"""Registry for Letta tools with client-side execution."""

import asyncio
import os
import re
import traceback
from typing import Any

import aiohttp
import discord
import structlog
from letta_client import Letta

from lares.config import ToolsConfig
from lares.memory import PendingToolCall
from lares.obsidian import add_journal_entry as obsidian_add_journal_entry
from lares.obsidian import append_to_note as obsidian_append_to_note
from lares.obsidian import list_notes as obsidian_list_notes
from lares.obsidian import read_note as obsidian_read_note
from lares.obsidian import search_notes as obsidian_search_notes
from lares.obsidian import write_note as obsidian_write_note
from lares.tools import (
    CommandNotAllowedError,
    FileBlockedError,
    InvalidToolCodeError,
    PathNotAllowedError,
    add_to_allowlist,
    list_jobs,
    react,
    read_file,
    read_rss_feed,
    remove_job,
    restart_lares,
    restart_mcp,
    run_command,
    schedule_job,
    send_message,
    validate_tool_code,
    write_file,
)
from lares.tools.google_calendar import (
    list_upcoming_events,
    create_event,
    search_events,
)

log = structlog.get_logger()

class ToolExecutor:
    """Executes tools with approval workflow support."""

    def __init__(
        self,
        tools_config: ToolsConfig,
        letta_client: Letta | None = None,
        agent_id: str | None = None,
        discord_channel: discord.TextChannel | None = None,
        mcp_url: str | None = None,
    ):
        self.config = tools_config
        self.letta_client = letta_client
        self.agent_id = agent_id
        self.channel = discord_channel
        self.mcp_url = mcp_url

    def set_channel(self, channel: discord.TextChannel) -> None:
        """Set the Discord channel for approval requests."""
        self.channel = channel

    def set_letta_context(self, client: Letta, agent_id: str) -> None:
        """Set the Letta client and agent ID for tool creation."""
        self.letta_client = client
        self.agent_id = agent_id

    async def _request_mcp_approval(self, tool_name: str, args: dict) -> str:
        """Submit a tool call to MCP approval queue."""
        import json
        log.info("requesting_mcp_approval", tool=tool_name)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.mcp_url}/approvals",
                    json={"tool": tool_name, "args": json.dumps(args)}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        approval_id = data.get("id", "unknown")
                        return f"⏳ Queued for approval (ID: {approval_id}). React ✅ to approve or ❌ to deny."
                    else:
                        error = await resp.text()
                        return f"Failed to queue approval: {error}"
        except Exception as e:
            log.error("mcp_approval_request_failed", error=str(e))
            return f"Failed to request approval: {e}"

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result as a string for Letta."""
        try:
            if tool_name == "run_command":
                result = await self._run_command(
                    arguments.get("command", ""),
                    arguments.get("working_dir"),
                )
            elif tool_name == "read_file":
                result = self._read_file(arguments.get("path", ""))
            elif tool_name == "write_file":
                result = self._write_file(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                )
            elif tool_name == "create_tool":
                result = self._create_tool(arguments.get("source_code", ""))
            elif tool_name == "schedule_job":
                result = self._schedule_job(
                    arguments.get("job_id", ""),
                    arguments.get("prompt", ""),
                    arguments.get("schedule", ""),
                    arguments.get("description", ""),
                )
            elif tool_name == "remove_job":
                result = self._remove_job(arguments.get("job_id", ""))
            elif tool_name == "list_jobs":
                result = self._list_jobs()
            elif tool_name == "read_rss_feed":
                result = self._read_rss_feed(
                    arguments.get("url", ""),
                    arguments.get("max_entries", 5),
                )
            elif tool_name == "discord_send_message":
                result = await self._discord_send_message(
                    arguments.get("content", ""),
                    arguments.get("reply", False),
                )
            elif tool_name == "discord_react":
                result = await self._discord_react(arguments.get("emoji", ""))
            elif tool_name == "restart_lares":
                result = await self._restart_lares()
            elif tool_name == "restart_mcp":
                result = await self._restart_mcp()
            elif tool_name == "search_obsidian_notes":
                result = self._search_obsidian_notes(
                    arguments.get("query", ""),
                    arguments.get("max_results", 10),
                )
            elif tool_name == "read_obsidian_note":
                path = arguments.get("path", "")
                log.info("read_obsidian_note_called", path=path, args=arguments)
                result = self._read_obsidian_note(path)
                log.info("read_obsidian_note_result", path=path, result_len=len(result),
                    result_preview=result[:100] if result else None)
            elif tool_name == "write_obsidian_note":
                result = self._write_obsidian_note(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                    arguments.get("overwrite", False),
                )
            elif tool_name == "append_to_obsidian_note":
                result = self._append_to_obsidian_note(
                    arguments.get("path", ""),
                    arguments.get("content", ""),
                    arguments.get("separator", "\n\n"),
                )
            elif tool_name == "list_obsidian_notes":
                result = self._list_obsidian_notes(
                    arguments.get("directory", ""),
                    arguments.get("include_subdirs", False),
                )
            elif tool_name == "add_obsidian_journal_entry":
                result = self._add_obsidian_journal_entry(
                    arguments.get("entry", ""),
                    arguments.get("journal_folder", "Journal"),
                    arguments.get("entry_time", True),
                )
            elif tool_name == "list_calendar_events":
                result = self._list_calendar_events(arguments.get("max_results", 10))
            elif tool_name == "create_calendar_event":
                result = await self._create_calendar_event(
                    arguments.get("summary", ""),
                    arguments.get("start_time", ""),
                    arguments.get("end_time", ""),
                    arguments.get("description", ""),
                )
            elif tool_name == "search_calendar_events":
                result = self._search_calendar_events(
                    arguments.get("query", ""),
                    arguments.get("max_results", 10),
                )
            elif tool_name in {"note", "note_tool"}:
                result = self._note_tool(arguments)
            else:
                result = f"Unknown tool: {tool_name}"
            
            # Log if tool returned an error string (not an exception)
            if isinstance(result, str) and result.startswith("Error"):
                log.warning(
                    "tool_returned_error",
                    tool=tool_name,
                    error_string=result,
                    arguments=arguments
                )
            
            return result
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            error_traceback = traceback.format_exc()
            log.error(
                "tool_execution_error",
                tool=tool_name,
                error=error_msg,
                error_type=type(e).__name__,
                traceback=error_traceback
            )
            return f"Error executing {tool_name}: {error_msg}"

    async def execute_tool(self, tool_call: PendingToolCall) -> str:
        """Execute a tool from a PendingToolCall object."""
        try:
            # Parse arguments if they're a string
            arguments = tool_call.arguments
            if isinstance(arguments, str):
                try:
                    import json
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
            elif not isinstance(arguments, dict):
                arguments = {}
            
            return await self.execute(tool_call.name, arguments)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            error_traceback = traceback.format_exc()
            log.error(
                "tool_execution_error",
                tool=tool_call.name,
                error=error_msg,
                error_type=type(e).__name__,
                traceback=error_traceback
            )
            return f"Error executing {tool_call.name}: {error_msg}"

    def _note_tool(self, arguments: dict[str, Any]) -> str:
        """Manage Letta notes stored as memory blocks."""
        if not self.letta_client or not self.agent_id:
            return "Error: Letta client not configured for note tool"

        command = arguments.get("command")
        path = arguments.get("path")
        content = arguments.get("content")
        old_str = arguments.get("old_str")
        new_str = arguments.get("new_str")
        new_path = arguments.get("new_path")
        insert_line = arguments.get("insert_line")
        query = arguments.get("query")
        search_type = arguments.get("search_type", "label")

        if not command:
            return "Error: 'command' is required"

        all_commands = [
            "create",
            "view",
            "attach",
            "detach",
            "insert",
            "append",
            "replace",
            "rename",
            "copy",
            "delete",
            "list",
            "search",
            "attached",
        ]
        enabled_env = os.environ.get("ENABLED_COMMANDS", "all")
        if enabled_env in ("all", "*"):
            enabled = all_commands
        else:
            enabled = [item.strip() for item in enabled_env.split(",") if item.strip()]
        if command not in enabled:
            return f"Error: '{command}' is disabled. Enabled: {enabled}"

        path_required = {
            "create",
            "view",
            "attach",
            "detach",
            "insert",
            "append",
            "replace",
            "rename",
            "copy",
            "delete",
        }
        if command in path_required and not path:
            return f"Error: '{command}' requires path parameter"

        if command == "replace" and (not old_str or new_str is None):
            return "Error: 'replace' requires old_str and new_str parameters"

        if command in {"create", "insert", "append"} and not content:
            return f"Error: '{command}' requires content parameter"

        if command in {"rename", "copy"} and not new_path:
            return f"Error: '{command}' requires new_path parameter"

        if command == "search" and not query:
            return "Error: 'search' requires query parameter"

        uuid_pattern = re.compile(r"/\[?agent-[a-f0-9-]+\]?/")
        client = self.letta_client
        agent_id = self.agent_id

        update_directory = False
        result = None

        try:
            if command == "create":
                existing = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if existing:
                    return f"Error: Note already exists: {path}"

                client.blocks.create(
                    label=path,
                    value=content,
                    description=f"owner:{agent_id}",
                )
                update_directory = True
                result = f"Created: {path}"

            elif command == "view":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"
                return blocks[0].value

            elif command == "attach":
                agent = client.agents.retrieve(agent_id=agent_id)
                attached_ids = {b.id for b in agent.memory.blocks}

                if path.endswith("/*"):
                    prefix = path[:-1]
                    all_blocks = list(client.blocks.list(description_search=agent_id).items)
                    blocks = [
                        b
                        for b in all_blocks
                        if b.label
                        and b.label.startswith(prefix)
                        and not uuid_pattern.search(b.label)
                    ]
                    if not blocks:
                        return f"No notes matching: {path}"

                    to_attach = [b for b in blocks if b.id not in attached_ids]
                    skipped = len(blocks) - len(to_attach)
                    for block in to_attach:
                        client.agents.blocks.attach(agent_id=agent_id, block_id=block.id)

                    msg = f"Attached {len(to_attach)} notes matching {path}"
                    if skipped:
                        msg += f" ({skipped} already attached)"
                    return msg

                existing = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if existing:
                    block_id = existing[0].id
                    if block_id in attached_ids:
                        return f"Already attached: {path}"
                else:
                    new_block = client.blocks.create(
                        label=path,
                        value=content or "",
                        description=f"owner:{agent_id}",
                    )
                    block_id = new_block.id
                    update_directory = True

                client.agents.blocks.attach(agent_id=agent_id, block_id=block_id)
                result = f"Attached: {path}"

            elif command == "detach":
                if path.endswith("/*"):
                    prefix = path[:-1]
                    agent = client.agents.retrieve(agent_id=agent_id)
                    attached_ids = {b.id for b in agent.memory.blocks}
                    all_blocks = list(client.blocks.list(description_search=agent_id).items)
                    blocks = [
                        b
                        for b in all_blocks
                        if b.label
                        and b.label.startswith(prefix)
                        and not uuid_pattern.search(b.label)
                        and b.id in attached_ids
                    ]
                    if not blocks:
                        return f"No attached notes matching: {path}"
                    for block in blocks:
                        client.agents.blocks.detach(agent_id=agent_id, block_id=block.id)
                    return f"Detached {len(blocks)} notes matching {path}"

                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"

                client.agents.blocks.detach(agent_id=agent_id, block_id=blocks[0].id)
                return f"Detached: {path}"

            elif command == "insert":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}. Use 'attach' first."

                block = blocks[0]
                lines = block.value.split("\n") if block.value else []
                line_info = "end"
                if insert_line is not None:
                    try:
                        line_idx = int(insert_line)
                    except (TypeError, ValueError):
                        line_idx = None
                    if line_idx is not None:
                        lines.insert(line_idx, content)
                        line_info = f"line {line_idx}"
                    else:
                        lines.append(content)
                else:
                    lines.append(content)

                client.blocks.update(block_id=block.id, value="\n".join(lines))
                preview = content[:80] + ("..." if len(content) > 80 else "")
                return f"Inserted at {line_info} in {path}:\n  + {preview}"

            elif command == "append":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}. Use 'attach' first."

                block = blocks[0]
                if block.value:
                    new_value = block.value + "\n" + content
                else:
                    new_value = content

                client.blocks.update(block_id=block.id, value=new_value)
                preview = content[:80] + ("..." if len(content) > 80 else "")
                return f"Appended to {path}:\n  + {preview}"

            elif command == "replace":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"

                block = blocks[0]
                if old_str not in (block.value or ""):
                    return "Error: old_str not found in note. Exact match required."

                new_value = (block.value or "").replace(old_str, new_str, 1)
                client.blocks.update(block_id=block.id, value=new_value)
                return f"Replaced in {path}:\n  - {old_str}\n  + {new_str}"

            elif command == "rename":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"

                dest_blocks = list(
                    client.blocks.list(label=new_path, description_search=agent_id).items
                )
                if dest_blocks:
                    return f"Error: Destination already exists: {new_path}"

                block = blocks[0]
                client.blocks.update(block_id=block.id, label=new_path)
                update_directory = True
                result = f"Renamed: {path} -> {new_path}"

            elif command == "copy":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"

                dest_blocks = list(
                    client.blocks.list(label=new_path, description_search=agent_id).items
                )
                if dest_blocks:
                    return f"Error: Destination already exists: {new_path}"

                source = blocks[0]
                client.blocks.create(
                    label=new_path,
                    value=source.value,
                    description=f"owner:{agent_id}",
                )
                update_directory = True
                result = f"Copied: {path} -> {new_path}"

            elif command == "delete":
                blocks = list(
                    client.blocks.list(label=path, description_search=agent_id).items
                )
                if not blocks:
                    return f"Note not found: {path}"

                client.blocks.delete(block_id=blocks[0].id)
                update_directory = True
                result = f"Deleted: {path}"

            elif command == "list":
                all_blocks = list(client.blocks.list(description_search=agent_id).items)
                blocks = [
                    b
                    for b in all_blocks
                    if b.label
                    and b.label.startswith("/")
                    and not uuid_pattern.search(b.label)
                ]
                if query and query != "*":
                    blocks = [b for b in blocks if b.label.startswith(query)]

                if not blocks:
                    return "No notes found" if not query or query == "*" else f"No notes matching: {query}"

                labels = sorted({b.label for b in blocks})
                return "\n".join(labels)

            elif command == "search":
                all_blocks = list(client.blocks.list(description_search=agent_id).items)
                all_blocks = [
                    b
                    for b in all_blocks
                    if b.label
                    and b.label.startswith("/")
                    and not uuid_pattern.search(b.label)
                ]

                if search_type == "label":
                    blocks = [b for b in all_blocks if query in b.label]
                else:
                    blocks = [b for b in all_blocks if b.value and query in b.value]

                if not blocks:
                    return f"No notes matching: {query}"

                results = []
                for b in blocks:
                    preview = b.value[:100].replace("\n", " ") if b.value else ""
                    if len(b.value or "") > 100:
                        preview += "..."
                    results.append(f"{b.label}: {preview}")

                return "\n".join(results)

            elif command == "attached":
                agent = client.agents.retrieve(agent_id=agent_id)
                note_blocks = [
                    b
                    for b in agent.memory.blocks
                    if b.label
                    and b.label.startswith("/")
                    and not uuid_pattern.search(b.label)
                ]
                if not note_blocks:
                    return "No notes currently attached"
                return "\n".join(sorted(b.label for b in note_blocks))

            else:
                return f"Error: Unknown command '{command}'"

            if update_directory:
                self._update_note_directory(client, agent_id, uuid_pattern)

            if result:
                return result

        except Exception as e:
            return f"Error executing '{command}': {e}"

        return ""

    def _update_note_directory(self, client: Letta, agent_id: str, uuid_pattern: re.Pattern) -> None:
        dir_label = "/note_directory"
        all_blocks = list(client.blocks.list(description_search=agent_id).items)
        notes = [
            b
            for b in all_blocks
            if b.label
            and b.label.startswith("/")
            and b.label != dir_label
            and not uuid_pattern.search(b.label)
        ]

        header = (
            "External storage. Attach to load into context, detach when done.\n"
            "Folders are also notes (e.g., /projects and /projects/task1 can both have content).\n"
            "Commands: view, attach, detach, insert, append, replace, rename, copy, delete, list, search\n"
            "Bulk: attach /folder/*, detach /folder/*"
        )

        if notes:
            folders: dict[str, list[tuple[str, str]]] = {}
            for b in sorted(notes, key=lambda x: x.label):
                parts = b.label.rsplit("/", 1)
                if len(parts) == 2:
                    folder, name = parts[0] + "/", parts[1]
                else:
                    folder, name = "/", b.label[1:]
                if folder not in folders:
                    folders[folder] = []
                first_line = (b.value or "").split("\n")[0][:80]
                if len((b.value or "").split("\n")[0]) > 80:
                    first_line += "..."
                folders[folder].append((name, first_line))

            lines: list[str] = []
            for folder in sorted(folders.keys()):
                lines.append(folder)
                items = folders[folder]
                max_name_len = max(len(name) for name, _ in items)
                for name, summary in items:
                    lines.append(f"  {name.ljust(max_name_len)} | {summary}")

            dir_content = header + "\n\n" + "\n".join(lines)
        else:
            dir_content = header + "\n\n(no notes)"

        dir_blocks = list(client.blocks.list(label=dir_label, description_search=agent_id).items)
        if dir_blocks:
            client.blocks.update(block_id=dir_blocks[0].id, value=dir_content)
        else:
            dir_block = client.blocks.create(
                label=dir_label,
                value=dir_content,
                description=f"owner:{agent_id}",
            )
            client.agents.blocks.attach(agent_id=agent_id, block_id=dir_block.id)

    async def _run_command(self, command: str, working_dir: str | None) -> str:
        """Execute a command, requesting approval if needed."""
        try:
            result = run_command(
                command,
                self.config.command_allowlist,
                working_dir,
            )
            output = str(result["stdout"])
            if result["stderr"]:
                output += f"\n[stderr]: {result['stderr']}"
            if result["returncode"] != 0:
                output += f"\n[exit code: {result['returncode']}]"
            return output

        except CommandNotAllowedError:
            # Request approval via MCP queue if available
            if self.mcp_url:
                return await self._request_mcp_approval(
                    "run_shell_command",
                    {"command": command, "working_dir": str(working_dir)}
                )

            # Fall back to old Discord channel approach
            if self.channel is None:
                return f"Command not allowed and no Discord channel for approval: {command}"

            log.info("requesting_command_approval", command=command)

            _, future = await request_command_approval(self.channel, command)

            try:
                # Wait for approval (timeout after 5 minutes)
                approved = await asyncio.wait_for(future, timeout=300)

                if approved:
                    # Add to allowlist and retry
                    add_to_allowlist(
                        command,
                        self.config.allowlist_file,
                        self.config.command_allowlist,
                    )
                    await self.channel.send("✅ Command approved and added to allowlist!")

                    # Now run it
                    result = run_command(
                        command,
                        self.config.command_allowlist,
                        working_dir,
                    )
                    output = str(result["stdout"])
                    if result["stderr"]:
                        output += f"\n[stderr]: {result['stderr']}"
                    return output
                else:
                    return (
                        f"Command denied by Ja: {command}\n\n"
                        "(Ja saw this request and chose to deny it)"
                    )

            except TimeoutError:
                await self.channel.send(
                    f"⏰ Approval request timed out for: `{command}`\n"
                    "Lares has been notified."
                )
                return (
                    f"Approval request timed out after 5 minutes for command: {command}\n\n"
                    "(Ja has been notified of the timeout)"
                )

    def _read_file(self, path: str) -> str:
        """Read a file."""
        try:
            return read_file(path, self.config.allowed_paths, self.config.blocked_files)
        except PathNotAllowedError:
            return f"Error: Path not in allowed directories: {path}"
        except FileBlockedError:
            return f"Error: File is blocked (may contain secrets): {path}"

    def _write_file(self, path: str, content: str) -> str:
        """Write a file."""
        try:
            return write_file(
                path, content, self.config.allowed_paths, self.config.blocked_files
            )
        except PathNotAllowedError:
            return f"Error: Path not in allowed directories: {path}"
        except FileBlockedError:
            return f"Error: File is blocked (may contain secrets): {path}"

    def _create_tool(self, source_code: str) -> str:
        """Create a new tool from Python source code."""
        if not self.letta_client or not self.agent_id:
            return "Error: Letta client not configured for tool creation"

        # Validate the source code
        try:
            func_name, docstring = validate_tool_code(source_code)
        except InvalidToolCodeError as e:
            return f"Error: {e}"

        # Register the tool with Letta
        try:
            tool = self.letta_client.tools.upsert(
                source_code=source_code,
                default_requires_approval=False,  # Lares-created tools run in sandbox
            )

            # Attach to agent
            try:
                self.letta_client.agents.tools.attach(
                    agent_id=self.agent_id, tool_id=tool.id
                )
            except Exception:
                # May already be attached (update case)
                pass

            log.info("tool_created", name=func_name, tool_id=tool.id)
            return f"Successfully created tool '{func_name}': {docstring[:100]}..."

        except Exception as e:
            log.error("tool_creation_failed", name=func_name, error=str(e))
            return f"Error creating tool: {e}"

    def _schedule_job(
        self, job_id: str, prompt: str, schedule: str, description: str
    ) -> str:
        """Schedule a job."""
        return schedule_job(job_id, prompt, schedule, description)

    def _remove_job(self, job_id: str) -> str:
        """Remove a scheduled job."""
        return remove_job(job_id)

    def _list_jobs(self) -> str:
        """List all scheduled jobs."""
        return list_jobs()

    def _read_rss_feed(self, url: str, max_entries: int) -> str:
        """Read an RSS feed."""
        return read_rss_feed(url, max_entries=max_entries)


    async def _discord_send_message(self, content: str, reply: bool) -> str:
        """Send a message to Discord."""
        # Check if Discord context is available
        from lares.tools.discord import _discord_channel
        if _discord_channel is None:
            log.warning(
                "discord_context_missing",
                tool="discord_send_message",
                message="Discord channel context not set"
            )
        result = await send_message(content, reply=reply)
        if result.startswith("Error"):
            log.warning("discord_send_message_failed", error=result, content_preview=content[:50])
        return result

    async def _discord_react(self, emoji: str) -> str:
        """React to the current message with an emoji."""
        # Check if Discord context is available
        from lares.tools.discord import _current_message
        if _current_message is None:
            log.warning(
                "discord_context_missing",
                tool="discord_react",
                message="Discord message context not set"
            )
        result = await react(emoji)
        if result.startswith("Error"):
            log.warning("discord_react_failed", error=result, emoji=emoji)
        return result

    async def _restart_lares(self) -> str:
        """Restart the Lares service."""
        return await restart_lares()

    async def _restart_mcp(self) -> str:
        """Restart only the MCP server."""
        return await restart_mcp()

    def _search_obsidian_notes(self, query: str, max_results: int) -> str:
        """Search notes in the Obsidian vault."""
        try:
            return obsidian_search_notes(query, max_results=max_results)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_search_error", query=query, error=error_msg, error_type=type(e).__name__)
            return f"Error searching Obsidian notes: {error_msg}"

    def _read_obsidian_note(self, path: str) -> str:
        """Read a specific note from the Obsidian vault."""
        log.info("_read_obsidian_note_wrapper", path=path)
        try:
            result = obsidian_read_note(path)
            log.info("_obsidian_read_result", path=path, result_len=len(result) if result else 0,
                    result_preview=result[:100] if result else None)
            return result
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_read_error", path=path, error=error_msg, error_type=type(e).__name__)
            return f"Error reading Obsidian note: {error_msg}"

    def _write_obsidian_note(self, path: str, content: str, overwrite: bool) -> str:
        """Create or write a note in the Obsidian vault."""
        try:
            return obsidian_write_note(path, content, overwrite=overwrite)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_write_error", path=path, error=error_msg, error_type=type(e).__name__)
            return f"Error writing Obsidian note: {error_msg}"

    def _append_to_obsidian_note(self, path: str, content: str, separator: str) -> str:
        """Append content to an Obsidian note."""
        try:
            return obsidian_append_to_note(path, content, separator=separator)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_append_error", path=path, error=error_msg, error_type=type(e).__name__)
            return f"Error appending to Obsidian note: {error_msg}"

    def _list_obsidian_notes(self, directory: str, include_subdirs: bool) -> str:
        """List notes in the Obsidian vault."""
        try:
            return obsidian_list_notes(directory=directory, include_subdirs=include_subdirs)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_list_error", directory=directory, error=error_msg, error_type=type(e).__name__)
            return f"Error listing Obsidian notes: {error_msg}"

    def _add_obsidian_journal_entry(self, entry: str, journal_folder: str, entry_time: bool) -> str:
        """Add a journal entry to today's Obsidian note."""
        try:
            return obsidian_add_journal_entry(entry, journal_folder=journal_folder, entry_time=entry_time)
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__} (no message)"
            log.error("obsidian_journal_error", error=error_msg, error_type=type(e).__name__)
            return f"Error adding Obsidian journal entry: {error_msg}"

    def _list_calendar_events(self, max_results: int) -> str:
        """List calendar events."""
        return list_upcoming_events(max_results=max_results)

    async def _create_calendar_event(
        self, summary: str, start_time: str, end_time: str, description: str
    ) -> str:
        """Create calendar event with approval."""
        # Calendar modifications require approval
        approval_id = self.approval_queue.submit(
            "create_calendar_event",
            {
                "summary": summary,
                "start_time": start_time,
                "end_time": end_time,
                "description": description,
            }
        )

        if self.mcp_url:
            return await self._request_mcp_approval(
                "create_calendar_event",
                {
                    "summary": summary,
                    "start_time": start_time,
                    "end_time": end_time,
                    "description": description,
                }
            )

        # Fallback to Discord approval
        if self.channel is None:
            return "Error: No approval mechanism available for calendar event creation"

        # Request approval via Discord
        embed = discord.Embed(
            title="📅 Calendar Event Creation",
            description=f"**{summary}**\n{start_time} - {end_time}",
            color=discord.Color.blue(),
        )
        if description:
            embed.add_field(name="Description", value=description, inline=False)

        message = await self.channel.send(embed=embed)
        await message.add_reaction("✅")
        await message.add_reaction("❌")

        return f"📅 Calendar event queued for approval (message #{message.id})"

    def _search_calendar_events(self, query: str, max_results: int) -> str:
        """Search calendar events."""
        return search_events(query=query, max_results=max_results)


