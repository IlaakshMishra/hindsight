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
marked by touching
`${CLAUDE_PLUGIN_DATA}/<project slug>/session-<session_id>.marker`. The
`<project slug>` component (final whole-project review, Finding C1) is
explained in `hooks/mark_error.py`'s own module docstring -- this script
must compute the identical slug or it will never find a marker that
script wrote.

  - No marker for this `session_id` (including when `session_id` is
    itself missing or unparseable from a malformed payload): exit 0,
    print nothing. A session that never hit a tool failure -- the common
    case, true for every `Stop` in a clean session -- must produce zero
    stdout; this is the "no-op" behavior `hooks/tests/
    test_mark_and_capture.py` checks for.
  - Marker exists: print the `hookSpecificOutput` nudge below (with this
    session's `session_id` interpolated into it -- see Finding I1 below)
    and exit 0.

This hook never deletes the marker file. Deletion only happens after a
real save, from `agents/lesson-distiller.md` calling the `hindsight` MCP
server's `clear_capture_marker` tool (`server/main.py`; see that file
and `agents/lesson-distiller.md` for the full reasoning -- an earlier
version deleted the marker via the `Bash` tool directly, which turned
out not to reliably see `${CLAUDE_PLUGIN_DATA}` in that subprocess's
environment) -- so an unresolved session's *next* `Stop` (if the
session continues) can still trigger this same nudge once the error IS
actually resolved. Deleting here, on the mere act of nudging, would
break that: the nudge would fire at most once per session regardless of
whether anything was ever actually captured.

The nudge text below is phrased factually/descriptively, not
imperatively, matching `retrieve.py`'s own phrasing rationale (see that
file's docstring for the full argument): an imperative "dispatch the
agent... exclude secrets..." risks tripping Claude's own
prompt-injection defenses on its *own* hook output, which would surface
this raw text to the user instead of Claude acting on it. The bulk of
this string is taken verbatim from the Task 7 brief (itself already
corrected to factual phrasing after Task 6's review, per that brief's own
note) -- not paraphrased or reworded, EXCEPT for one addition made by the
final whole-project review's Finding I1 fix (see below): the text now
also states this session's `session_id` value literally, in backticks.

Finding I1 / session_id interpolation: `agents/lesson-distiller.md`
expects to be dispatched WITH a `session_id`, so it can call
`clear_capture_marker(session_id)` after a successful save (see that
agent file and `server/main.py`'s `clear_capture_marker` for why that
matters -- without it, this same nudge re-fires on every subsequent
`Stop` in the session even after the lesson is actually captured). But
nothing before this fix ever handed Claude that value: this script reads
`session_id` from the `Stop` payload to decide whether to nudge at all,
but the nudge text itself was a FIXED string that never included it, and
Claude Code does not automatically surface a hook's raw JSON input
fields into the model's context -- only what a hook actually prints in
`additionalContext` is visible. So the dispatching Claude turn had no
reliable way to know the real `session_id` to hand to the distiller,
`clear_capture_marker` would fail to find/clear the marker, and the nudge
would re-fire every subsequent `Stop` for the rest of the session -- the
exact bug Task 7 already fixed once (an earlier version tried deleting
the marker via a `Bash`-tool `rm -f` that couldn't see
`${CLAUDE_PLUGIN_DATA}`), reappearing via this different gap. The fix:
`_build_additional_context` below interpolates the real, UNSANITIZED
`session_id` (see that function's own docstring for why it's the raw
value, not the sanitized `safe_id` used for the marker filename)
directly into the printed text, so it is now literally present in what
Claude sees and can copy into the distiller's dispatch prompt.

Env var resolution / sanitization: an intentional byte-for-byte
duplicate of `hooks/mark_error.py`'s `_project_slug`/`_plugin_data_dir`/
`_marker_path` (see that file's module docstring for the full reasoning
on why this is duplicated -- both from `server/`, and between these two
hook scripts, rather than shared via a new intra-`hooks/` helper module).
Kept identical to `mark_error.py`'s copy so a given real `session_id`
always resolves to the same marker path on both the write side
(`mark_error.py`) and this read side.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Must match server/main.py's _FALLBACK_CACHE_LEAF and
# hooks/mark_error.py's copy byte-for-byte (Finding I4) -- see the module
# docstring's "Env var resolution" section.
_FALLBACK_CACHE_LEAF = ".hindsight-cache"

# Template for the Stop-hook nudge (final whole-project review, Finding
# I1). The non-`{session_id}` portions are taken verbatim from the Task 7
# brief (see module docstring) -- do not reword them incidentally.
# `hooks/tests/test_mark_and_capture.py` builds the same expected string
# per-session_id and asserts it exactly, so this and that test's copy
# must stay in sync.
ADDITIONAL_CONTEXT_TEMPLATE = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from this session's session_id, `{session_id}`, "
    "and a concise summary — error signature, symptom, failed approaches, "
    "root cause, fix — with secrets/tokens/customer data excluded. Not "
    "worth dispatching if the error wasn't actually resolved this "
    "session."
)


def _build_additional_context(session_id: str) -> str:
    """Fill `ADDITIONAL_CONTEXT_TEMPLATE` with this session's real,
    UNSANITIZED `session_id` (not the filesystem-safe `safe_id` used for
    the marker filename -- the text is not a path, so the raw value is
    fine here, and the distiller agent needs the real id to pass back to
    `clear_capture_marker`, not a lossy sanitized copy of it).
    """
    return ADDITIONAL_CONTEXT_TEMPLATE.format(session_id=session_id)


def _project_slug() -> str:
    """Byte-for-byte duplicate of `server/main.py`'s and
    `hooks/mark_error.py`'s `_project_slug()` (see either's docstring for
    the full C1-fix reasoning). Must stay identical across all three
    copies -- see `hooks/mark_error.py`'s copy for why.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    key = project_dir if project_dir else str(Path.cwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    basename = Path(key).name or "root"
    safe_basename = _SAFE_CHARS_RE.sub("_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _plugin_data_dir() -> Path:
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
            "additionalContext": _build_additional_context(session_id),
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
