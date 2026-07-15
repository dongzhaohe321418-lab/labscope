#!/bin/sh
# Register the LabScope MCP server with Claude Code (run from anywhere).
REPO="$(cd "$(dirname "$0")/.." && pwd)"
exec claude mcp add labscope -- "$REPO/.venv/bin/python" "$REPO/agent/mcp_server.py"