# Tool definitions for Letta registration
TOOL_SOURCES = {
    "note": '''
def note(
    command: str,
    path: str = None,
    content: str = None,
    old_str: str = None,
    new_str: str = None,
    new_path: str = None,
    insert_line: int = None,
    query: str = None,
    search_type: str = "label",
) -> str:
    """
    Manage notes in your vault. All notes are automatically scoped to your agent.

    Commands:
      create <path> <content>             - create new note (not attached)
      view <path>                         - read note contents
      attach <path> [content]             - load into context (supports /folder/*)
      detach <path>                       - remove from context (supports /folder/*)
      insert <path> <content> [line]      - insert before line (0-indexed) or append
      append <path> <content>             - add content to end of note
      replace <path> <old_str> <new_str>  - find/replace, shows diff
      rename <path> <new_path>            - move/rename note to new path
      copy <path> <new_path>              - duplicate note to new path
      delete <path>                       - permanently remove
      list [query]                        - list notes (prefix filter, * for all)
      search <query> [label|content]      - grep notes by label or content
      attached                            - show notes currently in context

    Args:
        command: The operation to perform
        path: Path to the note (e.g., /projects/webapp, /todo)
        content: Content to insert or initial content when creating
        old_str: Text to find (for replace)
        new_str: Text to replace with (for replace)
        new_path: Destination path (for rename/copy)
        insert_line: Line number to insert before (0-indexed, omit to append)
        query: Search query (for list/search)
        search_type: Search by "label" or "content"

    Returns:
        Result of the operation
    """
    raise Exception("Client-side tool")
''',
    "run_command": '''
def run_command(command: str, working_dir: str = None) -> str:
    """
    Execute a shell command on the local machine.

    Use this for: git operations, running tests, checking code with linters.
    Common commands: git status, git push, pytest, ruff check, mypy, ls, cat.
    Commands not in the allowlist will require human approval.

    Args:
        command: The shell command to execute
        working_dir: Working directory (optional, defaults to project root)

    Returns:
        Command output (stdout and stderr)
    """
    raise Exception("Client-side tool")
''',
    "read_file": '''
def read_file(path: str) -> str:
    """
    Read a file from the local filesystem.

    Use this to examine source code, read documentation, or check configs.
    Only files in allowed paths can be read.
    Sensitive files (.env, credentials) are blocked.

    Args:
        path: Absolute path to the file to read

    Returns:
        File contents as a string
    """
    raise Exception("Client-side tool")
''',
    "write_file": '''
def write_file(path: str, content: str) -> str:
    """
    Write content to a file on the local filesystem.

    Use this to create or modify source code, documentation, or configuration.
    Only files in allowed paths can be written. Sensitive files are blocked.

    Args:
        path: Absolute path to the file to write
        content: Content to write to the file

    Returns:
        Success or error message
    """
    raise Exception("Client-side tool")
''',
    "create_tool": '''
def create_tool(source_code: str) -> str:
    """
    Create a new tool from Python source code.

    Use this to extend your own capabilities by creating new tools.
    The last top-level function becomes the tool entry point and must have a docstring.
    Helper functions are allowed and encouraged for clean, modular code.
    Import statements are not allowed - tools run in Letta's sandbox.

    IMPORTANT: This tool requires human approval before execution.

    Args:
        source_code: Python code with the main function last (helpers allowed)

    Returns:
        Success message with tool name, or error description
    """
    raise Exception("Client-side tool")
''',
    "schedule_job": '''
def schedule_job(job_id: str, prompt: str, schedule: str, description: str = "") -> str:
    """
    Schedule a job to trigger with a prompt at specified times.

    Use this to set reminders, recurring tasks, or timed notifications.
    Jobs are checked during perch time ticks.

    Args:
        job_id: Unique identifier for the job (used to remove it later)
        prompt: The prompt/message to send when the job triggers
        schedule: When to run:
            - ISO datetime for one-time: "2025-12-25T09:00:00"
            - Simple intervals: "every 2 hours", "every day at 9:00"
        description: Human-readable description of what this job does

    Returns:
        Success or error message
    """
    raise Exception("Client-side tool")
''',
    "remove_job": '''
def remove_job(job_id: str) -> str:
    """
    Remove a scheduled job.

    Args:
        job_id: The ID of the job to remove

    Returns:
        Success or error message
    """
    raise Exception("Client-side tool")
''',
    "list_jobs": '''
def list_jobs() -> str:
    """
    List all scheduled jobs.

    Returns:
        Formatted list of jobs with their schedules and descriptions
    """
    raise Exception("Client-side tool")
''',
    "read_rss_feed": '''
def read_rss_feed(url: str, max_entries: int = 5) -> str:
    """
    Read and parse an RSS or Atom feed from the given URL.

    Use this to monitor news, blogs, or any site with an RSS feed.
    Great for staying updated on topics of interest.

    Args:
        url: The URL of the RSS/Atom feed to read
        max_entries: Maximum number of entries to return (default 5)

    Returns:
        Formatted string containing feed entries with titles, dates, and summaries
    """
    raise Exception("Client-side tool")
''',
    "discord_send_message": '''
def discord_send_message(content: str, reply: bool = False) -> str:
    """
    Send a message to the Discord channel.

    Use this to communicate with Ja. You can send updates, ask questions,
    share findings, or just chat.

    Args:
        content: The message text to send
        reply: If True, reply to the triggering message (default False)

    Returns:
        Success or error message
    """
    raise Exception("Client-side tool")
''',
    "discord_react": '''
def discord_react(emoji: str) -> str:
    """
    React to the current message with an emoji.

    Use this to acknowledge messages, show emotions, or give quick feedback.
    Common emojis: 👀 (looking), ✅ (done), 👍 (ok), ❤️ (love), 🎉 (celebrate)

    Args:
        emoji: The emoji to react with (e.g., "👀", "✅", "👍")

    Returns:
        Success or error message
    """
    raise Exception("Client-side tool")
''',
    "restart_lares": '''
def restart_lares() -> str:
    """
    Restart the Lares systemd service.

    Use this when:
    - Updates have been applied via git pull and need to take effect
    - Configuration changes (.env) require a restart
    - You want to perform periodic maintenance (clear memory, fresh start)
    - Recovery from suspected issues or unusual behavior

    This requires passwordless sudo access to be configured.
    Run scripts/setup-sudoers.sh during installation.

    Note: Lares will exit immediately and systemd will automatically restart it.
    You will be offline for a few seconds during the restart.

    Returns:
        Success message (though you'll restart before seeing it)
    """
    raise Exception("Client-side tool")
''',
    "search_obsidian_notes": '''
def search_obsidian_notes(query: str, max_results: int = 10) -> str:
    """
    Search for notes in the Obsidian vault containing the query string.

    Use this to find relevant notes, discover connections between topics,
    or look up information from past notes.

    Args:
        query: Text to search for (case-insensitive)
        max_results: Maximum number of matching notes to return (default 10)

    Returns:
        Formatted string with matching notes and context snippets
    """
    raise Exception("Client-side tool")
''',
    "read_obsidian_note": '''
def read_obsidian_note(path: str) -> str:
    """
    Read a specific note from the Obsidian vault.

    Use this to read the full content of a note found via search,
    or to access a known note by path.

    Args:
        path: Path to the note relative to vault root (e.g., "Diario/2025/01/2025-01-12.md")

    Returns:
        The full content of the note, or an error message if not found
    """
    raise Exception("Client-side tool")
''',
    "write_obsidian_note": '''
def write_obsidian_note(path: str, content: str, overwrite: bool = False) -> str:
    """
    Create or write a note in the Obsidian vault.

    Use this to create new notes or update existing ones.
    The .md extension is optional - it will be added automatically.

    Args:
        path: Path relative to vault root (e.g., "Projects/New Idea.md")
        content: The markdown content to write
        overwrite: If False (default), will not overwrite existing notes

    Returns:
        Success message or error description
    """
    raise Exception("Client-side tool")
''',
    "append_to_obsidian_note": '''
def append_to_obsidian_note(path: str, content: str, separator: str = "\\n\\n") -> str:
    """
    Append content to an existing note, or create it if it doesn't exist.

    Useful for adding to notes over time, like daily logs or running lists.

    Args:
        path: Path relative to vault root
        content: Content to append
        separator: String between existing and new content (default: two newlines)

    Returns:
        Success message or error description
    """
    raise Exception("Client-side tool")
''',
    "list_obsidian_notes": '''
def list_obsidian_notes(directory: str = "", include_subdirs: bool = False) -> str:
    """
    List notes in a directory of the Obsidian vault.

    Use this to explore the vault structure and discover what notes exist.

    Args:
        directory: Relative path to list (empty for vault root)
        include_subdirs: If True, recursively list all notes in subdirectories

    Returns:
        Formatted list of folders and notes
    """
    raise Exception("Client-side tool")
''',
    "add_obsidian_journal_entry": '''
def add_obsidian_journal_entry(entry: str, journal_folder: str = "Journal", entry_time: bool = True) -> str:
    """
    Add an entry to today's journal note.

    Creates a new journal file if one doesn't exist for today, with a date header.
    Automatically adds timestamps to entries for chronological tracking.

    Args:
        entry: The journal entry text
        journal_folder: Folder where journal entries live (default: "Journal")
        entry_time: Whether to prefix entry with timestamp (default: True)

    Returns:
        Success message or error description
    """
    raise Exception("Client-side tool")
''',
    "list_calendar_events": '''
def list_calendar_events(max_results: int = 10) -> str:
    """
    List upcoming events from Google Calendar.

    Use this to check your schedule and see what events are coming up.
    Shows events starting from now onwards.

    Args:
        max_results: Maximum number of events to return (default 10)

    Returns:
        Formatted list of upcoming calendar events with dates and times
    """
    raise Exception("Client-side tool")
''',
    "create_calendar_event": '''
def create_calendar_event(summary: str, start_time: str, end_time: str, description: str = "") -> str:
    """
    Create a new event in Google Calendar.

    Use this to schedule meetings, appointments, or reminders.
    Times should be in ISO format (e.g., "2025-01-15T10:00:00").

    IMPORTANT: This tool requires human approval before execution.

    Args:
        summary: Event title/summary
        start_time: Start time in ISO format (e.g., "2025-01-15T10:00:00")
        end_time: End time in ISO format (e.g., "2025-01-15T11:00:00")
        description: Optional event description

    Returns:
        Success message with event ID
    """
    raise Exception("Client-side tool")
''',
    "search_calendar_events": '''
def search_calendar_events(query: str, max_results: int = 10) -> str:
    """
    Search for events in Google Calendar containing the query text.

    Use this to find specific events by title, description, or other content.
    Searches across all your calendar events.

    Args:
        query: Search query string (searches titles and descriptions)
        max_results: Maximum number of results (default 10)

    Returns:
        Formatted list of matching events with dates and times
    """
    raise Exception("Client-side tool")
''',
}


