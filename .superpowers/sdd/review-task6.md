# Review package: Task 6 (no git — full file dump)

## Files
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
/Users/ilaakshmishra/Documents/hindsight/.claude/settings.local.json
/Users/ilaakshmishra/Documents/hindsight/.gitignore
/Users/ilaakshmishra/Documents/hindsight/.mcp.json
/Users/ilaakshmishra/Documents/hindsight/README.md
/Users/ilaakshmishra/Documents/hindsight/hooks/hooks.json
/Users/ilaakshmishra/Documents/hindsight/hooks/retrieve.py
/Users/ilaakshmishra/Documents/hindsight/hooks/tests/test_retrieve.py
/Users/ilaakshmishra/Documents/hindsight/server/index.py
/Users/ilaakshmishra/Documents/hindsight/server/main.py
/Users/ilaakshmishra/Documents/hindsight/server/requirements.txt
/Users/ilaakshmishra/Documents/hindsight/server/schema.py
/Users/ilaakshmishra/Documents/hindsight/server/scrub.py
/Users/ilaakshmishra/Documents/hindsight/server/store.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/conftest.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-04-01-postgres-pool-exhausted.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-05-14-docker-build-oom-killed.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-06-02-react-useeffect-infinite-loop.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-07-18-fastmcp-pydantic-floor.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_index.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_main.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_schema.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_scrub.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_store.py
/Users/ilaakshmishra/Documents/hindsight/skills/hindsight/SKILL.md
/Users/ilaakshmishra/Documents/hindsight/templates/LESSON_TEMPLATE.md
```

## hooks/hooks.json
```
{
  "description": "Nudge Claude to check the hindsight lesson database before proposing a fix, on every tool failure.",
  "hooks": {
    "PostToolUseFailure": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/retrieve.py"]
          }
        ]
      }
    ]
  }
}
```

## hooks/retrieve.py
```
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
payload-shape change or a truncated/garbled stream can't turn into an
unhandled exception that makes this hook silently stop nudging on every
tool failure in a session. Stdlib only (`json`, `sys`): no `mcp`,
`fastembed`, or any pinned dependency, so this runs directly via plain
`python3` in `hooks/hooks.json` -- no `uv run` startup cost on every
single tool failure. No MCP call happens in this process; the nudge only
tells Claude to call `search_lessons` on its next turn.
"""

from __future__ import annotations

import json
import sys

# Kept short (~350 chars) per the Task 6 brief -- this fires on every tool
# failure across the whole session, so cost compounds. If you edit this,
# re-run hooks/tests/test_retrieve.py, which asserts a hard length bound.
ADDITIONAL_CONTEXT = (
    "An error occurred. Before proposing a fix, call hindsight "
    "search_lessons with a short natural-language description of this "
    "error. If a returned lesson is genuinely relevant, use its "
    "failed-approaches list to avoid dead ends and treat its fix as a "
    "starting hypothesis — the codebase may have changed since it was "
    "written. Ignore low-relevance results."
)


def main() -> int:
    # Drain stdin so the parent process never blocks on a full pipe, even
    # though no field of the payload changes this hook's output. Malformed
    # or empty stdin must not prevent the nudge from firing.
    raw = sys.stdin.read()
    try:
        json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
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
```

## hooks/tests/test_retrieve.py
```
"""Standalone script test for `hooks/retrieve.py` (Task 6).

Doesn't need a live Claude Code session: invokes the hook script exactly
the way `hooks/hooks.json` does (`python3 hooks/retrieve.py`, JSON
payload on stdin, JSON read back from stdout), using a fabricated
`PostToolUseFailure` payload matching the real schema confirmed against
`https://code.claude.com/docs/en/hooks.md` ("PostToolUseFailure input"
section) during this task.

Runnable directly (`python3 hooks/tests/test_retrieve.py`) or via pytest
(`pytest hooks/tests/test_retrieve.py`) -- no non-stdlib imports either
way, matching the hook script itself.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

