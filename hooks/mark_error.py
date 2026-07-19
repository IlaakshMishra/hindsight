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
`${CLAUDE_PLUGIN_DATA}/<project slug>/session-<session_id>.marker` so
`hooks/capture.py` (the `Stop` hook, also Task 7) can tell, at session
end, whether *this* session ever hit a tool failure worth possibly
turning into a lesson. Content doesn't matter, only existence, per the
brief -- the file is created empty (`Path.touch`).

The `<project slug>` path component (final whole-project review, Finding
C1) was added because `${CLAUDE_PLUGIN_DATA}` is one directory per plugin
PER MACHINE, not per project -- shared across every repo on this machine
that has this plugin installed. Marker filenames were never actually at
risk of colliding across projects (session ids are globally unique), but
`server/main.py`'s `_cache_dir()` -- which resolves the very same
`${CLAUDE_PLUGIN_DATA}` directory this script writes markers into -- had
exactly this per-project-leakage bug for `index.json` (see that module's
`_project_slug` docstring for the full story). Co-locating markers under
the same per-project subdirectory as the index cache keeps one consistent
partitioning scheme instead of a mix of per-project and machine-global
files sitting side by side in `${CLAUDE_PLUGIN_DATA}`.

Never blocks or fails the tool-failure event over this: any problem
reading stdin, parsing the payload, a missing/malformed `session_id`, or
a filesystem error while creating the marker's parent directory or the
file itself is swallowed, and this exits 0 either way. The brief calls
out explicitly that a missing `${CLAUDE_PLUGIN_DATA}` directory (e.g. a
freshly installed plugin, first failure of the session) "must not fail
or block" this hook -- `_plugin_data_dir` below creates it
(`mkdir(parents=True, exist_ok=True)`) rather than assuming it exists.

Env var resolution (`${CLAUDE_PLUGIN_DATA}`, marker file location):
duplicates the tiny amount of logic `server/main.py`'s `_cache_dir()`/
`_project_slug()` use (`os.environ.get("CLAUDE_PLUGIN_DATA")`,
`hashlib.sha256`-derived project slug, then
`.mkdir(parents=True, exist_ok=True)`; see those functions' own
docstrings for the full env-var-injection and per-project-partitioning
story) rather than importing from `server/` -- hooks are separate Python
processes from the MCP server (different concern, different process
lifecycle; importing across that boundary for ~15 lines of logic would
just be a coupling liability for no real benefit). This is also
intentionally NOT factored into a new shared helper module under
`hooks/` and imported by both this file and `hooks/capture.py`: every
hook script in this plugin is a fully standalone, dependency-free
`python3` script (the precedent Task 6's `retrieve.py` set, verified by
its own `test_no_non_stdlib_imports` test), so this duplicates the same
helper a second time (byte-for-byte identical to `capture.py`'s copy)
rather than introducing an intra-`hooks/` import dependency between two
scripts that are otherwise independently invoked, independently
timed-out, and independently tested.

The fallback used when `CLAUDE_PLUGIN_DATA` is unset (standalone/test
use, same rationale as `_cache_dir()`'s own documented fallback) is
`${CLAUDE_PROJECT_DIR or cwd}/.debug-memory/.hindsight-cache` -- the
SAME leaf directory name `server/main.py`'s `_cache_dir()` fallback uses
(`_FALLBACK_CACHE_LEAF`). Before the final whole-project review's Finding
I4 fix, this fallback used a different leaf name (`.plugin-data`) than
`_cache_dir()`'s own fallback (`.index-cache`) -- two different
directories for what, in the fallback case, must be the exact same
directory: a marker this script wrote was never actually found by
`server/main.py`'s `clear_capture_marker` when both ran with
`CLAUDE_PLUGIN_DATA` unset (a standalone/test-only scenario -- a real
plugin install always has `CLAUDE_PLUGIN_DATA` set, so this gap never
affected a real install, only standalone runs without it). One name, used
by every one of the three files that needs it, closes that gap. No
`_project_slug()` partitioning is applied to THIS fallback path -- it's
already nested under `${CLAUDE_PROJECT_DIR}` (or `cwd`), i.e. already
per-project on its own, so adding a slug subdirectory on top would just
be redundant double-nesting (matches `_cache_dir()`'s own fallback
reasoning).

In a real plugin install, both marker files and the index cache land
under the very same real `${CLAUDE_PLUGIN_DATA}/<project slug>/`
directory -- see the module docstring's "Job" section above for why the
`<project slug>` component exists. Tests in this repo don't rely on the
fallback; they set `CLAUDE_PLUGIN_DATA` (and, since the Finding C1 fix,
`CLAUDE_PROJECT_DIR`, so the computed project slug is deterministic)
explicitly per-subprocess so each test is isolated to its own tmp
directory.

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

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Must match server/main.py's _FALLBACK_CACHE_LEAF byte-for-byte (Finding
# I4) -- see the module docstring's "Env var resolution" section.
_FALLBACK_CACHE_LEAF = ".hindsight-cache"


def _project_slug() -> str:
    """Byte-for-byte duplicate of `server/main.py`'s `_project_slug()`
    (see that function's docstring for the full C1-fix reasoning) --
    duplicated rather than imported for the same "hooks are standalone
    dependency-free scripts" reason every other helper in this file is
    duplicated (see module docstring). Must stay identical to
    `server/main.py`'s copy and to `hooks/capture.py`'s copy: all three
    partition `${CLAUDE_PLUGIN_DATA}` by this same slug, and a mismatch
    would silently reintroduce Finding C1's cross-project leakage for
    marker files specifically.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    key = project_dir if project_dir else str(Path.cwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    basename = Path(key).name or "root"
    safe_basename = _SAFE_CHARS_RE.sub("_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _plugin_data_dir() -> Path:
    """Resolve this project's `${CLAUDE_PLUGIN_DATA}/<project slug>/`
    directory (see module docstring), creating it if it doesn't exist
    yet.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data) / _project_slug()
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / _FALLBACK_CACHE_LEAF
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
