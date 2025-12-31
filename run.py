#!/usr/bin/env python3
"""Simple runner script for Lares."""

import sys
import os

sys.path.insert(0, 'src')

# Load .env file first, before checking any env vars
from dotenv import load_dotenv
load_dotenv()

# Configure SSL certificates using certifi (fixes macOS certificate issues)
# This must happen BEFORE importing discord or aiohttp
import certifi
import ssl
os.environ["SSL_CERT_FILE"] = certifi.where()
# Configure default SSL context for urllib/aiohttp
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# Enable context monitoring BEFORE importing memory module
# This must happen before any imports from lares.memory
if os.getenv("LARES_CONTEXT_MONITORING", "false").lower() == "true":
    try:
        from lares.monitoring_patch import apply_monitoring_patch
        analyzer = apply_monitoring_patch()
        print("[MAIN] Context monitoring activated", flush=True)
    except Exception as e:
        print(f"WARNING: Context monitoring failed with error: {e}", flush=True)
        import traceback
        traceback.print_exc()

import asyncio

import discord

from lares.config import load_config
from lares.discord_bot import create_bot
from lares.logging_config import get_logger, setup_logging
from lares.memory import create_letta_client, get_or_create_agent
from lares.tool_registry import register_tools_with_letta


async def run() -> None:
    """Async main function."""
    print("Starting Lares...", flush=True)

    config = load_config()
    print(f"Config loaded. Agent: {config.agent_id}", flush=True)

    # Initialize logging system
    setup_logging(config)
    log = get_logger("main")
    log.info("lares_starting", version="0.1.0", config_loaded=True)

    # Log if monitoring was enabled (it was already set up before imports)
    if os.getenv("LARES_CONTEXT_MONITORING", "false").lower() == "true":
        log.info("context_monitoring_enabled")
        print("Context monitoring is active", flush=True)

    client = create_letta_client(config)
    log.info("letta_client_ready")
    print("Letta client ready", flush=True)

    # Get or create agent (also updates model if changed)
    agent_id = await get_or_create_agent(client, config)
    log.info("agent_ready", agent_id=agent_id)
    print(f"Agent ready: {agent_id}", flush=True)

    # Register tools with Letta
    registered_tools = register_tools_with_letta(client, agent_id)
    log.info("tools_registered", tools=registered_tools)
    print(f"Tools registered: {len(registered_tools)}", flush=True)

    bot = create_bot(config, client, agent_id)
    log.info("discord_bot_created")
    print("Connecting to Discord...", flush=True)

    await bot.start(config.discord.bot_token)


def main():
    try:
        asyncio.run(run())

    except KeyboardInterrupt:
        log = get_logger("main")
        log.info("lares_shutdown", reason="keyboard_interrupt")
        print("\nLares shutting down gracefully...", flush=True)

    except discord.errors.PrivilegedIntentsRequired as e:
        log = get_logger("main")
        log.error("discord_privileged_intents_required", error=str(e))
        print("\n" + "=" * 70, flush=True, file=sys.stderr)
        print("DISCORD PRIVILEGED INTENTS REQUIRED", flush=True, file=sys.stderr)
        print("=" * 70, flush=True, file=sys.stderr)
        print("\nLares requires the 'MESSAGE CONTENT INTENT' to be enabled.", flush=True, file=sys.stderr)
        print("\nTo fix this:", flush=True, file=sys.stderr)
        print("1. Go to https://discord.com/developers/applications/", flush=True, file=sys.stderr)
        print("2. Select your bot application", flush=True, file=sys.stderr)
        print("3. Navigate to the 'Bot' section in the left sidebar", flush=True, file=sys.stderr)
        print("4. Scroll down to 'Privileged Gateway Intents'", flush=True, file=sys.stderr)
        print("5. Enable 'MESSAGE CONTENT INTENT'", flush=True, file=sys.stderr)
        print("6. Save changes", flush=True, file=sys.stderr)
        print("\nNote: This is required for the bot to read message content.", flush=True, file=sys.stderr)
        print("=" * 70 + "\n", flush=True, file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        log = get_logger("main")
        log.error("lares_startup_failed", error=str(e), error_type=type(e).__name__)
        print(f"Fatal error: {e}", flush=True, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
