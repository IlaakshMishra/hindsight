# Review package: Task 1 fix (uv run migration) — no git, file dump


## .mcp.json
```
{
  "mcpServers": {
    "hindsight": {
      "command": "uv",
      "args": [
        "run",
        "--no-project",
        "--with-requirements",
        "${CLAUDE_PLUGIN_ROOT}/server/requirements.txt",
        "${CLAUDE_PLUGIN_ROOT}/server/main.py"
      ]
    }
  }
}
```

## server/requirements.txt
```
# Pinned to the versions verified against this plugin during development.
#
# .mcp.json launches the server via `uv run --no-project --with-requirements
# server/requirements.txt server/main.py`. uv reads this file and
# auto-provisions an isolated, ephemeral environment (cached in uv's own
# cache dir, not a project-local directory) on first launch — no manual
# venv-bootstrap step required on a fresh checkout. Requires `uv`
# (https://docs.astral.sh/uv/) to be installed on the developer's machine;
# nothing else to set up.
#
# To reproduce the same environment manually (e.g. for local testing
# outside Claude Code):
#   uv run --no-project --with-requirements server/requirements.txt server/main.py

# Official MCP Python SDK - server transport, tool registration (FastMCP).
mcp==1.27.0

# Local embeddings for the similarity index (BAAI/bge-small-en-v1.5).
# Not imported yet in Task 1's stub server; wired up starting Task 3.
fastembed==0.8.0
```

## .gitignore
```
__pycache__/
*.pyc
```

## README.md
```
# hindsight

Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice.

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be installed on your machine — the MCP server is launched via `uv run`, which auto-provisions its own isolated Python environment on first use (no manual `pip install`/venv setup required).

**Status: skeleton only.** This is Task 1 of the build plan
(`docs/superpowers/plans/hindsight-plan.md`) — the plugin manifest and MCP
server exist and expose the `search_lessons`, `save_lesson`, and
`list_lessons` tools, but every tool currently returns a hardcoded
placeholder response. No lessons are actually stored, embedded, or
searched yet. This README will be filled out in full (install
instructions, architecture diagram, usage) in Task 8.
```
