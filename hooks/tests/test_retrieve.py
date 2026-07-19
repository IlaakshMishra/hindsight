"""Standalone script test for `hooks/retrieve.py` (Task 6).

Doesn't need a live Claude Code session: invokes the hook script the same
way `hooks/hooks.json` does functionally (JSON payload on stdin, JSON
read back from stdout) -- via `sys.executable` here rather than
hooks.json's actual `uv run --no-project hooks/retrieve.py` launcher,
since the script itself is what's under test, not the launch mechanism
(see `test_hooks_json.py` for a test that pins hooks.json's real command
shape). Uses a fabricated
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
    "A tool call just failed. hindsight search_lessons can surface past "
    "team lessons on similar errors, including approaches that didn't "
    "work. A relevant result is worth checking before proposing a fix; "
    "treat its fix as a hypothesis, not gospel, since the codebase may "
    "have changed. Low-relevance results aren't worth acting on."
)


def _run_hook(stdin_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RETRIEVE_PY)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_hook_bytes(stdin_bytes: bytes) -> subprocess.CompletedProcess[bytes]:
    # Byte-mode variant of _run_hook: some inputs (genuinely non-UTF-8
    # bytes) can't be represented as a Python str via the text=True path
    # at all, so this feeds raw bytes straight to the subprocess's stdin.
    return subprocess.run(
        [sys.executable, str(RETRIEVE_PY)],
        input=stdin_bytes,
        capture_output=True,
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
    # the brief's "a few hundred characters" target (323 today) so normal
    # wording tweaks don't trip this, but a runaway rewrite does. Measures
    # the real subprocess output (not just the duplicated EXPECTED_*
    # literal above) so this test would actually catch a length regression
    # in the script itself, not just in this file's copy of the string.
    result = _run_hook(json.dumps(FAKE_PAYLOAD))
    parsed = json.loads(result.stdout)
    length = len(parsed["hookSpecificOutput"]["additionalContext"])
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


def test_unconditional_even_on_non_utf8_stdin() -> None:
    # Regression test: sys.stdin.read() decodes with the strict error
    # handler and raises UnicodeDecodeError on non-UTF-8 bytes, crashing
    # the script before it prints anything (reproduced live: piping
    # b"\xff\xfe\x00\xff\xd8\xff\xe0" into the old retrieve.py exited 1
    # with no stdout -- silently killing the nudge for that failure).
    # These bytes are not malformed-but-valid-UTF-8 text like "not json at
    # all" (already covered above) -- they are genuinely undecodable as
    # UTF-8, exercising the actual crash path via a real subprocess, not a
    # mock. The fix must emit the nudge regardless.
    non_utf8_payloads = [
        b"\xff\xfe\x00\xff\xd8\xff\xe0",  # reviewer's exact repro bytes
        b"\x80\x81\x82\xfe\xff",  # standalone continuation/reserved bytes
    ]
    for garbage in non_utf8_payloads:
        result = _run_hook_bytes(garbage)
        assert result.returncode == 0, (
            f"input={garbage!r} stderr={result.stderr!r} "
            f"stdout={result.stdout!r}"
        )
        parsed = json.loads(result.stdout.decode("utf-8"))
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
        test_unconditional_even_on_non_utf8_stdin,
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
