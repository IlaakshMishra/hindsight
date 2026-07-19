## Task 1: Plugin skeleton + empty MCP server

Create the plugin manifest and an MCP server that starts, registers, and
exposes empty tool stubs — verifiable end to end before any real logic
exists.

Files:
- `.claude-plugin/plugin.json` — manifest: name `hindsight`, version
  `0.1.0`, description (use the README one-liner from the spec), and
  whatever fields Claude Code plugin manifests require (check an existing
  installed plugin's `plugin.json` under
  `/Users/ilaakshmishra/.claude/plugins/cache/` for the exact required
  shape before inventing fields).
- `.mcp.json` — registers the server. Command must launch
  `${CLAUDE_PLUGIN_ROOT}/server/main.py` (literal string, not resolved).
  Use a `python3` (or `uv run`) command array. Working directory should
  not be assumed; use absolute paths built from the plugin-root variable.
- `server/main.py` — MCP server (use the official `mcp` Python SDK,
  `pip install mcp`) exposing three tool stubs: `search_lessons`,
  `save_lesson`, `list_lessons`. Each stub validates its input schema and
  returns a hardcoded placeholder response (no real storage/embedding
  logic yet — that's Task 2). Server must start over stdio per the MCP
  Python SDK's standard pattern.
- `server/requirements.txt` (or `pyproject.toml`, implementer's choice,
  document which) pinning `mcp`, `fastembed`.
- `README.md` — stub with the one-line summary from the spec (section 13)
  and a "status: skeleton only" note; will be filled out in Task 8.

Verification: document in the report exactly how you confirmed the server
starts and lists its 3 tools (e.g. `claude --plugin-dir . ` then
inspecting available tools, or the MCP SDK's own stdio test harness /
`mcp dev` if installed). If `claude` CLI plugin loading can't be exercised
headlessly, a direct stdio round-trip test (send `tools/list`, assert 3
tools returned) is an acceptable substitute — state which you used.

---