RETRIEVE_PY = Path(__file__).resolve().parent.parent / "retrieve.py"

# A fabricated but schema-accurate PostToolUseFailure payload -- every
# field name and the overall shape come straight from the doc's own
# example for this event, not invented.
FAKE_PAYLOAD = {
    "session_id": "abc123",
    "transcript_path": "/Users/example/.claude/projects/demo/00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
    "cwd": "/Users/example/project",
    "permission_mode": "default",
    "hook_event_name": "PostToolUseFailure",
    "tool_name": "Bash",
    "tool_input": {"command": "npm test", "description": "Run test suite"},
    "tool_use_id": "toolu_01ABC123",
    "error": "Command exited with non-zero status code 1",
    "is_interrupt": False,
    "duration_ms": 4187,
}

EXPECTED_ADDITIONAL_CONTEXT = (
    "An error occurred. Before proposing a fix, call hindsight "
    "search_lessons with a short natural-language description of this "
    "error. If a returned lesson is genuinely relevant, use its "
    "failed-approaches list to avoid dead ends and treat its fix as a "
    "starting hypothesis — the codebase may have changed since it was "
    "written. Ignore low-relevance results."
)


def _run_hook(stdin_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RETRIEVE_PY)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_emits_exact_additional_context_on_real_payload_shape() -> None:
    result = _run_hook(json.dumps(FAKE_PAYLOAD))

    assert result.returncode == 0, f"stderr: {result.stderr!r}"

    parsed = json.loads(result.stdout)  # must be valid JSON
    assert parsed == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUseFailure",
            "additionalContext": EXPECTED_ADDITIONAL_CONTEXT,
        }
    }


def test_additional_context_is_short() -> None:
    # This fires on every tool failure in a session, so a future edit
    # that quietly bloats the string is a real cost. Bound it well above
    # the brief's "a few hundred characters" target (350 today) so normal
    # wording tweaks don't trip this, but a runaway rewrite does.
    length = len(EXPECTED_ADDITIONAL_CONTEXT)
    assert length < 500, f"additionalContext is {length} chars, expected < 500"


def test_unconditional_even_on_malformed_stdin() -> None:
    # The nudge doesn't depend on any payload field, so garbled/empty
    # stdin must still produce the same nudge with exit 0, not a crash --
    # a payload-shape change upstream shouldn't be able to silence every
    # future failure's nudge for the rest of the session.
    for garbage in ("", "not json at all", "{", "null"):
        result = _run_hook(garbage)
        assert result.returncode == 0, f"input={garbage!r} stderr={result.stderr!r}"
        parsed = json.loads(result.stdout)
        assert (
            parsed["hookSpecificOutput"]["additionalContext"]
            == EXPECTED_ADDITIONAL_CONTEXT
        )


def test_no_non_stdlib_imports() -> None:
    # Confirms the environment/tooling constraint: the hook needs only
    # Python's standard library, so hooks.json can invoke it via plain
    # `python3` instead of paying `uv run`'s startup cost on every tool
    # failure. Stdlib module names below are Python 3.12's; this repo
    # targets the same interpreter the MCP server uses (see
    # server/tests/conftest.py neighbors).
    stdlib_modules = sys.stdlib_module_names  # type: ignore[attr-defined]

    tree = ast.parse(RETRIEVE_PY.read_text(encoding="utf-8"), filename=str(RETRIEVE_PY))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    non_stdlib = {name for name in imported if name not in stdlib_modules}
    assert not non_stdlib, f"retrieve.py imports non-stdlib modules: {non_stdlib}"


if __name__ == "__main__":
    # Plain-script runner so this passes the brief's "standalone script
    # test" bar without requiring pytest to be installed.
    tests = [
        test_emits_exact_additional_context_on_real_payload_shape,
        test_additional_context_is_short,
        test_unconditional_even_on_malformed_stdin,
        test_no_non_stdlib_imports,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        else:
            print(f"PASS {test.__name__}")
    if failures:
        print(f"{failures}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"All {len(tests)} tests passed")
```
