"""Standalone script tests for `hooks/mark_error.py` + `hooks/capture.py`
(Task 7's marker-and-capture pair).

Same approach as `hooks/tests/test_retrieve.py` (Task 6): no live Claude
Code session needed. Each hook script is invoked exactly the way
`hooks/hooks.json` invokes it (`python3 hooks/<script>.py`, a JSON
payload on stdin, JSON read back from stdout), using fabricated but
schema-accurate `PostToolUseFailure`/`Stop` payloads (`session_id` is a
"Common input field" present on every hook event per
`https://code.claude.com/docs/en/hooks.md`, confirmed directly during
Task 7 -- see `hooks/capture.py`'s own module docstring for the fuller
citation).

`${CLAUDE_PLUGIN_DATA}` is pointed at a fresh temp directory per test
(never inherited from whatever real environment happens to run this
suite) so every test is isolated and repeatable, mirroring how
`server/tests/*` isolate `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` via
`monkeypatch.setenv` -- the equivalent here is passing an explicit `env`
dict to each subprocess rather than mutating this process's own
environment, since these are genuinely separate `python3` subprocesses
(matching how `hooks.json` runs them), not in-process calls.

`CLAUDE_PROJECT_DIR` is likewise pinned to a fixed, fake value
(`FAKE_PROJECT_DIR` below) for every test in this file, since the final
whole-project review's Finding C1 fix made both hook scripts partition
`${CLAUDE_PLUGIN_DATA}` by a project slug derived from
`CLAUDE_PROJECT_DIR` (see `hooks/mark_error.py`'s own module docstring).
A fixed literal (rather than leaving it unset and relying on whatever
directory the test-runner subprocess happens to inherit as `cwd`) keeps
every marker path this file's tests expect fully deterministic and
independent of how/where this suite is invoked -- the project-slug
computation is a pure string transform with no filesystem I/O, so this
fake path never needs to actually exist on disk.

Runnable directly (`python3 hooks/tests/test_mark_and_capture.py`) or
via pytest -- no non-stdlib imports either way, matching both hook
scripts under test.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from subprocess import CompletedProcess, run

HOOKS_DIR = Path(__file__).resolve().parent.parent
MARK_ERROR_PY = HOOKS_DIR / "mark_error.py"
CAPTURE_PY = HOOKS_DIR / "capture.py"

# See module docstring's "CLAUDE_PROJECT_DIR is likewise pinned..." note.
FAKE_PROJECT_DIR = "/fake/project/hindsight-hook-tests"

# Template mirrors hooks/capture.py's ADDITIONAL_CONTEXT_TEMPLATE
# byte-for-byte (final whole-project review, Finding I1 -- see that
# module's own docstring for the session_id-interpolation reasoning). The
# non-{session_id} portions are taken verbatim from the Task 7 brief.
# Independently transcribed here (not imported -- these are genuinely
# separate subprocesses, matching how this whole file already treats
# every other piece of hook logic) so a future accidental edit to either
# copy is caught.
EXPECTED_ADDITIONAL_CONTEXT_TEMPLATE = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from this session's session_id, `{session_id}`, "
    "and a concise summary — error signature, symptom, failed approaches, "
    "root cause, fix — with secrets/tokens/customer data excluded. Not "
    "worth dispatching if the error wasn't actually resolved this "
    "session."
)


def _expected_additional_context(session_id: str) -> str:
    return EXPECTED_ADDITIONAL_CONTEXT_TEMPLATE.format(session_id=session_id)


def _post_tool_use_failure_payload(session_id: str) -> dict:
    # Schema-accurate PostToolUseFailure payload, same shape
    # hooks/tests/test_retrieve.py uses (see that file for the doc
    # citation), just with a configurable session_id.
    return {
        "session_id": session_id,
        "transcript_path": "/Users/example/.claude/projects/demo/00893aaf.jsonl",
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


def _stop_payload(session_id: str) -> dict:
    # Schema-accurate Stop payload per the "Common input fields" section
    # of https://code.claude.com/docs/en/hooks.md (session_id, cwd,
    # permission_mode, hook_event_name are common to every event) plus
    # Stop's own documented last_assistant_message field.
    return {
        "session_id": session_id,
        "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
        "transcript_path": "/Users/example/.claude/projects/demo/00893aaf.jsonl",
        "cwd": "/Users/example/project",
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "last_assistant_message": "Fixed it -- the pool size was too small.",
    }


def _env_with_plugin_data(
    plugin_data_dir: Path, project_dir: str = FAKE_PROJECT_DIR
) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_DATA"] = str(plugin_data_dir)
    # Pinned to a fixed, fake value rather than a real CLAUDE_PROJECT_DIR
    # from the outer environment, or left unset -- see module docstring's
    # "CLAUDE_PROJECT_DIR is likewise pinned..." note for why.
    env["CLAUDE_PROJECT_DIR"] = project_dir
    return env


def _run(script: Path, stdin_text: str, env: dict) -> CompletedProcess:
    return run(
        [sys.executable, str(script)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


def _run_bytes(script: Path, stdin_bytes: bytes, env: dict) -> CompletedProcess:
    return run(
        [sys.executable, str(script)],
        input=stdin_bytes,
        capture_output=True,
        timeout=10,
        env=env,
    )


def _project_slug(project_dir: str) -> str:
    # Mirrors server/main.py's / hooks/mark_error.py's /
    # hooks/capture.py's _project_slug() exactly (final whole-project
    # review, Finding C1) -- this test helper is a fourth, independent
    # transcription of the same rule, so a mismatch between the three
    # real implementations would still show up as a test failure rather
    # than all copies drifting together.
    digest = hashlib.sha256(project_dir.encode("utf-8")).hexdigest()[:12]
    basename = Path(project_dir).name or "root"
    safe_basename = re.sub(r"[^A-Za-z0-9_-]", "_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _marker_path(
    plugin_data_dir: Path, session_id: str, project_dir: str = FAKE_PROJECT_DIR
) -> Path:
    # Mirrors both hook scripts' sanitization AND per-project
    # partitioning exactly (see their docstrings) -- this test helper is
    # an independent transcription of the same rules, so a mismatch
    # between the two real implementations would still show up as a test
    # failure rather than all copies drifting together.
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    slug = _project_slug(project_dir)
    return plugin_data_dir / slug / f"session-{safe_id}.marker"


def _touch_marker(
    plugin_data_dir: Path, session_id: str, project_dir: str = FAKE_PROJECT_DIR
) -> Path:
    """Create an empty marker file at the expected path -- simulating a
    marker `hooks/mark_error.py` already wrote in an earlier step of a
    test -- creating the (now per-project-partitioned) parent directory
    first, since a bare `_marker_path(...).touch()` would otherwise raise
    `FileNotFoundError` on the not-yet-existing `<project slug>/`
    subdirectory (in real usage, `hooks/mark_error.py`'s own
    `_plugin_data_dir()` always creates that directory before any marker
    is ever written into it).
    """
    path = _marker_path(plugin_data_dir, session_id, project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


# --- mark_error.py -----------------------------------------------------


def test_mark_error_creates_marker_file_at_expected_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp) / "plugin-data"
        env = _env_with_plugin_data(plugin_data_dir)
        payload = _post_tool_use_failure_payload("session-abc-123")

        result = _run(MARK_ERROR_PY, json.dumps(payload), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        expected = _marker_path(plugin_data_dir, "session-abc-123")
        assert expected.exists(), f"expected marker at {expected}"
        assert expected.is_file()


def test_mark_error_creates_plugin_data_dir_if_missing() -> None:
    # Brief: "This must not fail or block if the directory doesn't exist
    # yet -- create it." Use a plugin_data_dir path that doesn't exist
    # yet (not even its parent), unlike other tests where tempfile
    # already created the parent tmp dir.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp) / "does" / "not" / "exist" / "yet"
        assert not plugin_data_dir.exists()
        env = _env_with_plugin_data(plugin_data_dir)
        payload = _post_tool_use_failure_payload("s1")

        result = _run(MARK_ERROR_PY, json.dumps(payload), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert plugin_data_dir.is_dir()
        assert _marker_path(plugin_data_dir, "s1").exists()


def test_mark_error_emits_no_stdout() -> None:
    # mark_error.py must stay silent so it never adds a second
    # (possibly conflicting) additionalContext alongside retrieve.py's
    # Task-6-approved nudge for the same PostToolUseFailure event.
    with tempfile.TemporaryDirectory() as tmp:
        env = _env_with_plugin_data(Path(tmp))
        payload = _post_tool_use_failure_payload("s1")

        result = _run(MARK_ERROR_PY, json.dumps(payload), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert result.stdout == "", f"expected no stdout, got {result.stdout!r}"


def test_mark_error_no_op_on_missing_session_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        payload = _post_tool_use_failure_payload("s1")
        del payload["session_id"]

        result = _run(MARK_ERROR_PY, json.dumps(payload), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert list(plugin_data_dir.glob("*.marker")) == []


def test_mark_error_unconditional_even_on_malformed_stdin() -> None:
    # Must never crash/exit nonzero on garbled stdin -- there's just
    # nothing to mark without a usable session_id.
    with tempfile.TemporaryDirectory() as tmp:
        env = _env_with_plugin_data(Path(tmp))
        for garbage in ("", "not json at all", "{", "null"):
            result = _run(MARK_ERROR_PY, garbage, env)
            assert result.returncode == 0, f"input={garbage!r} stderr={result.stderr!r}"
            assert result.stdout == ""


def test_mark_error_unconditional_even_on_non_utf8_stdin() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = _env_with_plugin_data(Path(tmp))
        result = _run_bytes(MARK_ERROR_PY, b"\xff\xfe\x00\xff\xd8\xff\xe0", env)
        assert result.returncode == 0, (
            f"stderr: {result.stderr!r} stdout: {result.stdout!r}"
        )
        assert result.stdout == b""


# --- capture.py ----------------------------------------------------------


def test_capture_emits_nudge_when_marker_exists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        session_id = "session-with-a-marker"
        _touch_marker(plugin_data_dir, session_id)

        result = _run(CAPTURE_PY, json.dumps(_stop_payload(session_id)), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        parsed = json.loads(result.stdout)
        assert parsed == {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": _expected_additional_context(session_id),
            }
        }


def test_capture_no_op_when_different_session_has_no_marker() -> None:
    # The explicit "no-op" case: a marker exists for one session, but
    # THIS Stop event is for a different session_id that never hit a
    # failure -- must produce empty stdout and exit 0, not the nudge.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        _touch_marker(plugin_data_dir, "some-other-session")

        result = _run(CAPTURE_PY, json.dumps(_stop_payload("clean-session")), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert result.stdout == "", f"expected no stdout, got {result.stdout!r}"


def test_capture_no_op_when_no_marker_at_all() -> None:
    # A session with zero tool failures: no marker was ever written for
    # any session_id. Must write nothing -- the "no-op tests" case from
    # the plan's testing section.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        assert list(plugin_data_dir.glob("*.marker")) == []

        result = _run(CAPTURE_PY, json.dumps(_stop_payload("never-failed")), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert result.stdout == ""


def test_capture_does_not_delete_the_marker() -> None:
    # Deletion is the lesson-distiller agent's job, not this hook's --
    # an unresolved session's later Stop must still be able to trigger
    # capture once the error IS resolved.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        session_id = "still-unresolved"
        marker = _touch_marker(plugin_data_dir, session_id)

        result = _run(CAPTURE_PY, json.dumps(_stop_payload(session_id)), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert marker.exists(), "capture.py must not delete the marker file"


def test_capture_no_op_on_missing_session_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        payload = _stop_payload("irrelevant")
        del payload["session_id"]

        result = _run(CAPTURE_PY, json.dumps(payload), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        assert result.stdout == ""


def test_capture_no_op_on_malformed_stdin() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = _env_with_plugin_data(Path(tmp))
        for garbage in ("", "not json at all", "{", "null"):
            result = _run(CAPTURE_PY, garbage, env)
            assert result.returncode == 0, f"input={garbage!r} stderr={result.stderr!r}"
            assert result.stdout == ""


def test_capture_no_op_on_non_utf8_stdin() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = _env_with_plugin_data(Path(tmp))
        result = _run_bytes(CAPTURE_PY, b"\x80\x81\x82\xfe\xff", env)
        assert result.returncode == 0, (
            f"stderr: {result.stderr!r} stdout: {result.stdout!r}"
        )
        assert result.stdout == b""


# --- end-to-end: mark_error.py then capture.py ----------------------------


def test_end_to_end_mark_then_capture_same_session() -> None:
    # The real sequence: a tool fails (mark_error.py runs), the session
    # continues and later stops (capture.py runs) -- same session_id
    # both times, wired together exactly like hooks.json would invoke
    # them, not just each script tested in isolation.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        session_id = "e2e-session"

        mark_result = _run(
            MARK_ERROR_PY,
            json.dumps(_post_tool_use_failure_payload(session_id)),
            env,
        )
        assert mark_result.returncode == 0

        capture_result = _run(
            CAPTURE_PY, json.dumps(_stop_payload(session_id)), env
        )
        assert capture_result.returncode == 0
        parsed = json.loads(capture_result.stdout)
        assert (
            parsed["hookSpecificOutput"]["additionalContext"]
            == _expected_additional_context(session_id)
        )


def test_end_to_end_clean_session_writes_nothing() -> None:
    # A session with no tool failures: mark_error.py never runs (no
    # PostToolUseFailure event fired), so capture.py's Stop must be a
    # pure no-op. This is the plan's "no-op test" stated at the level of
    # a whole session rather than a single hook invocation.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)

        result = _run(CAPTURE_PY, json.dumps(_stop_payload("clean-session")), env)

        assert result.returncode == 0
        assert result.stdout == ""
        assert list(plugin_data_dir.glob("*.marker")) == []


def test_sanitization_is_consistent_between_write_and_read() -> None:
    # A session_id containing characters outside [A-Za-z0-9_-] (this
    # test uses path-traversal-shaped input deliberately) must still
    # round-trip: mark_error.py's write-side sanitization and
    # capture.py's read-side sanitization are independently duplicated
    # code, so this guards against them silently drifting apart.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        hostile_session_id = "../../etc/evil"

        mark_result = _run(
            MARK_ERROR_PY,
            json.dumps(_post_tool_use_failure_payload(hostile_session_id)),
            env,
        )
        assert mark_result.returncode == 0

        # No file escaped plugin_data_dir: it must land exactly one level
        # of (expected) per-project-slug nesting below plugin_data_dir --
        # not directly in plugin_data_dir (pre-Finding-C1 shape) and not
        # anywhere deeper/elsewhere (which would indicate the hostile
        # session_id actually achieved some traversal).
        created = list(plugin_data_dir.rglob("*.marker"))
        assert len(created) == 1
        expected_parent = plugin_data_dir / _project_slug(FAKE_PROJECT_DIR)
        assert created[0].parent == expected_parent

        capture_result = _run(
            CAPTURE_PY, json.dumps(_stop_payload(hostile_session_id)), env
        )
        assert capture_result.returncode == 0
        parsed = json.loads(capture_result.stdout)
        assert (
            parsed["hookSpecificOutput"]["additionalContext"]
            == _expected_additional_context(hostile_session_id)
        )


def test_marker_partitioning_is_isolated_per_project_dir() -> None:
    # Companion to server/tests/test_main.py's
    # test_cache_is_partitioned_per_project_not_shared_across_projects
    # (final whole-project review, Finding C1), at the hook layer: two
    # different CLAUDE_PROJECT_DIR values pointed at the SAME
    # CLAUDE_PLUGIN_DATA must not let one project's marker leak into a
    # capture.py run for a DIFFERENT project -- even reusing the exact
    # same session_id (which would never happen in practice, since
    # session ids are globally unique, but proves the isolation actually
    # comes from project partitioning and not merely from session_id
    # uniqueness).
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        session_id = "shared-session-id-used-by-both-projects"

        env_a = _env_with_plugin_data(plugin_data_dir, project_dir="/fake/project/a")
        env_b = _env_with_plugin_data(plugin_data_dir, project_dir="/fake/project/b")

        mark_result = _run(
            MARK_ERROR_PY,
            json.dumps(_post_tool_use_failure_payload(session_id)),
            env_a,
        )
        assert mark_result.returncode == 0

        # Project A's own capture.py run sees the marker it just wrote.
        capture_a = _run(CAPTURE_PY, json.dumps(_stop_payload(session_id)), env_a)
        assert capture_a.returncode == 0
        assert (
            json.loads(capture_a.stdout)["hookSpecificOutput"]["additionalContext"]
            == _expected_additional_context(session_id)
        )

        # Project B's capture.py run -- same CLAUDE_PLUGIN_DATA, same
        # session_id, DIFFERENT CLAUDE_PROJECT_DIR -- must NOT see it.
        capture_b = _run(CAPTURE_PY, json.dumps(_stop_payload(session_id)), env_b)
        assert capture_b.returncode == 0
        assert capture_b.stdout == "", (
            "project B must not see a marker written under project A's "
            "partition of the same shared CLAUDE_PLUGIN_DATA"
        )

        # The two projects partition into different subdirectories (both
        # exist -- capture.py's own _plugin_data_dir() eagerly mkdir()s
        # the directory just to check for a marker, even when none is
        # found, matching mark_error.py's identical "must not fail on a
        # missing directory" eagerness), but only project A's actually
        # contains a marker file.
        subdirs = sorted(p.name for p in plugin_data_dir.iterdir() if p.is_dir())
        assert len(subdirs) == 2, f"expected two per-project subdirectories, got {subdirs}"
        project_a_dir = plugin_data_dir / _project_slug("/fake/project/a")
        project_b_dir = plugin_data_dir / _project_slug("/fake/project/b")
        assert list(project_a_dir.glob("*.marker")) != []
        assert list(project_b_dir.glob("*.marker")) == []


# --- shared hygiene checks -------------------------------------------------


def test_no_non_stdlib_imports() -> None:
    # Same constraint/check as hooks/tests/test_retrieve.py: both
    # scripts must stay stdlib-only so hooks.json can invoke them via
    # plain `python3`, no `uv run` startup cost on every tool failure or
    # every Stop event.
    stdlib_modules = sys.stdlib_module_names  # type: ignore[attr-defined]

    for script in (MARK_ERROR_PY, CAPTURE_PY):
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        non_stdlib = {name for name in imported if name not in stdlib_modules}
        assert not non_stdlib, f"{script.name} imports non-stdlib modules: {non_stdlib}"


if __name__ == "__main__":
    # Plain-script runner so this passes the "standalone script test" bar
    # without requiring pytest to be installed, matching test_retrieve.py.
    tests = [
        test_mark_error_creates_marker_file_at_expected_path,
        test_mark_error_creates_plugin_data_dir_if_missing,
        test_mark_error_emits_no_stdout,
        test_mark_error_no_op_on_missing_session_id,
        test_mark_error_unconditional_even_on_malformed_stdin,
        test_mark_error_unconditional_even_on_non_utf8_stdin,
        test_capture_emits_nudge_when_marker_exists,
        test_capture_no_op_when_different_session_has_no_marker,
        test_capture_no_op_when_no_marker_at_all,
        test_capture_does_not_delete_the_marker,
        test_capture_no_op_on_missing_session_id,
        test_capture_no_op_on_malformed_stdin,
        test_capture_no_op_on_non_utf8_stdin,
        test_end_to_end_mark_then_capture_same_session,
        test_end_to_end_clean_session_writes_nothing,
        test_sanitization_is_consistent_between_write_and_read,
        test_marker_partitioning_is_isolated_per_project_dir,
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
