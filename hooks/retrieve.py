#!/usr/bin/env python3
"""hindsight `PostToolUseFailure` hook: the automatic retrieval nudge.

Registered in `hooks/hooks.json` against every tool (no matcher — any
tool can fail: Bash, Edit, a build command run through Bash, an MCP tool,
etc). Claude Code spawns this script once per genuine tool failure with
the failure's JSON payload on stdin and reads JSON back from stdout.

Confirmed payload shape (fetched `https://code.claude.com/docs/en/
hooks.md` directly during Task 6, "PostToolUseFailure input" section --
not guessed):

    {
      "session_id": "abc123",
      "transcript_path": "/Users/.../00893aaf-....jsonl",
      "cwd": "/Users/...",
      "permission_mode": "default",
      "hook_event_name": "PostToolUseFailure",
      "tool_name": "Bash",
      "tool_input": {"command": "npm test", "description": "Run test suite"},
      "tool_use_id": "toolu_01ABC123...",
      "error": "Command exited with non-zero status code 1",
      "is_interrupt": false,
      "duration_ms": 4187
    }

This hook does not branch on any of those fields. Per the Task 6 brief,
the nudge is unconditional -- `PostToolUseFailure` itself already only
fires on genuine tool failures (validation/permission rejections fire
neither `PreToolUse` nor this event, so there is no "is this error-like"
filtering left to do here). Every invocation emits the same fixed
`additionalContext` string on stdout and exits 0:

    {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
     "additionalContext": "<ADDITIONAL_CONTEXT below>"}}

Stdin is still read and (best-effort) parsed rather than ignored
outright -- not because any field feeds the output, but so a future
payload-shape change, a truncated/garbled stream, or even non-UTF-8 bytes
on stdin can't turn into an unhandled exception that makes this hook
silently stop nudging on every tool failure in a session. Stdlib only
(`json`, `sys`): no `mcp`,
`fastembed`, or any pinned dependency, so this runs directly via plain
`python3` in `hooks/hooks.json` -- no `uv run` startup cost on every
single tool failure. No MCP call happens in this process; the nudge only
tells Claude to call `search_lessons` on its next turn.
"""

from __future__ import annotations

import json
import sys

# Kept short (~325 chars) per the Task 6 brief -- this fires on every tool
# failure across the whole session, so cost compounds. If you edit this,
# re-run hooks/tests/test_retrieve.py, which asserts a hard length bound.
#
# Phrased as factual/descriptive statements rather than imperative
# instructions ("Before proposing a fix, call...") per Claude Code's own
# hooks doc guidance on `additionalContext` -- imperative phrasing risks
# tripping Claude's prompt-injection defenses, which would make Claude
# surface this raw text to the user instead of acting on it, silently
# defeating the hook. Rephrased after human review; see task-6-report.md,
# "Fix: factual phrasing + encoding resilience".
ADDITIONAL_CONTEXT = (
    "A tool call just failed. hindsight search_lessons can surface past "
    "team lessons on similar errors, including approaches that didn't "
    "work. A relevant result is worth checking before proposing a fix; "
    "treat its fix as a hypothesis, not gospel, since the codebase may "
    "have changed. Low-relevance results aren't worth acting on."
)


def main() -> int:
    # Drain stdin so the parent process never blocks on a full pipe, even
    # though no field of the payload changes this hook's output. Malformed,
    # empty, or non-UTF-8 stdin must not prevent the nudge from firing.
    #
    # Read raw bytes (sys.stdin.buffer), not sys.stdin.read() -- the latter
    # decodes with the strict error handler under the hood and raises
    # UnicodeDecodeError on non-UTF-8 bytes (e.g. a tool failure whose
    # error output embeds binary data), which would crash this script
    # before it ever prints the nudge. errors="replace" guarantees the
    # decode itself can't raise. The outer try/except is a second layer of
    # defense: whatever garbage arrives on stdin, nothing in this block may
    # ever stop the nudge below from being emitted.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        json.loads(raw) if raw.strip() else None
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUseFailure",
            "additionalContext": ADDITIONAL_CONTEXT,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
