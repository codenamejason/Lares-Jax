<p align="center">
  <img src="docs/logo.png" alt="Lares logo" width="250">
</p>


![Stability: Experimental](https://img.shields.io/badge/stability-experimental-red)

# Lares

A stateful AI agent with persistent memory - your household guardian.

Inspired by [Strix](https://timkellogg.me/blog/2025/12/15/strix), Lares is an ambient AI assistant that maintains memory across conversations, learns about you over time, and can act proactively.

## Features

- **Persistent Memory**: Uses [Letta](https://letta.com) for long-term memory that survives restarts
- **Discord Interface**: Chat with Lares through Discord
- **Memory Blocks**: Organized memory for identity, human preferences, state, and ideas
- **Autonomous Operation**: "Perch time" ticks every hour for self-reflection and proactive actions
- **Scheduled Tasks**: Set reminders and recurring jobs with flexible scheduling
- **Self-Management**: Can restart itself for updates and maintenance
- **Tool System**: File operations, shell commands, RSS feeds, BlueSky integration, and more
- **Skills System**: Procedural memory through markdown files - teaches Lares how to perform tasks
- **MCP Server**: Portable tool layer via Model Context Protocol - connect any MCP-compatible system
- **Extensible**: Designed for adding new interfaces (Telegram, web) and capabilities

## Quick Start

### Prerequisites

- Python 3.11+
- A [Letta Cloud](https://app.letta.com) account (or self-hosted Letta)
- A Discord bot token

### Installation

```bash
# Clone the repository
git clone https://git.v37.io/daniele/lares.git
cd lares

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# (Optional) Enable self-restart capability
# This allows Lares to restart itself for updates and maintenance
sudo bash scripts/setup-sudoers.sh
```

### Configuration

```bash
# Copy example config
cp .env.example .env

# Edit .env with your credentials:
# - LETTA_API_KEY: From app.letta.com (or use LETTA_BASE_URL for self-hosted)
# - DISCORD_BOT_TOKEN: From Discord Developer Portal
# - DISCORD_CHANNEL_ID: The channel where Lares will listen
# - ANTHROPIC_API_KEY: For the LLM (required for self-hosted Letta)

# Optional integrations:
# - BLUESKY_HANDLE: Your BlueSky handle (e.g., user.bsky.social)
# - BLUESKY_APP_PASSWORD: App password from BlueSky settings
# - OBSIDIAN_VAULT_PATH: Path to your Obsidian vault folder
# - LARES_MAX_TOOL_ITERATIONS: Max tool iterations per message (default: 10)
```

### Running

#### Docker Compose (Recommended)

Run all services in containers for consistent environments:

```bash
# Create .env file with required variables (see Configuration section)
cp .env.example .env
# Edit .env with your credentials

# Build and start all services
docker compose up --build

# Or run in detached mode
docker compose up -d --build

# View logs
docker compose logs -f

# View logs for specific service
docker compose logs -f lares-bot
docker compose logs -f mcp-server
docker compose logs -f letta

# Stop all services
docker compose down

# Rebuild after code changes
docker compose build
docker compose up
```

**Container Networking:**
- Services communicate using service names: `letta`, `mcp-server`, `lares-bot`
- Set in `.env`:
  - `LETTA_BASE_URL=http://letta:8283` (for containers)
  - `LARES_MCP_URL=http://mcp-server:8765` (for containers)
- Ports exposed:
  - Letta: `8283` (for external access if needed)
  - MCP Server: `8765` (for external access if needed)

**Services:**
- `letta`: Letta memory service
- `mcp-server`: MCP server with Discord integration
- `lares-bot`: Main Discord bot

#### Development Mode (Local)

For testing and development locally:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run Lares directly
python run.py
# or if installed: lares
```

On first run, Lares will create a new agent and print an `LARES_AGENT_ID` - add this to your `.env` to persist the agent across restarts.

#### Production Mode (systemd)

For production deployment with auto-start on boot:

```bash
# Copy the service file
sudo cp lares.service /etc/systemd/system/

# Edit the service file to match your setup
sudo systemctl edit lares.service
# Update User, WorkingDirectory, and paths as needed

# Enable and start the service
sudo systemctl enable lares.service
sudo systemctl start lares.service

# View logs
journalctl -u lares.service -f

# Common management commands:
sudo systemctl status lares.service  # Check status
sudo systemctl restart lares.service # Restart Lares
sudo systemctl stop lares.service    # Stop Lares
journalctl -u lares.service -n 50    # View last 50 log lines
```

The systemd service:
- Automatically starts Letta Docker container before Lares
- Restarts on failure
- Runs with proper virtual environment
- Logs to systemd journal
- Persists across reboots when enabled

## Self-Hosting Letta

You can run Letta locally with Docker:

```bash
docker run \
  -v ~/.letta/.persist/pgdata:/var/lib/postgresql/data \
  -p 8283:8283 \
  -e ANTHROPIC_API_KEY="your_key" \
  letta/letta:latest
```

Then set in your `.env`:
```
LETTA_BASE_URL=http://localhost:8283
```

**Note:** When using Docker Compose, Letta is automatically included and configured. Use `LETTA_BASE_URL=http://letta:8283` for container networking.

## Approval Workflows

Lares implements two types of approval workflows for sensitive operations:

### Command Approval (Synchronous)
When Lares tries to run a shell command not in the allowlist:
1. Sends approval request to Discord with ✅/❌ reactions
2. **Waits up to 5 minutes** for your response
3. If approved: adds command to allowlist and executes
4. If denied or timeout: returns error to Lares

### BlueSky Post Approval (Asynchronous)
When Lares wants to post to BlueSky:
1. Sends approval request to Discord with post preview
2. **Returns immediately** - Lares continues other work
3. You can approve/deny anytime (even hours later)
4. When approved: post is sent to BlueSky
5. When denied: post is discarded

This async pattern prevents Lares from being blocked while waiting for approval.

## Self-Restart Capability

Lares can restart itself when needed (e.g., after updates, configuration changes, or for maintenance). This requires passwordless sudo access for the restart command.

### Setup

Run the setup script during installation (requires sudo):

```bash
sudo bash scripts/setup-sudoers.sh
```

This configures passwordless sudo for **only** the specific command:
```bash
systemctl restart lares.service
```

### Security Note

The sudoers configuration is minimal and scoped:
- Only allows restarting the `lares.service` systemd unit
- No other sudo commands are affected
- Standard Linux pattern for service self-management

### Usage

Once configured, Lares can restart itself by calling the `restart_lares()` tool:

```python
# Lares can decide when to restart, such as:
# - After git pull to apply updates
# - When .env configuration changes
# - For periodic maintenance during perch time
# - Recovery from suspected issues
```

## Development

```bash
# Run tests
pytest

# Run linter
ruff check src/

# Run type checker
mypy src/
```

## Architecture

```
src/lares/
├── config.py          # Configuration management
├── memory.py          # Letta integration and memory blocks
├── discord_bot.py     # Discord interface and perch time
├── scheduler.py       # Job scheduling with APScheduler
├── tool_registry.py   # Tool execution and approval workflow
├── response_parser.py # Discord response parsing (reactions, messages)
├── time_utils.py      # Time context and timezone handling
├── bluesky_reader.py  # BlueSky API client
├── rss_reader.py      # RSS/Atom feed parser
├── obsidian.py        # Obsidian vault integration (optional)
├── mcp_server.py     # MCP server exposing tools via SSE
├── mcp_approval.py   # SQLite-based approval queue for MCP
├── mcp_bridge.py     # Bridges MCP approvals to Discord
├── tools/             # Tool implementations
│   ├── filesystem.py      # read_file, write_file
│   ├── shell.py           # run_command
│   ├── discord.py         # send_message, react
│   ├── scheduler.py       # schedule_job, remove_job, list_jobs
│   ├── rss.py             # read_rss_feed
│   ├── bluesky.py         # read_bluesky_user, search_bluesky, post_to_bluesky
│   ├── system_management.py  # restart_lares
│   └── tool_creation.py   # create_tool (dynamic tool creation)
└── main.py            # Entry point
```

### Memory Compaction Recovery

Lares gracefully handles Letta's automatic memory compaction when conversations exceed context limits:

1. **Detection**: System alerts about memory constraints are automatically detected
2. **Notification**: Shows "💭 *Reorganizing my thoughts...*" in Discord
3. **Automatic Retry**: The interrupted operation is retried after compaction
4. **Continuity**: Lares completes intended actions (especially important during perch time)

This ensures Lares never gets "stunned" by memory compaction and maintains continuous operation.

### Memory Blocks

Lares uses four memory blocks:

| Block | Purpose |
|-------|---------|
| `persona` | Lares's identity and personality |
| `human` | Information about you |
| `state` | Current working memory and tasks |
| `ideas` | Feature ideas and future plans |

### Skills (Procedural Memory)

Skills are markdown files that teach Lares how to perform specific tasks. Inspired by [Letta Code's skill learning](https://www.letta.com/blog/skill-learning), they provide:

- **Persistent procedural knowledge** that survives context resets
- **On-demand loading** - only loaded when needed (context-efficient)
- **Learn from experience** - new skills created after successful task completion

Example skills in `examples/skills/`:
- `git-workflow.md` - Version control patterns
- `perch-tick.md` - Autonomous time decision framework  
- `discord-interaction.md` - Communication patterns

Skills are indexed in Lares's persona (lightweight pointers) and loaded via `read_file` when performing related tasks.

### Available Tools

Lares has access to 20 tools (native + MCP), plus optional Obsidian integration:

#### Native Tools (10)

| Tool | Description |
|------|-------------|
| `run_command` | Execute shell commands with approval workflow (working_dir optional) |
| `read_file` | Read files from the filesystem |
| `write_file` | Create or modify files |
| `schedule_job` | Schedule reminders and recurring tasks (supports cron, intervals, datetime) |
| `remove_job` | Remove scheduled jobs |
| `list_jobs` | List all scheduled jobs |
| `read_rss_feed` | Read RSS/Atom feeds |
| `read_bluesky_user` | Read posts from a BlueSky user |
| `search_bluesky` | Search BlueSky posts |
| `post_to_bluesky` | Post to BlueSky (async approval workflow) |
| `discord_send_message` | Send messages to Discord (reply mode optional) |
| `discord_react` | React to messages with emoji |
| `restart_lares` | Restart the Lares service |
| `create_tool` | Create new tools from Python code |

#### Obsidian Integration (6, optional)

When `OBSIDIAN_VAULT_PATH` is configured, these additional tools become available:

| Tool | Description |
|------|-------------|
| `read_note` | Read a note from Obsidian vault |
| `write_note` | Create or modify notes in vault |
| `append_to_note` | Append content to existing notes |
| `search_notes` | Search vault for text content |
| `list_notes` | List notes in directory |
| `add_journal_entry` | Add timestamped journal entries |

## Roadmap

Future enhancements under consideration:

- Multi-modal awareness (images, voice)
- Local-first operation for privacy
- Multiple LLM backend support
- Telegram and web interfaces
- Richer memory with semantic search
- Plugin system for extensibility
- Proactive context gathering

## License

**PolyForm Noncommercial License 1.0.0**

This software is licensed under the PolyForm Noncommercial License 1.0.0, a modern license designed specifically for noncommercial open source.

### What this means:
- ✅ **Free for personal use** - Individuals can use, modify, and share for hobby/personal projects
- ✅ **Free for education** - Students, teachers, and educational institutions
- ✅ **Free for nonprofits** - Charities and registered nonprofit organizations
- ✅ **Free for research** - Public research organizations and experiments
- ✅ **Free for government** - Government institutions and public services
- ❌ **NOT free for commercial use** - No commercial or for-profit use
- ❌ **NOT free for companies** - Corporations cannot use, even internally
- ❌ **NOT free as a service** - Cannot host or offer as SaaS

### Why this license?
Lares is a labor of love meant to empower individuals. The PolyForm Noncommercial license provides crystal-clear terms that prevent any commercial exploitation while keeping the software freely available for personal, educational, and charitable use.

See [LICENSE](LICENSE) for full terms.

## MCP Server

Lares includes an MCP (Model Context Protocol) server that exposes tools in a framework-agnostic way. This enables portability - you can connect any MCP-compatible system (Letta, Claude Desktop, etc.) to use Lares tools.

### Running the MCP Server

```bash
# Start the MCP server (default: http://0.0.0.0:8765)
python -m lares.mcp_server

# Or as a systemd service (see lares-mcp.service)
```

### MCP Tools (10)

The MCP server provides these tools:

| Tool | Description |
|------|-------------|
| `run_shell_command` | Execute shell commands (with approval for non-allowlisted) |
| `read_file` | Read files from allowed directories |
| `write_file` | Write files to allowed directories |
| `list_directory` | List contents of a directory |
| `read_rss_feed` | Read RSS/Atom feeds |
| `read_bluesky_user` | Read posts from a BlueSky user |
| `search_bluesky` | Search BlueSky posts |
| `post_to_bluesky` | Post to BlueSky (requires approval) |
| `search_obsidian_notes` | Search notes in Obsidian vault |
| `read_obsidian_note` | Read a specific note from Obsidian |

### Approval Queue

The MCP server includes an HTTP-based approval queue for sensitive operations:

```
GET  /approvals/pending      - List pending approvals
GET  /approvals/{id}         - Get specific approval
POST /approvals/{id}/approve - Approve and execute
POST /approvals/{id}/deny    - Deny request
GET  /health                 - Health check
```

Lares bridges this queue to Discord, allowing you to approve/deny via reactions.

### Connecting Letta to MCP

Lares automatically connects to the MCP server and attaches tools to the Letta agent. Configuration in `.env`:

```
LARES_MCP_URL=http://localhost:8765/sse
```

export BLUESKY_SESSION_TOKEN=$(curl -s -X POST https://bsky.social/xrpc/com.atproto.server.createSession \
  -H "Content-Type: application/json" \
  -d '{"identifier":"jaxcoder.bsky.social","password":""}' | jq -r .accessJwt)

  curl -s -X POST https://bsky.social/xrpc/com.atproto.server.createSession \
  -H "Content-Type: application/json" \
  -d '{"identifier":"jaxcoder.bsky.social","password":"5eot-5yw6-bvty-wldw"}'