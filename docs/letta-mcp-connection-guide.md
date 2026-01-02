# Letta MCP Connection Issue - Analysis and Solution

## Problem Summary
Letta cannot connect to the Lares MCP server using either:
- **stdio** - Fails with "No such file or directory" (can't spawn subprocess across Docker containers)
- **streamable HTTP** - Fails with "RuntimeError: No response returned" (protocol mismatch)

## Root Cause
The issue is likely a **protocol incompatibility**:

1. **FastMCP** (what we're using) implements the MCP protocol with SSE transport at `/sse`
2. **Letta** expects "streamable HTTP" but may be looking for a different endpoint or response format

## Investigation Findings

### MCP Server Endpoints (Working)
- `GET /health` - Returns `{"status":"ok","server":"lares-mcp","pending_approvals":0}` ✅
- `GET /sse` - Returns SSE stream with session endpoint ✅
- `GET /events` - Custom Discord/approval events endpoint ✅
- Custom approval/Discord endpoints - All working ✅

### The SSE Flow
When you connect to `/sse`, FastMCP returns:
```
event: endpoint
data: /messages/?session_id=<uuid>
```

Then you POST JSON-RPC messages to that `/messages/?session_id=<uuid>` endpoint.

## Possible Solutions

### Option 1: Check Letta's MCP Documentation
We need to find out what transport protocol Letta's "streamable HTTP" actually expects. It might be:
- A different URL path
- Different authentication
- A different streaming protocol (WebSocket instead of SSE?)

### Option 2: Use Letta's MCP Client Directly
Instead of connecting through Letta's dashboard, integrate the MCP tools at the application level (in lares-bot).

### Option 3: Create a Protocol Adapter
Build a thin adapter service that translates between Letta's expected format and FastMCP's format.

### Option 4: Install Lares in Letta Container (stdio)
Mount the lares source code into the Letta container so it can spawn the MCP server as a subprocess.

## Recommended Next Steps

1. **Check what URL you used** in Letta's config:
   - Did you use `http://mcp-server:8765` or `http://mcp-server:8765/sse`?

2. **Check Letta's logs** to see what request it's actually making

3. **Review Letta's MCP documentation** for the correct streamable HTTP format

4. **Test with a simple MCP client** to verify the server works correctly

## Testing Commands

```bash
# Check server health
curl http://localhost:8765/health

# Connect to SSE (will stream)
curl http://localhost:8765/sse

# Check Docker logs
docker-compose logs letta
docker-compose logs mcp-server
```
