# Review package: Task 7 (no git — full file dump)

## Files
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
/Users/ilaakshmishra/Documents/hindsight/.claude/settings.local.json
/Users/ilaakshmishra/Documents/hindsight/.gitignore
/Users/ilaakshmishra/Documents/hindsight/.mcp.json
/Users/ilaakshmishra/Documents/hindsight/README.md
/Users/ilaakshmishra/Documents/hindsight/agents/lesson-distiller.md
/Users/ilaakshmishra/Documents/hindsight/hooks/capture.py
/Users/ilaakshmishra/Documents/hindsight/hooks/hooks.json
/Users/ilaakshmishra/Documents/hindsight/hooks/mark_error.py
/Users/ilaakshmishra/Documents/hindsight/hooks/retrieve.py
/Users/ilaakshmishra/Documents/hindsight/hooks/tests/test_mark_and_capture.py
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
  "description": "Nudge Claude to check the hindsight lesson database before proposing a fix on every tool failure (also marking the session), and nudge it to capture a resolved-error lesson when the session ends.",
  "hooks": {
    "PostToolUseFailure": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/retrieve.py"],
            "timeout": 30
          },
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/mark_error.py"],
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/capture.py"],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

## hooks/mark_error.py
```
#!/usr/bin/env python3
"""hindsight `PostToolUseFailure` hook: per-session error marker (Task 7).

Registered in `hooks/hooks.json` as a *second* command alongside
`retrieve.py`, under the same `PostToolUseFailure` matcher group (see
that file's own module docstring for the confirmed payload shape --
unchanged by this script, so there's no need to re-fetch or re-confirm
it here). Claude Code spawns this script once per genuine tool failure,
alongside (not instead of) `retrieve.py`. Per the live hooks docs
("Hook execution" -- fetched during this task): "All matching hooks run
in parallel," and when several hooks emit `additionalContext` for the
same event, Claude receives all of them concatenated. This script
deliberately emits *no* `hookSpecificOutput` at all (see `main` below),
so it can never add to, conflict with, or otherwise change what
`retrieve.py`'s Task-6-approved nudge already puts in front of Claude --
this file is purely additive housekeeping, not a second nudge.

Job: touch an empty marker file at
`${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` so `hooks/capture.py`
(the `Stop` hook, also Task 7) can tell, at session end, whether *this*
session ever hit a tool failure worth possibly turning into a lesson.
Content doesn't matter, only existence, per the brief -- the file is
created empty (`Path.touch`).

Never blocks or fails the tool-failure event over this: any problem
reading stdin, parsing the payload, a missing/malformed `session_id`, or
a filesystem error while creating the marker's parent directory or the
file itself is swallowed, and this exits 0 either way. The brief calls
out explicitly that a missing `${CLAUDE_PLUGIN_DATA}` directory (e.g. a
freshly installed plugin, first failure of the session) "must not fail
or block" this hook -- `_plugin_data_dir` below creates it
(`mkdir(parents=True, exist_ok=True)`) rather than assuming it exists.

Env var resolution (`${CLAUDE_PLUGIN_DATA}`, marker file location):
duplicates the tiny amount of logic `server/main.py`'s `_cache_dir()`
uses (`os.environ.get("CLAUDE_PLUGIN_DATA")`, then
`.mkdir(parents=True, exist_ok=True)`; see that function's own
docstring for the full env-var-injection story) rather than importing
from `server/` -- hooks are separate Python processes from the MCP
server (different concern, different process lifecycle; importing
across that boundary for ~10 lines of logic would just be a coupling
liability for no real benefit). This is also intentionally NOT factored
into a new shared helper module under `hooks/` and imported by both this
file and `hooks/capture.py`: every hook script in this plugin is a
fully standalone, dependency-free `python3` script (the precedent Task
6's `retrieve.py` set, verified by its own `test_no_non_stdlib_imports`
test), so this duplicates the same ~10-line helper a second time
(byte-for-byte identical to `capture.py`'s copy) rather than introducing
an intra-`hooks/` import dependency between two scripts that are
otherwise independently invoked, independently timed-out, and
independently tested.

The fallback used when `CLAUDE_PLUGIN_DATA` is unset (standalone/test
use, same rationale as `_cache_dir()`'s own documented fallback) is
`${CLAUDE_PROJECT_DIR or cwd}/.debug-memory/.plugin-data` -- a different
leaf directory name than `_cache_dir()`'s own `.index-cache` fallback,
since marker files aren't the search index cache. In a real plugin
install both marker files and the index cache land under the very same
real `${CLAUDE_PLUGIN_DATA}` directory regardless, per the brief's
literal path `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (no
subdirectory). Tests in this repo don't rely on the fallback; they set
`CLAUDE_PLUGIN_DATA` explicitly per-subprocess so each test is isolated
to its own tmp directory.

`session_id` is sanitized to a safe filename component
(`[A-Za-z0-9_-]` only; anything else is replaced with `_`) before being
used in a path -- defense in depth against a malformed/hostile payload
turning a filesystem-path-shaped field into a path-traversal write (same
precedent as `server/main.py`'s `prune_lesson` id validation, though
here it degrades to a differently-named marker file rather than raising,
since silently degrading beats crashing a step that must never block the
tool-failure event). `hooks/capture.py` applies the *identical*
sanitization so a given real `session_id` always maps to the same marker
path on both the write side (here) and its read side.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _plugin_data_dir() -> Path:
    """Resolve `${CLAUDE_PLUGIN_DATA}` (see module docstring), creating
    it if it doesn't exist yet.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / ".plugin-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _marker_path(session_id: str) -> Path:
    safe_id = _SAFE_CHARS_RE.sub("_", session_id)
    return _plugin_data_dir() / f"session-{safe_id}.marker"


def main() -> int:
    # Same stdin-resilience pattern as retrieve.py: raw bytes decoded
    # with errors="replace" so genuinely non-UTF-8 stdin can't raise
    # before this script even gets a chance to try parsing JSON.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id.strip():
        # No usable session_id -- nothing to mark, but this must not be
        # treated as an error (a garbled/unexpected payload shape is not
        # this hook's problem to raise about).
        return 0

    try:
        _marker_path(session_id).touch(exist_ok=True)
    except Exception:
        # Marker-writing is best-effort housekeeping; a filesystem
        # problem here must never fail the PostToolUseFailure event.
        pass

    # Deliberately no stdout output at all -- see module docstring.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## hooks/capture.py
```
#!/usr/bin/env python3
"""hindsight `Stop` hook: nudge to capture a resolved-error lesson (Task 7).

Registered in `hooks/hooks.json` against `Stop` (fires once at the end
of a turn in which Claude stops responding). Claude Code spawns this
script once per `Stop` event with that event's JSON payload on stdin.

Payload shape / `session_id` field (per the Task 7 brief's instruction
to verify rather than assume): fetched
`https://code.claude.com/docs/en/hooks.md` directly during this task.
Its "Common input fields" section documents `session_id` ("Current
session identifier") as one of the fields every hook event receives,
`Stop` included -- not something guessed by analogy with
`PostToolUseFailure` alone. The same section separately notes that
`Stop` (and `SubagentStop`) additionally carry a `last_assistant_message`
field that other events don't; this hook doesn't use that field or any
other beyond `session_id`.

Job: check whether *this session* ever hit a tool failure that
`hooks/mark_error.py` (the `PostToolUseFailure` hook, also Task 7)
marked by touching `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`.

  - No marker for this `session_id` (including when `session_id` is
    itself missing or unparseable from a malformed payload): exit 0,
    print nothing. A session that never hit a tool failure -- the common
    case, true for every `Stop` in a clean session -- must produce zero
    stdout; this is the "no-op" behavior `hooks/tests/
    test_mark_and_capture.py` checks for.
  - Marker exists: print the fixed `hookSpecificOutput` nudge below and
    exit 0.

This hook never deletes the marker file. Deletion only happens after a
real save, from `agents/lesson-distiller.md` (see that file for the
full reasoning) -- so an unresolved session's *next* `Stop` (if the
session continues) can still trigger this same nudge once the error IS
actually resolved. Deleting here, on the mere act of nudging, would
break that: the nudge would fire at most once per session regardless of
whether anything was ever actually captured.

The nudge text below is phrased factually/descriptively, not
imperatively, matching `retrieve.py`'s own phrasing rationale (see that
file's docstring for the full argument): an imperative "dispatch the
agent... exclude secrets..." risks tripping Claude's own
prompt-injection defenses on its *own* hook output, which would surface
this raw text to the user instead of Claude acting on it. This exact
string is taken verbatim from the Task 7 brief (itself already corrected
to factual phrasing after Task 6's review, per that brief's own note) --
it is not paraphrased or reworded here.

Env var resolution / sanitization: an intentional byte-for-byte
duplicate of `hooks/mark_error.py`'s `_plugin_data_dir`/`_marker_path`
(see that file's module docstring for the full reasoning on why this is
duplicated -- both from `server/`, and between these two hook scripts,
rather than shared via a new intra-`hooks/` helper module). Kept
identical to `mark_error.py`'s copy so a given real `session_id` always
resolves to the same marker path on both the write side (`mark_error.py`)
and this read side.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Verbatim from the Task 7 brief -- do not reword. If this ever needs to
# change, it must be a deliberate, reviewed edit, not incidental drift;
# hooks/tests/test_mark_and_capture.py asserts this exact string.
ADDITIONAL_CONTEXT = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from a concise summary — error signature, "
    "symptom, failed approaches, root cause, fix, with secrets/tokens/"
    "customer data excluded. Not worth dispatching if the error wasn't "
    "actually resolved this session."
)


