## Task 6: Automatic retrieval hook (Phase 3)

Files:
- `hooks/hooks.json` — register a `PostToolUseFailure` hook (matcher: all
  tools, i.e. no matcher restriction, since an error can come from any
  tool — Bash, Edit, a build command, etc). Hook script path uses
  `${CLAUDE_PLUGIN_ROOT}` literal.
- `hooks/retrieve.py` (or `.sh`, implementer's choice — Python
  recommended for consistency with the server) — reads the hook's JSON
  stdin payload, and unconditionally (every tool failure) emits on
  stdout:
  ```json
  {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": "An error occurred. Before proposing a fix, call hindsight search_lessons with a short natural-language description of this error. If a returned lesson is genuinely relevant, use its failed-approaches list to avoid dead ends and treat its fix as a starting hypothesis — the codebase may have changed since it was written. Ignore low-relevance results."}}
  ```
  exit code 0. Keep the string under a few hundred characters — this
  fires on every failure, so it must stay cheap. Do NOT try to pre-filter
  "is this error-like" here; `PostToolUseFailure` already only fires on
  genuine tool failures.
- No MCP call happens inside the hook itself — the hook only nudges;
  Claude (which sees the injected context on its next turn) decides
  whether and how to call `search_lessons`.

Test: a standalone script test (not needing a live Claude session) that
pipes a fabricated `PostToolUseFailure` JSON payload (matching the real
schema — check the doc's example payload shape) into the hook script and
asserts the exact `additionalContext` JSON is emitted on stdout with exit
0.

Sequence: independent of Tasks 1-5's Python server internals (only needs
the `search_lessons` tool name to exist, which Task 1 already stubs) —
may be dispatched any time after Task 1.

---

