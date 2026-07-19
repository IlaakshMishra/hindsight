# Review package: Task 1 (no git — full file dump, not a diff)

## Files
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
/Users/ilaakshmishra/Documents/hindsight/.claude/settings.local.json
/Users/ilaakshmishra/Documents/hindsight/.gitignore
/Users/ilaakshmishra/Documents/hindsight/.mcp.json
/Users/ilaakshmishra/Documents/hindsight/README.md
/Users/ilaakshmishra/Documents/hindsight/server/main.py
/Users/ilaakshmishra/Documents/hindsight/server/requirements.txt
```

## .claude-plugin/plugin.json
```
{
  "name": "hindsight",
  "version": "0.1.0",
  "description": "Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice."
}
```

## .mcp.json
```
{
  "mcpServers": {
    "hindsight": {
      "command": "${CLAUDE_PLUGIN_ROOT}/server/.venv/bin/python3",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/main.py"]
    }
  }
}
```

## server/main.py
```
#!/usr/bin/env python3
"""Hindsight MCP server.

Exposes the `hindsight` tool surface (`search_lessons`, `save_lesson`,
`list_lessons`) over stdio using the official MCP Python SDK's FastMCP
helper.

Task 1 status: skeleton only. Each tool below validates its input shape
(via FastMCP's automatic schema generation from type hints) and returns a
hardcoded placeholder response. No lessons directory is read or written,
no embedding index is built or queried yet. Real storage/embedding logic
lands in later tasks — see docs/superpowers/plans/hindsight-plan.md
(Tasks 2-4).
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hindsight")


@mcp.tool()
def search_lessons(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Search saved debugging lessons for ones relevant to `query`.

    STUB (Task 1): always returns an empty placeholder list, regardless
    of input. Real similarity search against the fastembed index lands
    in Tasks 3-4.
    """
    return []


@mcp.tool()
def save_lesson(
    title: str,
    domain: list[str],
    error_signature: str,
    symptom: str,
    failed_approaches: list[str],
    root_cause: str,
    fix: str,
    confidence: Literal["confirmed", "probable"] = "probable",
) -> dict[str, Any]:
    """Save a debugging lesson learned during this session.

    STUB (Task 1): validates the input shape but performs no scrubbing,
    rendering, or disk writes. Real persistence (schema render + secret
    scrub + write to .debug-memory/lessons/ + index update) lands in
    Tasks 2 and 4.
    """
    return {"id": "stub-lesson-id", "path": "", "wrote": False}


@mcp.tool()
def list_lessons() -> list[dict[str, Any]]:
    """List all saved debugging lessons.

    STUB (Task 1): always returns an empty placeholder list. Real
    listing from .debug-memory/lessons/ lands in Task 4.
    """
    return []


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## server/requirements.txt
```
# Pinned to the versions verified against this plugin during development.
#
# .mcp.json launches the server via server/.venv/bin/python3 (a
# project-local virtualenv), not the system python3 — this keeps the
# plugin self-contained and avoids clashing with whatever else is on a
# teammate's machine. Set it up with:
#   python3 -m venv server/.venv
#   server/.venv/bin/pip install -r server/requirements.txt

# Official MCP Python SDK - server transport, tool registration (FastMCP).
mcp==1.27.0

# Local embeddings for the similarity index (BAAI/bge-small-en-v1.5).
# Not imported yet in Task 1's stub server; wired up starting Task 3.
fastembed==0.8.0
```

## README.md
```
# hindsight

Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice.

**Status: skeleton only.** This is Task 1 of the build plan
(`docs/superpowers/plans/hindsight-plan.md`) — the plugin manifest and MCP
server exist and expose the `search_lessons`, `save_lesson`, and
`list_lessons` tools, but every tool currently returns a hardcoded
placeholder response. No lessons are actually stored, embedded, or
searched yet. This README will be filled out in full (install
instructions, architecture diagram, usage) in Task 8.
```

## .gitignore
```
server/.venv/
__pycache__/
*.pyc
```