def _plugin_data_dir() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / ".plugin-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _marker_path(session_id: str) -> Path:
    safe_id = _SAFE_CHARS_RE.sub("_", session_id)
    return _plugin_data_dir() / f"session-{safe_id}.marker"


def main() -> int:
    # Same stdin-resilience pattern as retrieve.py/mark_error.py: raw
    # bytes decoded with errors="replace" so genuinely non-UTF-8 stdin
    # can't raise before this script even tries to parse JSON.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id.strip():
        # No usable session_id -- can't know which marker to check, so
        # this degrades to the same "nothing to capture" no-op as a
        # genuinely marker-less session, rather than raising.
        return 0

    try:
        marker_exists = _marker_path(session_id).exists()
    except Exception:
        # Filesystem trouble reading CLAUDE_PLUGIN_DATA -> treat as
        # no-op rather than crash; there is nothing safe to report if
        # this hook can't even check whether a marker exists.
        marker_exists = False

    if not marker_exists:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": ADDITIONAL_CONTEXT,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## agents/lesson-distiller.md
```
---
name: lesson-distiller
description: >
  Structures a resolved debugging incident into a saved hindsight lesson
  and clears the session's capture marker. Dispatch with subagent_type:
  lesson-distiller only after the Stop hook's capture nudge has fired
  AND the error that caused the earlier tool failure has actually been
  resolved this session -- not worth dispatching otherwise. The dispatch
  prompt must include: a concise incident summary (error signature,
  symptom, approaches that were actually tried and failed, root cause,
  fix, and whether the fix was verified to actually work) and the
  session's session_id (the same session_id the Stop hook payload
  carried).
tools: Read, Bash, mcp__hindsight__save_lesson
model: inherit
---

You are the hindsight lesson-distiller. You are dispatched once, after a
tool failure earlier in a session has been resolved, with a concise
incident summary and a `session_id` in your prompt. Your job: turn that
summary into one saved lesson via the `hindsight` MCP server's
`save_lesson` tool, then clear the session's capture marker so the next
`Stop` in this session doesn't re-nudge for the same incident. Nothing
else. You do not investigate the codebase, you do not re-run the failing
command, and you do not fix anything -- by the time you're dispatched,
the fix already happened; you're only recording it.

## 1. Decide whether there's anything to save

If the incident summary you were given doesn't actually describe a
*resolved* error (the failure is described as still happening, or the
summary is too vague to tell), do not call `save_lesson`. Say so plainly
in your final response instead -- explain what's missing or unclear --
and stop. A half-true lesson saved to the shared store is worse than no
lesson: someone else will trust it later.

## 2. Structure the incident into `save_lesson`'s exact input shape

`save_lesson` takes these fields (same contract the `/hindsight save`
skill uses for the manual path -- see `skills/hindsight/SKILL.md` if you
want the fuller field-by-field description):

- `title` (str, required) -- short human-readable summary.
- `domain` (list[str], required) -- e.g. `["react", "javascript"]`.
- `error_signature` (str, required) -- the distinguishing error
  message/code.
- `symptom` (str, required) -- what was observed, in prose.
- `failed_approaches` (list[str], required) -- things that were tried
  and did NOT fix it. May be `[]` if the summary says nothing was tried
  first, or doesn't mention any -- see the fabrication rule below.
- `root_cause` (str, required) -- the actual underlying cause.
- `fix` (str, required) -- what actually fixed it.
- `confidence` (`"confirmed"` or `"probable"`, defaults to
  `"probable"`) -- use `"confirmed"` ONLY if the incident summary says
  the fix was actually verified working (tests passed, the error
  stopped recurring, etc.). If verification isn't mentioned or is
  ambiguous, leave it as `"probable"`. When in doubt, `"probable"`.

Derive every field's *content* only from what the incident summary
actually says. Don't pad a thin summary with plausible-sounding detail
to make the lesson feel more complete.

### Never fabricate

Never invent a `failed_approaches` entry that the summary doesn't
actually describe as having been tried. An empty list is a correct,
honest answer when nothing was tried first (or the summary doesn't say)
-- it is never a reason to make something up. The same rule applies to
every other field: if the summary doesn't give you enough to respon-
sibly fill a required field, say so in your final response (per step 1)
rather than guessing.

### Never include secrets, tokens, or customer data

The `hindsight` MCP server's `save_lesson` runs everything through a
server-side scrubber (`server/scrub.py`) before writing to disk, but
that is a safety net, not your first line of defense. Before calling
`save_lesson`, look over every field you're about to send for anything
that looks like a secret, API key, access token, password, connection
string with embedded credentials, or customer-identifying data (real
names, emails, account IDs, etc. that belong to an end user rather than
to the codebase itself). Redact or omit it -- replace with something
like `<redacted>` or drop the surrounding detail -- rather than passing
it through. You're dispatched unattended, so there's no one to ask
first; when in doubt, leave it out rather than include it.

## 3. Call `save_lesson`

Call `mcp__hindsight__save_lesson` with the fields you built. On
success it returns `{id, path, wrote: true, warnings?}`. If it returns a
`warnings` field, that means some *other* previously-saved lesson failed
to index and is currently unsearchable -- mention it in your final
response; it's unrelated to whether *this* save succeeded but is worth
surfacing.

If the call fails (tool error), report the failure plainly in your final
response and stop -- do not attempt the marker deletion below, since
nothing was actually captured.

## 4. Delete the session's marker file

Only after a successful `save_lesson` call: delete
`${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`, using the
`session_id` you were given in your dispatch prompt. This is what stops
a later `Stop` in the same session from re-emitting the capture nudge
for an incident that's now already saved.

Use `Bash` for the deletion, since there is no dedicated file-delete
tool available to you:

```bash
rm -f "${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker"
```

substituting the literal `session_id` value you were given for
`<session_id>` (the hook scripts that write and read this marker
sanitize `session_id` to `[A-Za-z0-9_-]` before using it in a path,
replacing every other character with `_` -- apply the identical
substitution to the `session_id` you were given before building this
path, so you delete the exact file they created/checked, not a
differently-named one).

If `$CLAUDE_PLUGIN_DATA` turns out to be unset or empty in your shell,
or the `rm` fails for any other reason, don't treat that as a hard
failure of your overall task -- the lesson is already saved by this
point, which is the part that matters. Just note in your final response
that marker cleanup didn't happen, so whoever's watching knows a
`Stop` event later in this same session may nudge about this incident
again even though it's already captured (harmless redundancy, not a
correctness problem -- the same marker is what lets an *unresolved*
session's later `Stop` still trigger capture once it IS resolved, so
this hook family is intentionally biased toward a spurious extra nudge
over a silently dropped one).

## 5. Final response

Report plainly: whether a lesson was saved (and its `id`/`path` if so),
whether the marker was cleared, and anything you declined to do and why
(step 1's resolved-error check, step 2's fabrication guard, or a
`save_lesson` failure). Keep it short -- this is a background capture
step, not a report the user needs to read closely.
```

## hooks/tests/test_mark_and_capture.py
```
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

Runnable directly (`python3 hooks/tests/test_mark_and_capture.py`) or
via pytest -- no non-stdlib imports either way, matching both hook
scripts under test.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from subprocess import CompletedProcess, run

HOOKS_DIR = Path(__file__).resolve().parent.parent
MARK_ERROR_PY = HOOKS_DIR / "mark_error.py"
CAPTURE_PY = HOOKS_DIR / "capture.py"

# Exact string from the Task 7 brief -- copied into hooks/capture.py
# verbatim (not paraphrased) and re-asserted here so a future accidental
# edit to either copy is caught. See capture.py's own module docstring
# for why this is phrased factually rather than imperatively.
EXPECTED_ADDITIONAL_CONTEXT = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from a concise summary — error signature, "
    "symptom, failed approaches, root cause, fix, with secrets/tokens/"
    "customer data excluded. Not worth dispatching if the error wasn't "
    "actually resolved this session."
)


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


def _env_with_plugin_data(plugin_data_dir: Path) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_DATA"] = str(plugin_data_dir)
    # Never let a real CLAUDE_PROJECT_DIR from the outer environment
    # leak into the fallback path this hook would otherwise take.
    env.pop("CLAUDE_PROJECT_DIR", None)
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


def _marker_path(plugin_data_dir: Path, session_id: str) -> Path:
    # Mirrors both hook scripts' sanitization exactly (see their
    # docstrings) -- this test helper is a third, independent
    # transcription of the same rule, so a mismatch between the two real
    # implementations would still show up as a test failure rather than
    # all three copies drifting together.
    import re

    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    return plugin_data_dir / f"session-{safe_id}.marker"


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
        _marker_path(plugin_data_dir, session_id).touch()

        result = _run(CAPTURE_PY, json.dumps(_stop_payload(session_id)), env)

        assert result.returncode == 0, f"stderr: {result.stderr!r}"
        parsed = json.loads(result.stdout)
        assert parsed == {
            "hookSpecificOutput": {
                "hookEventName": "Stop",
                "additionalContext": EXPECTED_ADDITIONAL_CONTEXT,
            }
        }


def test_capture_no_op_when_different_session_has_no_marker() -> None:
    # The explicit "no-op" case: a marker exists for one session, but
    # THIS Stop event is for a different session_id that never hit a
    # failure -- must produce empty stdout and exit 0, not the nudge.
    with tempfile.TemporaryDirectory() as tmp:
        plugin_data_dir = Path(tmp)
        env = _env_with_plugin_data(plugin_data_dir)
        _marker_path(plugin_data_dir, "some-other-session").touch()

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
        marker = _marker_path(plugin_data_dir, session_id)
        marker.touch()

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
            == EXPECTED_ADDITIONAL_CONTEXT
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

        # No file escaped plugin_data_dir.
        created = list(plugin_data_dir.rglob("*.marker"))
        assert len(created) == 1
        assert created[0].parent == plugin_data_dir

        capture_result = _run(
            CAPTURE_PY, json.dumps(_stop_payload(hostile_session_id)), env
        )
        assert capture_result.returncode == 0
        parsed = json.loads(capture_result.stdout)
        assert (
            parsed["hookSpecificOutput"]["additionalContext"]
            == EXPECTED_ADDITIONAL_CONTEXT
        )


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
