"""Discord bot interface for Lares.

Handles Discord message processing, tool execution, and perch time scheduling.
"""

import asyncio
import os
from datetime import datetime

import discord
from discord.ext import commands
import structlog
from letta_client import Letta

from lares.config import Config
from lares.memory import MessageResponse, send_message as send_letta_message
from lares.response_parser import DiscordAction, parse_response
from lares.scheduler import get_scheduler
from lares.time_utils import get_time_context
from lares.tool_registry import (
    ToolExecutor,
    handle_approval_reaction,
)
from lares.tools import set_discord_context, clear_discord_context

log = structlog.get_logger()

# Perch time interval in minutes
PERCH_INTERVAL_MINUTES = int(os.getenv("LARES_PERCH_INTERVAL_MINUTES", "30"))


def create_bot(config: Config, client: Letta, agent_id: str) -> commands.Bot:
    """
    Create and configure the Discord bot.

    Args:
        config: Application configuration
        client: Letta client instance
        agent_id: Agent ID for Letta

    Returns:
        Configured Discord bot instance

    Note:
        This bot requires the MESSAGE CONTENT INTENT to be enabled in the
        Discord Developer Portal. This is a privileged intent required for
        reading message content. Enable it at:
        https://discord.com/developers/applications/ -> Your Bot -> Privileged Gateway Intents
    """
    intents = discord.Intents.default()
    # MESSAGE CONTENT INTENT is required (privileged intent - must be enabled in Discord Developer Portal)
    intents.message_content = True
    intents.reactions = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    channel: discord.TextChannel | None = None

    # Create tool executor (channel will be set in on_ready)
    tool_executor = ToolExecutor(config.tools, client, agent_id, discord_channel=None)

    # Initialize scheduler
    scheduler = get_scheduler()

    async def process_message(message: discord.Message) -> None:
        """Process a Discord message through Letta."""
        if message.author == bot.user:
            return

        if message.channel.id != config.discord.channel_id:
            return

        log.info("processing_message", author=message.author.name, content=message.content[:50])

        # Set Discord context for tools
        set_discord_context(message.channel, bot, message)

        try:
            # Show typing indicator
            async with message.channel.typing():
                # Format message with time context
                current_time = get_time_context(config.user.timezone)
                formatted_message = (
                    f"{current_time}\n\n"
                    f"[Discord message from {message.author.display_name}]: {message.content}"
                )

                # Send to Letta (run in executor to avoid blocking)
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, send_letta_message, client, agent_id, formatted_message
                )

                # Handle memory compaction
                if response.needs_retry:
                    log.info("memory_compaction_during_message")
                    try:
                        await message.channel.send("💭 *Reorganizing my thoughts...*")
                    except Exception as notify_err:
                        log.error("compaction_notification_failed", error=str(notify_err))

                    # Retry without compaction retry flag
                    response = await loop.run_in_executor(
                        None,
                        send_letta_message,
                        client,
                        agent_id,
                        formatted_message,
                        False,  # retry_on_compaction=False
                    )

                # Process response and execute any tools
                await handle_response(response, message)

        except Exception as e:
            log.error("message_processing_failed", error=str(e))
            try:
                await message.channel.send(f"Error processing message: {e}")
            except Exception:
                pass
        finally:
            clear_discord_context()

    async def handle_response(response: MessageResponse, trigger_message: discord.Message) -> None:
        """Handle Letta response, executing tools and sending Discord actions."""
        # Execute pending tools first
        if response.pending_tool_calls:
            log.info("executing_tools", count=len(response.pending_tool_calls))
            for tool_call in response.pending_tool_calls:
                try:
                    result = await tool_executor.execute_tool(tool_call)
                    log.info("tool_executed", tool=tool_call.name, result_preview=str(result)[:50])

                    # Send tool result back to Letta
                    tool_result_message = f"Tool {tool_call.name} result: {result}"
                    loop = asyncio.get_event_loop()
                    tool_response = await loop.run_in_executor(
                        None, send_letta_message, client, agent_id, tool_result_message
                    )

                    # If tool execution triggered more tools, handle them
                    if tool_response.pending_tool_calls:
                        for followup_tool in tool_response.pending_tool_calls:
                            await tool_executor.execute_tool(followup_tool)

                except Exception as e:
                    log.error("tool_execution_failed", tool=tool_call.name, error=str(e))
                    error_message = f"Error executing {tool_call.name}: {e}"
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, send_letta_message, client, agent_id, error_message
                    )

        # Parse and execute Discord actions from response text
        if response.text:
            actions = parse_response(response.text)
            for action in actions:
                await execute_discord_action(action, trigger_message)

    async def execute_discord_action(action: DiscordAction, trigger_message: discord.Message) -> None:
        """Execute a Discord action (react, message, reply, silent)."""
        if action.type == "silent":
            return  # Do nothing

        if action.type == "react" and action.emoji:
            try:
                await trigger_message.add_reaction(action.emoji)
                log.info("discord_reaction_added", emoji=action.emoji)
            except Exception as e:
                log.error("discord_react_failed", emoji=action.emoji, error=str(e))

        elif action.type in ("message", "reply") and action.content:
            try:
                if action.type == "reply":
                    await trigger_message.reply(action.content)
                else:
                    await trigger_message.channel.send(action.content)
                log.info("discord_message_sent", type=action.type, preview=action.content[:50])
            except Exception as e:
                log.error("discord_send_failed", error=str(e))

    async def perch_time_tick() -> None:
        """Autonomous perch time tick - think, journal, and act."""
        if channel is None:
            return

        log.info("perch_time_tick", timestamp=datetime.now().isoformat())

        try:
            perch_prompt = f"""[PERCH TIME - {datetime.now().strftime("%Y-%m-%d %H:%M")}]

This is your autonomous perch time tick. You have {PERCH_INTERVAL_MINUTES} minutes between ticks.

Think about:
- What should I be working on?
- What information should I gather?
- What actions should I take?

Be proactive and useful. Use your tools to gather information, check on things, and take action."""

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, send_letta_message, client, agent_id, perch_prompt
            )

            # Handle memory compaction during perch time
            if response.needs_retry:
                log.info("memory_compaction_during_perch_time")
                response = await loop.run_in_executor(
                    None,
                    send_letta_message,
                    client,
                    agent_id,
                    perch_prompt,
                    False,  # retry_on_compaction=False
                )

            # Process response (tools and actions)
            # For perch time, we'll handle actions directly since there's no triggering message
            if response.pending_tool_calls:
                for tool_call in response.pending_tool_calls:
                    try:
                        result = await tool_executor.execute_tool(tool_call)
                        log.info("perch_tool_executed", tool=tool_call.name)

                        # Send tool result back to Letta
                        tool_result_message = f"Tool {tool_call.name} result: {result}"
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None, send_letta_message, client, agent_id, tool_result_message
                        )
                    except Exception as e:
                        log.error("perch_tool_failed", tool=tool_call.name, error=str(e))

            # Handle Discord actions from response
            if response.text:
                actions = parse_response(response.text)
                for action in actions:
                    if action.type == "silent":
                        continue
                    if action.type in ("message", "reply") and action.content and channel:
                        try:
                            await channel.send(action.content)
                            log.info("perch_message_sent", preview=action.content[:50])
                        except Exception as e:
                            log.error("perch_send_failed", error=str(e))
            log.info("perch_time_complete")

        except Exception as e:
            log.error("perch_time_failed", error=str(e))

    @bot.event
    async def on_ready() -> None:
        """Called when the bot is ready."""
        nonlocal channel
        channel = bot.get_channel(config.discord.channel_id)
        if channel:
            log.info("discord_connected", channel=channel.name)
            print(f"Discord connected to #{channel.name}")
            # Update tool executor with channel
            tool_executor.set_channel(channel)
        else:
            log.warning("discord_channel_not_found", channel_id=config.discord.channel_id)
            print(f"Warning: Could not find channel {config.discord.channel_id}")

        # Start scheduler
        async def job_callback(job_id: str, prompt: str) -> None:
            """Callback for scheduled jobs."""
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                send_letta_message,
                client,
                agent_id,
                f"[Scheduled job: {job_id}]\n{prompt}",
            )

        scheduler.set_callback(job_callback)
        scheduler.start()

        # Start perch time loop
        async def perch_time_loop() -> None:
            """Background task for periodic perch time ticks."""
            # Run initial perch tick after a short delay
            await asyncio.sleep(10)
            log.info("startup_perch_tick")
            await perch_time_tick()

            # Then run every PERCH_INTERVAL_MINUTES
            while True:
                await asyncio.sleep(PERCH_INTERVAL_MINUTES * 60)
                await perch_time_tick()

        asyncio.create_task(perch_time_loop())

        # Send startup message
        if channel:
            try:
                await channel.send("🦉 Jax is online")
            except Exception as e:
                log.error("startup_message_failed", error=str(e))

    @bot.event
    async def on_message(message: discord.Message) -> None:
        """Handle incoming Discord messages."""
        await process_message(message)

    @bot.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        """Handle reaction events for approvals."""
        if payload.user_id == bot.user.id:
            return

        if payload.channel_id != config.discord.channel_id:
            return

        emoji = str(payload.emoji)
        if emoji not in ("✅", "❌"):
            return

        # Handle approval reactions
        approved = emoji == "✅"
        result = await handle_approval_reaction(payload.message_id, emoji, payload.user_id)

        if result:
            log.info("approval_handled", message_id=payload.message_id, approved=approved)

    return bot