def register_tools_with_letta(client: Letta, agent_id: str) -> list[str]:
    """
    Register client-side tools with a Letta agent.

    For Phase 1 MCP architecture, ALL tools must be registered with
    requires_approval=True so that Letta returns them as pending_tool_calls
    instead of trying to execute them in its sandbox.

    Returns list of registered tool names.
    """
    log.info("registering_tools", agent_id=agent_id)

    registered: list[str] = []
    tool_ids: list[str] = []

    for name, source_code in TOOL_SOURCES.items():
        try:
            # Phase 1 MCP: ALL tools require approval (returns as pending_tool_calls)
            # This prevents Letta from trying to execute them in its sandbox
            # where they would fail with "Client-side tool" exception
            needs_approval = True

            tool = client.tools.upsert(
                source_code=source_code,
                default_requires_approval=needs_approval,
            )
            log.info(
                "tool_registered", name=name, tool_id=tool.id, requires_approval=needs_approval
            )
            registered.append(name)
            tool_ids.append(tool.id)
        except Exception as e:
            log.error("tool_registration_failed", name=name, error=str(e))

    # Attach tools to the agent
    for tool_id in tool_ids:
        try:
            client.agents.tools.attach(agent_id=agent_id, tool_id=tool_id)
            log.info("tool_attached_to_agent", tool_id=tool_id, agent_id=agent_id)
        except Exception as e:
            # May already be attached
            log.warning("tool_attach_failed", tool_id=tool_id, error=str(e))

    return registered
