# Final whole-plugin review package: hindsight (no git — full source dump)

## Full file tree
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/marketplace.json
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
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
/Users/ilaakshmishra/Documents/hindsight/server/reindex.py
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

## .claude-plugin/plugin.json
```
{
  "name": "hindsight",
  "version": "0.1.0",
  "description": "Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice."
}
```

## .claude-plugin/marketplace.json
```
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "hindsight",
  "description": "Shared, on-demand memory of debugging sessions for Claude Code teams — solve an error once, skip the dead ends next time. Local-first, git-native, nothing sent to the cloud.",
  "owner": {
    "name": "IlaakshMishra"
  },
  "plugins": [
    {
      "name": "hindsight",
      "description": "Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice.",
      "source": "./",
      "category": "development"
    }
  ]
}
```

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

## README.md
```
# hindsight

Hindsight gives your team shared, on-demand memory of every debugging
session. Solve an error once, and every teammate's Claude skips the dead
ends next time. Lives in your repo. Sends nothing to the cloud.

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be installed on
your machine — the MCP server (and the standalone reindex CLI below) are
launched via `uv run`, which auto-provisions its own isolated Python
environment on first use (no manual `pip install`/venv setup required).

## Why not just a bigger CLAUDE.md?

The reason Hindsight is not just a bigger CLAUDE.md is context economics.

CLAUDE.md and generic memory files are always loaded. They sit in the
context window on every request. A growing library of past errors would
bloat the window, trigger compaction, and cost tokens and quality.

Hindsight keeps the library outside the context window and pulls in only
the one or two relevant lessons at the exact moment an error appears. A
500-lesson library costs nothing until you hit an error, then costs one
lesson.

Always-on memory eats context. On-demand retrieval stays lean. That
difference is the whole product.

## Install

```
/plugin marketplace add <path-or-git-url-to-this-repo>
/plugin install hindsight
```

Replace `<path-or-git-url-to-this-repo>` with wherever this repo lives for
you — a local path (e.g. `.` if you're already inside a checkout of it) or
a git remote URL once it's pushed somewhere your team can reach. This repo
doesn't ship with a fixed remote baked in, so there's nothing to fake here
— point the marketplace at whatever location you actually cloned or will
push it to.

Once installed, lessons your team saves live at `.debug-memory/lessons/`
in each consuming repo — commit that directory like any other source file
so the whole team shares the same lesson library.

## How it works

```
Developer's Claude Code session
        │
        │ (1) error occurs / session ends
        ▼
   HOOKS  ──── capture nudge ────► Claude distills a lesson ──► calls MCP save_lesson
        │                                                             │
        │ (2) error occurs later                                      ▼
        └──── retrieve nudge ────► Claude calls MCP search_lessons ──► reads top lessons
                                                                       │
                                                     ┌─────────────────┴─────────────────┐
                                                     ▼                                     ▼
                                        .debug-memory/lessons/*.md              local embedding index
                                        (in the git repo, source of truth)      (${CLAUDE_PLUGIN_DATA}, rebuildable)
```

Two hooks do the nudging; Claude does all the reasoning and tool-calling —
the hooks themselves never call an MCP tool directly:

- **On every tool failure** (`PostToolUseFailure`): a hook nudges Claude
  to check `search_lessons` for a past lesson on a similar error before
  proposing a fix, and marks the session as having hit a failure.
- **When Claude's turn ends** (`Stop` — not `SessionEnd`; `SessionEnd` has
  no live model turn left to act on anything, so it can't drive this):
  if this session hit a failure that hasn't been captured yet, a hook
  nudges Claude that the `lesson-distiller` subagent can turn a *resolved*
  incident into a saved lesson.

The lesson files themselves (`.debug-memory/lessons/*.md`) are the source
of truth, committed to your repo like any other file — plain Markdown with
YAML frontmatter, readable and diffable without this plugin at all. The
local embedding index is a rebuildable cache under `${CLAUDE_PLUGIN_DATA}`
(never git-committed, never authoritative) that makes `search_lessons`
fast; see `/hindsight reindex` below for when to force-rebuild it.

## Tool surface

Exposed by the `hindsight` MCP server (`server/main.py`), callable
directly by Claude or via the `/hindsight` skill described below.

| Tool | Signature | What it does |
| --- | --- | --- |
| `search_lessons` | `(query: str, k: int = 3)` | Embeds `query` against the local index and returns the top `k` lessons that clear the similarity threshold — `[]` if nothing does (never a weak match dressed as strong). |
| `save_lesson` | `(title, domain: list[str], error_signature, symptom, failed_approaches: list[str], root_cause, fix, confidence: "confirmed"\|"probable" = "probable")` | Scrubs secrets from every free-text field, writes a new lesson to `.debug-memory/lessons/`, rebuilds the index, and best-effort `git add`s the file (never auto-commits). |
| `list_lessons` | `()` | Returns every saved lesson. |
| `prune_lesson` | `(id: str)` | Deletes a saved lesson by id and rebuilds the index so it stops being searchable immediately. |
| `reindex_lessons` | `()` | Forces a full rebuild of the local index from every lesson file on disk — see `/hindsight reindex` below for when you need this. |

`clear_capture_marker(session_id)` also exists on the MCP server, but it's
internal plumbing the `lesson-distiller` agent uses to mark a captured
incident as done — not something you'd call yourself.

## The `/hindsight` skill

`skills/hindsight/SKILL.md` gives you a manual interface to the same tool
surface from inside a Claude Code session:

```
/hindsight save            - save a new debugging lesson
/hindsight search <query>  - search saved lessons
/hindsight list             - list every saved lesson
/hindsight prune <id>       - delete a saved lesson by id
/hindsight reindex          - force a full rebuild of the search index
```

Most of the time you won't need any of this — the hooks above nudge Claude
to search and save automatically. `/hindsight` is for when you want to do
it by hand: seed the library with an old incident, check what's saved,
clean up a bad lesson, or force a reindex after pulling teammates' newly
committed lessons (the index cache doesn't know about a lesson file until
something rebuilds it — `search_lessons` only auto-rebuilds when the cache
is entirely *missing*, not when it's merely stale).

For reindexing outside a live Claude Code session (CI, a maintainer's own
terminal), a standalone CLI also exists:

```
uv run --no-project --with-requirements server/requirements.txt \
    server/reindex.py [--lessons-dir DIR] [--cache-dir DIR]
```

This is a separate, lower-level entry point from `/hindsight reindex` —
see `server/reindex.py`'s module docstring for why the two aren't the same
code path (short version: the real index-cache location is only reliably
knowable from inside the MCP server process itself).

## Demo

_(Demo GIF not yet recorded — placeholder for a future capture of the
retrieve/capture loop in action.)_

## Local-first, no cloud

Embeddings run locally via `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim)
— no API key, no network call at query time. Lessons never leave your
repo. The only thing that could theoretically leave your machine is
whatever you `git push` yourself.
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
tools: Read, mcp__hindsight__save_lesson, mcp__hindsight__clear_capture_marker
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

## 4. Clear the session's capture marker

Only after a successful `save_lesson` call: call
`mcp__hindsight__clear_capture_marker` with the `session_id` you were
given in your dispatch prompt. This is what stops a later `Stop` in the
same session from re-emitting the capture nudge for an incident that's
now already saved.

(Earlier versions of this agent deleted the marker themselves via the
`Bash` tool. That didn't reliably work: `${CLAUDE_PLUGIN_DATA}` is only
exported to hook processes and MCP/LSP server subprocesses, not to a
`Bash`-tool invocation made during a normal agent turn, so the variable
expanded to empty and the `rm -f` silently no-op'd. `clear_capture_marker`
runs inside the `hindsight` MCP server instead, which does reliably see
`${CLAUDE_PLUGIN_DATA}` -- so this tool call, not a shell command, is now
the only way this agent clears the marker.)

The tool returns `{"cleared": true}` if a marker existed and was
deleted, `{"cleared": false}` if none existed for this `session_id` --
neither is an error. If the call itself fails (tool error), don't treat
that as a hard failure of your overall task -- the lesson is already
saved by this point, which is the part that matters. Just note in your
final response that marker cleanup didn't happen, so whoever's watching
knows a `Stop` event later in this same session may nudge about this
incident again even though it's already captured (harmless redundancy,
not a correctness problem -- the same marker is what lets an
*unresolved* session's later `Stop` still trigger capture once it IS
resolved, so this hook family is intentionally biased toward a spurious
extra nudge over a silently dropped one).

## 5. Final response

Report plainly: whether a lesson was saved (and its `id`/`path` if so),
whether the marker was cleared, and anything you declined to do and why
(step 1's resolved-error check, step 2's fabrication guard, or a
`save_lesson` failure). Keep it short -- this is a background capture
step, not a report the user needs to read closely.
```

## skills/hindsight/SKILL.md
```
---
name: hindsight
description: Use when the user wants to save, search, list, delete, or reindex debugging lessons stored by the hindsight plugin, or types /hindsight. Subcommands - save, search <query>, list, prune <id>, reindex.
---

# Hindsight

Manual interface to the `hindsight` MCP server's lesson store: save a
hard-won debugging fix, search past lessons before re-debugging something,
list everything saved, prune a lesson that's stale or wrong, or force a
full rebuild of the local search index.

This skill calls the `hindsight` MCP server's tools directly (exposed to
you as `mcp__hindsight__search_lessons`, `mcp__hindsight__save_lesson`,
`mcp__hindsight__list_lessons`, `mcp__hindsight__prune_lesson`,
`mcp__hindsight__reindex_lessons` — the `mcp__<server>__<tool>` naming
Claude Code gives every MCP tool). If a tool call fails because the
server isn't connected, tell the user the `hindsight` MCP server isn't
running rather than guessing at its output.

Invoked as `/hindsight <subcommand> [args]`. Read the first word after
`/hindsight` as the subcommand and follow the matching section below. If
there's no subcommand, or it doesn't match one of the five below, show
this usage summary instead of guessing intent:

```
/hindsight save            - save a new debugging lesson
/hindsight search <query>  - search saved lessons
/hindsight list             - list every saved lesson
/hindsight prune <id>       - delete a saved lesson by id
/hindsight reindex          - force a full rebuild of the search index
```

## `/hindsight save`

Walk the user through providing the fields `save_lesson` needs, then call
it. Don't demand every field up front in one wall of questions — if the
conversation already contains a resolved debugging session (an error the
user and you just fixed together), draft field values from that context
first and show the draft to the user for correction rather than
re-asking for things you already know.

Fields (exact names/types `save_lesson` takes):

- `title` (str, required) — short human-readable summary.
- `domain` (list[str], required) — e.g. `["react", "javascript"]`.
- `error_signature` (str, required) — the distinguishing error
  message/code, e.g. `"Warning: Maximum update depth exceeded"`.
- `symptom` (str, required) — what was observed, in prose.
- `failed_approaches` (list[str], required) — things that were tried and
  did NOT fix it (may be an empty list if nothing was tried first, but
  ask before assuming that).
- `root_cause` (str, required) — the actual underlying cause.
- `fix` (str, required) — what actually fixed it.
- `confidence` (`"confirmed"` or `"probable"`, optional, defaults to
  `"probable"`) — `"confirmed"` only if the fix has been verified to
  actually resolve the issue (e.g. tests pass, error stopped
  recurring); otherwise leave it as `"probable"`.

Never invent field content the user hasn't confirmed, and never include
secrets/tokens/credentials in what you send — the server scrubs common
secret patterns before writing to disk as a safety net, but don't rely on
it as the first line of defense; ask the user to redact anything
sensitive from free-text fields yourself first.

Call `mcp__hindsight__save_lesson` with the confirmed fields. On success
it returns `{id, path, wrote: true, warnings?}` — report the `id` and
`path` to the user, and surface any `warnings` verbatim (they mean some
*other* saved lesson failed to index and is currently unsearchable, worth
flagging even though this save itself succeeded).

## `/hindsight search <query>`

Everything after `search` is the query text — pass it as-is to
`mcp__hindsight__search_lessons` (default `k=3`; only override `k` if the
user explicitly asks for more/fewer results). If the query is empty, ask
the user what to search for instead of calling the tool with nothing.

Each result is `{id, title, score, failed_approaches, root_cause, fix,
path}`. Print every result with its score, most relevant first (the tool
already sorts descending), e.g.:

```
1. [0.87] react-useeffect-infinite-loop — React useEffect infinite render loop
   Root cause: ...
   Fix: ...
   Failed approaches: ...
   (id: 2026-06-02-react-useeffect-infinite-loop)
```

If the tool returns `[]`, say plainly that no saved lesson cleared the
relevance threshold for this query — don't pad the response with a
low-confidence guess dressed up as a match.

## `/hindsight list`

Call `mcp__hindsight__list_lessons` (no arguments) and print every saved
lesson compactly — id, title, confidence, and created_at date are enough
for a scan; don't dump every field of every lesson unless the user asks
for detail on a specific one. If the list is empty, say so plainly (no
lessons saved yet).

## `/hindsight prune <id>`

Everything after `prune` is the id to delete (the `id` field from a
`search`/`list` result, also the `.md` filename's stem). If no id was
given, ask for one — suggest running `/hindsight list` first if the user
isn't sure which id they want.

This is destructive and not undoable from inside this skill, so confirm
before deleting: show the id (and its title, if you already have it from
a prior `list`/`search` in this conversation — call
`mcp__hindsight__list_lessons` yourself first if you don't) and ask the
user to confirm before calling the tool.

Once confirmed, call `mcp__hindsight__prune_lesson` with that id. It
returns `{"deleted": true}` or `{"deleted": false}`. Report which one
happened — `false` means no saved lesson had that id (not an error; it
may already have been pruned, or the id was mistyped).

## `/hindsight reindex`

Takes no arguments. Call `mcp__hindsight__reindex_lessons` with no
arguments — it always does a full rebuild of the local search index from
every lesson `.md` file currently on disk (never incremental), so this is
safe to run any time, not just when something looks broken.

Useful mainly after `git pull`/`git merge` brings in lesson files a
teammate committed on another machine: those files land on disk
immediately, but this machine's local search index (a rebuildable cache,
not committed to git) doesn't know about them until something rebuilds
it. `search_lessons` only rebuilds automatically when its index is
entirely missing, not when it's merely out of date — so newly-pulled
lessons can silently fail to show up in search until a manual reindex.
If a search that should obviously match something recently pulled
returns nothing or feels stale, suggest `/hindsight reindex` before
concluding no lesson exists.

It returns `{"indexed": <N>, "skipped": [...], "lessons_dir": <path>,
"index_path": <path>}`. Report the `indexed` count plainly (e.g.
"Reindexed 12 lessons"). If `skipped` is non-empty, surface it — each
entry is a lesson file that failed to parse and is currently excluded
from search; that's worth flagging even though the reindex itself
succeeded for every other lesson.

(A separate standalone CLI, `server/reindex.py`, also exists for
reindexing outside a live Claude Code session — e.g. CI, or a
maintainer's own terminal. This subcommand does not shell out to it: it
calls the MCP tool directly, since `${CLAUDE_PLUGIN_DATA}` — the real
index-cache location — is only reliably available inside the MCP server
process itself, not to a command run via the `Bash` tool. See
`server/reindex.py`'s own module docstring for the full reasoning.)
```

## templates/LESSON_TEMPLATE.md
```
---
id: "<id>"
title: "<title>"
domain:
  - "<domain-1>"
  - "<domain-2>"
error_signature: "<error_signature>"
created_at: "<created_at>"
confidence: <confirmed|probable>
---

## Symptom

<What was observed — the visible symptom, not yet diagnosed. Plain
prose, no raw stack traces with file paths/line numbers.>

## Approaches that FAILED (do not repeat)

- <An approach that was tried and did NOT fix the problem, and why>
- <Another failed approach, if any>

## Root cause

<The actual underlying cause, once identified.>

## Fix

<The change that resolved it.>

## Tags for retrieval

- <short retrieval tag>
- <short retrieval tag>
```

## server/schema.py
```
"""Lesson schema: the data model for a saved debugging lesson.

Defines the `Lesson` dataclass and its `render()` method, which produces
a markdown document with YAML frontmatter matching the shape of
`templates/LESSON_TEMPLATE.md` at the repo root.

Field list matches the plan's Global Constraints verbatim:

    Lesson schema: YAML frontmatter (`id`, `title`, `domain[]`,
    `error_signature`, `created_at`, `confidence: confirmed|probable`) +
    markdown body sections `## Symptom`, `## Approaches that FAILED (do
    not repeat)`, `## Root cause`, `## Fix`, `## Tags for retrieval`.
    Match text built from `title` + `error_signature` + `domain` +
    retrieval tags — never raw stack traces with file paths/line
    numbers.

No MCP dependency. Pure logic, unit-testable standalone (see
server/tests/test_schema.py). `server/main.py` is not touched by this
module or by this task.

Also defines `parse_lesson()`, the inverse of `Lesson.render()` (added in
Task 3, gap found after Task 2 landed — Task 3's `index.build_index` and
Task 4's `store.read_lesson` both need to turn a saved lesson `.md` file
back into a `Lesson`). `parse_lesson()` uses PyYAML (`yaml.safe_load`) to
parse the frontmatter block, even though `render()` above hand-emits it:
emission is a small, fully-controlled, deterministic shape (six known
scalar/list-of-scalar keys) so hand-rolling it avoided a dependency this
module otherwise wouldn't need; *parsing* has to handle arbitrary
double-quoted-scalar YAML escaping correctly (the exact
backslash/quote/newline/control-char rules `_yaml_quote()` documents
above) and reimplementing a YAML unescaper by hand would just be a worse,
untested copy of what PyYAML already does correctly — so parsing takes
the dependency PyYAML gives for free instead. (PyYAML was already an
indirect dependency of this project's `mcp` package and used directly by
this module's own tests since Task 2; Task 3 adds it as a direct,
explicitly pinned dependency in `server/requirements.txt` since
production code — not just tests — now imports it.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import yaml

CONFIDENCE_VALUES = ("confirmed", "probable")

# Frontmatter keys, in the exact order they are emitted by render().
REQUIRED_FRONTMATTER_FIELDS = (
    "id",
    "title",
    "domain",
    "error_signature",
    "created_at",
    "confidence",
)

# Body section headers, in the exact order they are emitted by render().
BODY_SECTION_HEADERS = (
    "## Symptom",
    "## Approaches that FAILED (do not repeat)",
    "## Root cause",
    "## Fix",
    "## Tags for retrieval",
)


# Characters with a short, named YAML double-quoted-scalar escape.
# Newline/carriage-return matter most: a *raw* (unescaped) "\n" or "\r"
# inside a double-quoted scalar is not rejected by YAML — it parses, but
# the YAML line-folding rule silently collapses it (and any surrounding
# line breaks) to a single space, changing the string's content on
# round-trip through a real parser. Escaping them as the two-character
# sequences below keeps them literal.
_YAML_NAMED_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\0": "\\0",
}

# NEL (U+0085) is, per the YAML spec, a line-break character just like
# \n/\r — a raw NEL folds to a space exactly like a raw \n does, so it
# needs the same treatment. It has no short named escape, so it goes
# through the `\xHH` fallback below alongside the other C0 controls.
_YAML_NEL = "\x85"


def _yaml_quote(value: str) -> str:
    """Double-quote a scalar for safe inclusion in hand-emitted YAML.

    Lesson text (titles, error signatures) is free-form and may contain
    any character a user's title or error message can contain: colons,
    `#`, quotes, embedded newlines, or other control characters. This
    escapes, in a double-quoted scalar, everything that isn't safe to
    emit literally: backslashes and double quotes (so the quoting itself
    stays well-formed), newline/carriage-return/NEL (which YAML's
    line-folding rule would otherwise silently collapse to a space on
    reload — see `_YAML_NAMED_ESCAPES`/`_YAML_NEL`), and every other C0
    control character plus DEL (0x00-0x1F, 0x7F) via `\\xHH`, since a raw
    control character other than tab is rejected outright by a
    spec-compliant YAML parser. Verified (see
    server/tests/test_schema.py) to round-trip byte-for-byte through
    PyYAML's `yaml.safe_load` for arbitrary `str` input, including
    embedded newlines/CR/tabs/NUL/DEL/NEL. Frontmatter here is flat (six
    scalar/list-of-scalar fields) so hand-emitting it deterministically
    avoids taking a PyYAML dependency this module otherwise wouldn't need
    (PyYAML is only used by tests, to verify against a real parser).
    """
    chars = []
    for ch in value:
        if ch in _YAML_NAMED_ESCAPES:
            chars.append(_YAML_NAMED_ESCAPES[ch])
        elif ch == _YAML_NEL or ord(ch) < 0x20 or ord(ch) == 0x7F:
            chars.append(f"\\x{ord(ch):02x}")
        else:
            chars.append(ch)
    return f'"{"".join(chars)}"'


def _yaml_list(items: list[str]) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {_yaml_quote(item)}" for item in items)


@dataclass
class Lesson:
    """A single debugging lesson.

    Frontmatter fields: id, title, domain, error_signature, created_at,
    confidence.
    Body fields: symptom, failed_approaches, root_cause, fix, tags (the
    "Tags for retrieval" section).
    """

    id: str
    title: str
    domain: list[str]
    error_signature: str
    created_at: str
    confidence: Literal["confirmed", "probable"]
    symptom: str
    failed_approaches: list[str]
    root_cause: str
    fix: str
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_VALUES:
            raise ValueError(
                f"confidence must be one of {CONFIDENCE_VALUES!r}, "
                f"got {self.confidence!r}"
            )
        if not self.id:
            raise ValueError("id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.domain:
            raise ValueError("domain must be a non-empty list")
        if not self.error_signature:
            raise ValueError("error_signature is required")
        if not self.created_at:
            raise ValueError("created_at is required")

    def render(self) -> str:
        """Render this lesson as a markdown document with YAML
        frontmatter, matching the shape of templates/LESSON_TEMPLATE.md.
        """
        frontmatter = (
            "---\n"
            f"id: {_yaml_quote(self.id)}\n"
            f"title: {_yaml_quote(self.title)}\n"
            f"domain:{_yaml_list(self.domain)}\n"
            f"error_signature: {_yaml_quote(self.error_signature)}\n"
            f"created_at: {_yaml_quote(self.created_at)}\n"
            f"confidence: {self.confidence}\n"
            "---\n"
        )

        failed_approaches_block = (
            "\n".join(f"- {item}" for item in self.failed_approaches)
            if self.failed_approaches
            else "_(none recorded)_"
        )
        tags_block = (
            "\n".join(f"- {item}" for item in self.tags)
            if self.tags
            else "_(none recorded)_"
        )

        body = (
            "\n"
            "## Symptom\n\n"
            f"{self.symptom}\n\n"
            "## Approaches that FAILED (do not repeat)\n\n"
            f"{failed_approaches_block}\n\n"
            "## Root cause\n\n"
            f"{self.root_cause}\n\n"
            "## Fix\n\n"
            f"{self.fix}\n\n"
            "## Tags for retrieval\n\n"
            f"{tags_block}\n"
        )

        return frontmatter + body

    def match_text(self) -> str:
        """Text used for embedding/similarity search (Task 3), per
        Global Constraints: "Match text built from title +
        error_signature + domain + retrieval tags — never raw stack
        traces with file paths/line numbers."
        """
        parts = [self.title, self.error_signature, *self.domain, *self.tags]
        return " ".join(p for p in parts if p)


# --- parse_lesson(): the inverse of render() -------------------------------

# Matches the leading "---\n...\n---\n" frontmatter block render() always
# emits first. DOTALL so "." spans the embedded newlines a quoted scalar
# may legitimately contain (those are escaped as literal "\n" two-char
# sequences by _yaml_quote(), never as a raw newline, so they don't
# prematurely end this match — see _yaml_quote()'s docstring above).
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)

# Sentinel render() emits for an empty failed_approaches/tags list.
_EMPTY_LIST_SENTINEL = "_(none recorded)_"


def _parse_body_sections(body_text: str) -> dict[str, str]:
    """Split render()'s body text into {header: content} using the exact
    header set/order in BODY_SECTION_HEADERS.

    Each section's content is whatever sits between one header and the
    next (or end-of-text for the last section), with surrounding blank
    lines stripped. Header matching is anchored to a full line (`^header$`
    with `re.MULTILINE`), not a plain substring search: render() always
    emits each header occupying its own line, so a real header is always
    line-anchored. Anchoring this way means a body section's own free
    text that merely *contains* another section's exact header string as
    part of a sentence (e.g. "...references the \"## Fix\" section
    below...") is correctly left alone — a bare `str.find()` substring
    search would misfire on that and silently truncate the section (see
    the regression tests for this exact scenario in
    server/tests/test_schema.py). A body section's free text that
    contains another header string *as a standalone line by itself* would
    still be ambiguous with a real header and is not handled here — real
    lesson prose doesn't emit bare `## Something` lines outside of
    render()'s own headers.
    """
    positions: list[tuple[int, str, int]] = []
    for header in BODY_SECTION_HEADERS:
        match = re.search(rf"^{re.escape(header)}$", body_text, re.MULTILINE)
        if match is None:
            raise ValueError(
                f"lesson body is missing the required section header {header!r}"
            )
        positions.append((match.start(), header, match.end()))

    positions.sort(key=lambda triple: triple[0])
    if [header for _, header, _ in positions] != list(BODY_SECTION_HEADERS):
        raise ValueError(
            "lesson body section headers are present but out of order; "
            f"expected {list(BODY_SECTION_HEADERS)}"
        )

    sections: dict[str, str] = {}
    for i, (_, header, end) in enumerate(positions):
        content_start = end
        content_end = positions[i + 1][0] if i + 1 < len(positions) else len(body_text)
        sections[header] = body_text[content_start:content_end].strip("\n")
    return sections


def _parse_list_section(content: str, *, section_name: str) -> list[str]:
    """Invert render()'s `"\\n".join(f"- {item}" for item in items)` (or
    the `_(none recorded)_` sentinel for an empty list).
    """
    content = content.strip("\n")
    if content.strip() == _EMPTY_LIST_SENTINEL:
        return []
    items = []
    for line in content.split("\n"):
        if not line.startswith("- "):
            raise ValueError(
                f"malformed {section_name!r} list line (expected '- ' prefix): "
                f"{line!r}"
            )
        items.append(line[2:])
    return items


def parse_lesson(text: str) -> Lesson:
    """Parse a rendered lesson document (as produced by `Lesson.render()`)
    back into a `Lesson`. The inverse of `render()`.

    Frontmatter is parsed with `yaml.safe_load` (a real YAML parser, not
    a hand-rolled unescaper — see module docstring for why) so it
    correctly recovers every character `_yaml_quote()` can escape,
    including embedded newlines/CR/tabs/control characters in `title`,
    `error_signature`, `created_at`, `id`, or any `domain` item. Body
    sections are parsed positionally (see `_parse_body_sections`).

    Raises `ValueError` if the frontmatter block or any required section
    is missing/malformed. Round-trips exactly for any `Lesson` produced
    via its own constructor and rendered via `render()`:
    `parse_lesson(lesson.render()) == lesson`.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(
            "lesson text does not start with a '---'-delimited YAML "
            "frontmatter block"
        )
    frontmatter_text = match.group(1)
    body_text = text[match.end() :]

    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise ValueError("lesson frontmatter did not parse to a YAML mapping")

    missing = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in frontmatter]
    if missing:
        raise ValueError(f"lesson frontmatter missing required field(s): {missing}")

    sections = _parse_body_sections(body_text)

    return Lesson(
        id=str(frontmatter["id"]),
        title=str(frontmatter["title"]),
        domain=list(frontmatter["domain"]),
        error_signature=str(frontmatter["error_signature"]),
        created_at=str(frontmatter["created_at"]),
        confidence=frontmatter["confidence"],
        symptom=sections["## Symptom"],
        failed_approaches=_parse_list_section(
            sections["## Approaches that FAILED (do not repeat)"],
            section_name="## Approaches that FAILED (do not repeat)",
        ),
        root_cause=sections["## Root cause"],
        fix=sections["## Fix"],
        tags=_parse_list_section(
            sections["## Tags for retrieval"], section_name="## Tags for retrieval"
        ),
    )
```

## server/scrub.py
```
"""Secret scrubber: redacts credentials and high-entropy tokens from
free-text before it is ever written to disk.

Global Constraints (binding, copied verbatim from the plan):

    Secrets never written: regex pass (AWS keys, bearer tokens, `sk-`
    style keys, connection strings, private key blocks, long
    high-entropy strings) must run before anything touches disk (that
    wiring happens in a later task — this task just builds the scrubber
    function itself and proves it works standalone).

This module has no MCP dependency and does not touch `server/main.py` —
wiring `scrub`/`scrub_payload` into `save_lesson`'s write path is Task 4.

Redaction is always in place: only the offending token/block is replaced
with the `[REDACTED]` marker; the surrounding sentence is never dropped.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

REDACTED = "[REDACTED]"

# --- Specific, low-false-positive patterns --------------------------------

# AWS access key IDs: fixed, well-known prefixes (also covers STS
# temporary session keys under ASIA).
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")

# AWS secret access keys have no distinguishing prefix — just 40
# base64-alphabet characters — so matching them standalone anywhere in
# text is too false-positive-prone (a 40-char base64 blob could be
# almost anything). Real-world secret scanners key off the surrounding
# variable name; this does the same: a recognizable "secret key"
# identifier followed by `:`/`=` and a quoted-or-bare 40-char value.
# Group 3 (the optional quote) is backreferenced as the closing
# delimiter so surrounding quote characters, if present, survive
# redaction instead of being dropped.
_AWS_SECRET_KEY_RE = re.compile(
    r"(?i)\b(aws_secret_access_key|aws_secret_key|secret_access_key)"
    r"(\s*[:=]\s*)"
    r"([\"']?)[A-Za-z0-9/+=]{40}\3"
)

# Generic bearer tokens: `Bearer <token>` (Authorization headers, etc).
# Redact only the token; keep the scheme word for context.
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{10,}")

# `sk-`-prefixed API keys (OpenAI-style and similar). Negative lookbehind
# stops this from matching as a substring of some longer unrelated token.
_SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{16,}\b")

# DB connection strings with embedded credentials:
# scheme://user:pass@host[:port]/db
_DB_CONN_RE = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)"
    r"://[^\s'\"]+:[^\s'\"@]+@[^\s'\"]+"
)

# PEM-style private key blocks (RSA/EC/DSA/OpenSSH/generic). Redact the
# entire block, including the BEGIN/END markers.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Hex-encoded secrets explicitly labeled with a secret-shaped variable
# name (`api_key`, `SECRET_KEY`, `auth_token`, ...) at a canonical
# digest/SHA length (32 = MD5, 40 = SHA-1/git commit, 64 = SHA-256/Docker
# image ID). Handled as its own dedicated, context-aware pattern here —
# mirroring `_AWS_SECRET_KEY_RE` above, which keys off a variable name
# rather than the value's own randomness — instead of being folded into
# the generic high-entropy catch-all below, because entropy alone can't
# distinguish a labeled hex secret from an incidental SHA/checksum
# reference: hex's 16-symbol alphabet makes near-max entropy the
# *normal* case for any hex string, not a secrecy signal. An *unlabeled*
# hex value at these lengths is assumed to be a checksum/SHA/image-id in
# ordinary technical prose and is deliberately left alone (see the
# `_HEX_CHARS` handling in `_looks_like_secret` below) — this pattern
# only fires when a recognizable identifier is directly attached via
# `:`/`=`, same as the AWS pattern's own scope.
#
# Capture groups: (1) identifier, (2) separator incl. surrounding
# whitespace, (3) optional opening quote, (4) the hex value. Group 3 is
# backreferenced as the closing delimiter so a quoted value keeps
# matching quotes (or an unquoted value keeps none) — this also means,
# unlike `_AWS_SECRET_KEY_RE`, surrounding quote characters survive
# redaction instead of being silently dropped.
_LABELED_HEX_SECRET_RE = re.compile(
    r"(?i)\b([A-Za-z][A-Za-z0-9_]*)(\s*[:=]\s*)([\"']?)"
    r"([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})"
    r"(?![0-9a-fA-F])\3"
)

# Substrings that make an identifier "secret-shaped" for
# `_LABELED_HEX_SECRET_RE`. Deliberately substring (not whole-word)
# matching so `api_key`, `SECRET_KEY`, `aws_secret_access_key` all count
# as labeled — the tradeoff is that an unrelated identifier merely
# containing one of these as a substring (e.g. `monkey`) would also
# count; for a secret scrubber, over-redacting on an ambiguous label is
# the safe failure direction.
_HEX_SECRET_LABEL_KEYWORDS = ("secret", "key", "token", "password", "credential")


def _redact_labeled_hex_secret(m: re.Match[str]) -> str:
    identifier, sep, quote = m.group(1), m.group(2), m.group(3)
    if any(kw in identifier.lower() for kw in _HEX_SECRET_LABEL_KEYWORDS):
        return f"{identifier}{sep}{quote}{REDACTED}{quote}"
    return m.group(0)


# --- Generic high-entropy token catch-all ---------------------------------

# Candidate runs of secret-alphabet characters, >=32 chars long.
# Deliberately excludes `/` and whitespace so ordinary filesystem paths
# and URLs (exactly the "ordinary technical prose" this scrubber must
# leave alone) don't get swept into one long token.
_TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+_=\-]{32,}")

# Threshold tuned empirically (see server/tests/test_scrub.py) to flag
# randomized alphanumeric tokens (API keys, generated secrets) while
# passing plain-English kebab/snake-case identifiers and hex-ish IDs that
# lack digit+letter variety.
_ENTROPY_THRESHOLD_BITS_PER_CHAR = 3.5

# Pure hex-alphabet strings (0-9, a-f, A-F) at a canonical digest/SHA
# length (`_HEX_DIGEST_LENGTHS` — same three lengths as
# `_LABELED_HEX_SECRET_RE` above) are excluded from the entropy
# threshold: hex's 16-symbol alphabet makes near-max entropy
# (log2(16) = 4 bits/char) the *normal* case for any hex string of these
# lengths — git commit SHAs, Docker image IDs, MD5/SHA checksums in
# ordinary technical prose — not a signal of randomness/secrecy the way
# it is for a wider alphabet, so entropy alone can't tell one from a hex
# secret. This is safe to do *unconditionally* here (no context check
# needed at this point) because `_LABELED_HEX_SECRET_RE` already ran
# earlier in `scrub()` and redacted every *labeled* hex secret at these
# lengths — see that pattern's docstring for the labeled/unlabeled
# split. Hex strings at *other* lengths have no such length-based signal
# and fall through to the plain entropy check like any other candidate
# token (this deliberately narrows the exclusion relative to a blanket
# "all pure hex" rule, which would also suppress a real hex secret that
# happens to land on a non-canonical length).
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")
_HEX_DIGEST_LENGTHS = frozenset({32, 40, 64})


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _looks_like_secret(token: str) -> bool:
    """Heuristic for a "long high-entropy token" per Global Constraints.

    Requires a mix of letters and digits (this rules out plain
    hyphenated slugs, lowercase words, and pure numeric IDs — all common
    in ordinary technical prose), excludes pure hex strings at canonical
    digest/SHA lengths (git SHAs, checksums, image IDs — see
    `_HEX_DIGEST_LENGTHS`; a *labeled* hex secret at these lengths was
    already redacted earlier by `_LABELED_HEX_SECRET_RE`, so anything
    reaching this function is presumed unlabeled), AND requires Shannon
    entropy above a threshold tuned to flag randomized alphanumeric
    tokens.
    """
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    if not (has_digit and has_alpha):
        return False
    if len(token) in _HEX_DIGEST_LENGTHS and all(c in _HEX_CHARS for c in token):
        return False
    return _shannon_entropy(token) >= _ENTROPY_THRESHOLD_BITS_PER_CHAR


def scrub(text: str) -> str:
    """Redact secrets from `text`, returning the scrubbed string.

    Redacts, in order: PEM private key blocks, DB connection strings,
    AWS access key IDs, AWS secret access keys, bearer tokens, `sk-`
    API keys, labeled hex secrets (e.g. `api_key: <hex>`), and any
    remaining long high-entropy token. Redaction is always in place —
    only the offending token/block becomes `[REDACTED]`; the rest of the
    sentence/line is left untouched.
    """
    if not text:
        return text

    result = _PRIVATE_KEY_RE.sub(REDACTED, text)
    result = _DB_CONN_RE.sub(REDACTED, result)
    result = _AWS_ACCESS_KEY_RE.sub(REDACTED, result)
    result = _AWS_SECRET_KEY_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}",
        result,
    )
    result = _BEARER_TOKEN_RE.sub("Bearer " + REDACTED, result)
    result = _SK_KEY_RE.sub(REDACTED, result)
    result = _LABELED_HEX_SECRET_RE.sub(_redact_labeled_hex_secret, result)
    result = _TOKEN_CANDIDATE_RE.sub(
        lambda m: REDACTED if _looks_like_secret(m.group(0)) else m.group(0),
        result,
    )
    return result


def scrub_payload(payload: Any) -> Any:
    """Recursively scrub every string value in a dict/list payload.

    Convenience wrapper anticipated by the brief ("scrub a whole payload
    dict") for the eventual `save_lesson` write path (wired up in Task
    4) — scrubs an entire tool-call payload, not just a single string.
    Non-string leaves (numbers, bools, None) pass through unchanged.
    """
    if isinstance(payload, str):
        return scrub(payload)
    if isinstance(payload, dict):
        return {k: scrub_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [scrub_payload(v) for v in payload]
    return payload
```

## server/index.py
```
"""Local embedding index for lesson similarity search.

Wraps `fastembed`'s local (no-network-at-query-time, no-API-key) ONNX
embedding model to build and query a similarity index over saved
debugging lessons, per the plan's Global Constraints:

    Local embeddings: fastembed, model BAAI/bge-small-en-v1.5 (384-dim).
    Pin this exact model string everywhere it's referenced so every
    teammate's index is byte-compatible.

    Index cache: ${CLAUDE_PLUGIN_DATA} (rebuildable from the markdown
    lessons at any time — never treat it as source of truth).

    search_lessons(query, k=3) -> ..., empty list if nothing clears the
    similarity threshold (never return a weak match dressed as strong).

This module takes `cache_dir: Path` as a plain parameter rather than
reading `${CLAUDE_PLUGIN_DATA}` itself — resolving that env var into a
real path is Task 4's MCP-wiring job (this task has no MCP dependency and
does not touch server/main.py).

Index format: a single JSON file (`index.json`) under `cache_dir`
containing `{model, dim, records: [{id, path, vector}, ...], skipped:
[{path, error}, ...]}`. Every field in a record is either present in, or
trivially recomputed from, the lesson `.md` files themselves (`id` and
`vector` come from parsing + embedding a lesson's `match_text()`; `path`
is just the file's location) — nothing lives only in the index.
`skipped` lists any `.md` file under `lessons_dir` that failed to read or
parse during the most recent `build_index` call (see `build_index`'s
docstring) — empty in the common case where every lesson file parses
cleanly. `build_index` always does a full rebuild by re-reading every
`.md` file in `lessons_dir` from scratch, so a corrupted or deleted
`index.json` is always fully recoverable by
calling `build_index` again; the cache is never treated as authoritative.

No MCP dependency. Pure logic (network access is needed only once, on
first use, for fastembed to download and locally cache the ONNX model
weights — after that, embedding is fully local). `server/main.py` is not
touched by this module or by this task.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding

from schema import parse_lesson

logger = logging.getLogger(__name__)

# Pinned exact model string — must match everywhere it's referenced
# (Global Constraints) so every teammate's index is byte-compatible.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

INDEX_FILENAME = "index.json"

# Default cosine-similarity floor for search(). Empirically calibrated
# (see server/tests/test_index.py and the Task 3 report) against
# bge-small-en-v1.5's actual score distribution on this plugin's fixture
# lessons: a query closely matching a lesson's title/error_signature/tags
# scores ~0.80-0.91 against that lesson; genuinely unrelated queries
# (different domain entirely) top out around ~0.42-0.45 against every
# lesson; queries that only loosely share a domain word without matching
# the actual incident sit in a ~0.53-0.62 middle band. 0.55 sits with
# real margin above the unrelated ceiling (never returns a weak match
# dressed as strong) and well below genuine matches, while also
# filtering out shallow same-domain-word-only noise. The plan explicitly
# flags this as "tuned empirically in Task 8's matching tests" — this is
# a documented, evidence-based starting point, not a final calibration.
DEFAULT_THRESHOLD = 0.55

# Lazily constructed and cached at module scope: loading the ONNX model
# (and, on first-ever use on a machine, downloading its weights) is
# expensive enough that every embed() call must not repeat it.
_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    """Embed a single string into the model's 384-dim vector space.

    Returns a plain `list[float]` (not a numpy array) so callers/tests
    don't need a numpy dependency and the vector round-trips cleanly
    through JSON.
    """
    model = _get_model()
    (vector,) = model.embed([text])
    return [float(x) for x in vector]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_index(lessons_dir: Path, cache_dir: Path) -> Path:
    """Read every lesson markdown file under `lessons_dir`, embed each
    lesson's `match_text()` (title + error_signature + domain + retrieval
    tags — never raw stack traces, per Global Constraints and
    `Lesson.match_text()`), and write a flat vector file to `cache_dir`.

    Always a full rebuild from scratch (reads every `.md` file fresh;
    does not attempt to diff against a prior index), matching "Index
    format must be fully rebuildable from the markdown lessons alone —
    never treat the cache as authoritative." `lessons_dir` not existing
    yet is not an error — it just means an empty index (no lessons saved
    yet).

    A lesson file that fails to read or parse (malformed frontmatter,
    missing body section, invalid YAML, a future bug in `parse_lesson`,
    etc.) is skipped rather than aborting the entire build: one corrupt
    `.md` file must never disable search over every other, valid lesson.
    Each skip is logged (`logging.warning`, module logger `server.index`)
    and also collected into a `"skipped": [{"path", "error"}, ...]` list
    written alongside `"records"` in `index.json`, so a caller can inspect
    what was skipped and why without needing a separate return value —
    `build_index` still returns just the index path, keeping its existing
    call signature/return type for current callers (this module's own
    `search()`, this task's tests, and Task 4's planned usage). The catch
    is intentionally broad (`Exception`, not just `ValueError`): malformed
    YAML syntax raises `yaml.YAMLError` (a different hierarchy than the
    `ValueError` `parse_lesson` raises for structurally-valid-YAML-but-
    semantically-incomplete lessons), and an interrupted write or manual
    edit can produce input that fails in other ways too (e.g. a
    non-UTF-8-decodable file raising `UnicodeDecodeError` from
    `read_text`) — all of those are "this one file is bad," not "the
    whole index build should abort." Only the per-file read+parse step is
    covered by this catch; `embed()` failures (an infra/model problem,
    not a data-quality problem) are still allowed to propagate.

    Returns the path to the written index file.
    """
    lessons_dir = Path(lessons_dir)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if lessons_dir.exists():
        for lesson_path in sorted(lessons_dir.glob("*.md")):
            try:
                text = lesson_path.read_text(encoding="utf-8")
                lesson = parse_lesson(text)
            except Exception as exc:
                logger.warning(
                    "build_index: skipping unparseable lesson file %s: %s: %s",
                    lesson_path,
                    type(exc).__name__,
                    exc,
                )
                skipped.append(
                    {
                        "path": str(lesson_path),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            vector = embed(lesson.match_text())
            records.append(
                {
                    "id": lesson.id,
                    "path": str(lesson_path),
                    "vector": vector,
                }
            )

    index_path = cache_dir / INDEX_FILENAME
    index_path.write_text(
        json.dumps(
            {
                "model": MODEL_NAME,
                "dim": EMBEDDING_DIM,
                "records": records,
                "skipped": skipped,
            }
        ),
        encoding="utf-8",
    )
    return index_path


def search(
    query: str,
    cache_dir: Path,
    k: int = 3,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Embed `query`, cosine-similarity it against the cached vectors in
    `cache_dir`, and return the top-`k` records that clear `threshold`,
    sorted descending by score.

    Returns `[]` if the index doesn't exist yet, is empty, or nothing
    clears `threshold` — never a weak match dressed as strong (Global
    Constraints).

    Each returned dict is `{id, path, score}`; callers that need the full
    lesson content (title, failed_approaches, root_cause, fix, ...) parse
    the file at `path` via `schema.parse_lesson` — Task 4's `search_lessons`
    tool wiring does that to build the final `{id, title, score,
    failed_approaches, root_cause, fix, path}` shape from Global
    Constraints; this module only owns similarity ranking.
    """
    cache_dir = Path(cache_dir)
    index_path = cache_dir / INDEX_FILENAME
    if not index_path.exists():
        return []

    data = json.loads(index_path.read_text(encoding="utf-8"))
    records = data.get("records", [])
    if not records:
        return []

    query_vector = embed(query)
    scored = [
        {
            "id": record["id"],
            "path": record["path"],
            "score": _cosine_similarity(query_vector, record["vector"]),
        }
        for record in records
    ]
    scored = [r for r in scored if r["score"] >= threshold]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]
```

## server/store.py
```
"""Lesson storage: read/write lesson markdown files on disk.

Owns the on-disk `.debug-memory/lessons/<id>.md` file format's I/O side
(rendering a `Lesson` to text and parsing text back into a `Lesson` are
`schema.py`'s job -- this module just decides *where* a lesson lives and
reads/writes bytes there) plus the `<id>.md` filename/slug convention.

Public API (per the Task 4 brief, plus `delete_lesson` added in Task 5 for
the `prune_lesson` MCP tool -- same "this module decides where a lesson
lives and reads/writes bytes there" ownership as the rest of this file,
just the delete side of that instead of the read/write side):
    write_lesson(lesson, lessons_dir) -> Path
    read_lesson(path) -> dict
    list_lessons(lessons_dir) -> list[dict]
    delete_lesson(lesson_id, lessons_dir) -> bool  # raises ValueError on a
                                                     # path-traversal/non-bare
                                                     # lesson_id -- see its
                                                     # own docstring and
                                                     # _resolve_lesson_path

No MCP dependency and no env-var reads. `server/main.py` resolves
`${CLAUDE_PROJECT_DIR}` into a real `lessons_dir` Path (see its own
docstring for how) and passes it in here; this module never reads
`os.environ` itself, matching the pattern `index.py` already set with
`cache_dir`.

Deviation from the brief's example signature worth flagging up front:
the brief sketches `write_lesson(payload, lessons_dir)`. This takes an
already-constructed `schema.Lesson` instead of a raw payload dict --
`server/main.py`'s `save_lesson` is the one that scrubs the raw input and
builds the `Lesson` (including the auto-derived `id`/`tags`, per the
Task 4 brief's tags decision), so by the time this module is involved
there is already a fully-formed, validated `Lesson` to render and write;
building a second, parallel "dict -> Lesson" construction path here would
just duplicate what `Lesson.__init__`/`__post_init__` already do.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from schema import Lesson, parse_lesson

logger = logging.getLogger(__name__)

# Common filler words dropped when building a title-derived slug -- purely
# to keep filenames short and content-bearing (per the brief: "<id>" is a
# "slugified YYYY-MM-DD-short-slug"), not a linguistic/NLP stopword list.
_SLUG_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "is",
        "was", "with", "at", "by", "from", "this", "that",
    }
)

# Caps slug length at this many words so ids stay filename-friendly and
# match the shape of the spec's own example ids (see
# server/tests/fixtures/*.md, e.g. "2026-07-18-fastmcp-pydantic-floor" --
# 3 words; "2026-06-02-react-useeffect-infinite-loop" -- 4 words). Not a
# hard spec requirement, just a "short" judgment call.
_MAX_SLUG_WORDS = 6

_SLUG_WORD_RE = re.compile(r"[a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, ASCII-fold, drop filler words, and hyphen-join `text`
    into a short, filename-safe slug.

    E.g. "FastMCP tool registration crashes with stale pydantic" ->
    "fastmcp-tool-registration-crashes-stale" (5 content words after
    dropping "with"; capped at `_MAX_SLUG_WORDS`).

    Falls back to the un-filtered word list (or the literal string
    "lesson") if a title is made up entirely of filler words or has no
    ASCII alphanumeric characters at all -- `Lesson.title` is required
    non-empty (see `schema.Lesson.__post_init__`) but nothing stops it
    from being e.g. pure punctuation or non-ASCII, and a slug must never
    end up empty.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    all_words = _SLUG_WORD_RE.findall(ascii_text)
    words = [w for w in all_words if w not in _SLUG_STOPWORDS] or all_words or ["lesson"]
    return "-".join(words[:_MAX_SLUG_WORDS])


def make_lesson_id(title: str, created_at: str) -> str:
    """Build the `YYYY-MM-DD-short-slug` id (also the `<id>.md` filename
    stem) from a lesson's title and `created_at` timestamp, matching the
    fixture lessons' shape (server/tests/fixtures/*.md). `created_at` is
    expected to be an ISO-8601 string (`YYYY-MM-DDTHH:MM:SSZ`, what
    `server/main.py` generates); only its leading `YYYY-MM-DD` date
    portion is used.
    """
    date_part = created_at[:10]
    return f"{date_part}-{slugify(title)}"


def write_lesson(lesson: Lesson, lessons_dir: Path | str) -> Path:
    """Render `lesson` (via `Lesson.render()`) and write it to
    `lessons_dir/<id>.md`, creating `lessons_dir` (and any missing parent
    directories) if it doesn't exist yet.

    Id-collision safety: if a file already exists at
    `lessons_dir/<lesson.id>.md` (e.g. two lessons saved the same day
    with a similar-enough title to produce the same slug), a numeric
    suffix (`-2`, `-3`, ...) is appended to the id until a free filename
    is found -- this never silently overwrites a previously saved
    lesson. When the id had to be adjusted, the *written* lesson's own
    frontmatter `id:` field is updated to match (via `dataclasses.replace`,
    which re-runs `Lesson.__post_init__`'s validation harmlessly) so the
    file's own content and its filename never disagree.

    Returns the `Path` actually written to. Callers that need the final
    id should read it back from `path.stem` rather than assume it always
    equals the `lesson.id` passed in, for exactly the collision case
    above.
    """
    lessons_dir = Path(lessons_dir)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    candidate_id = lesson.id
    suffix = 2
    while (lessons_dir / f"{candidate_id}.md").exists():
        candidate_id = f"{lesson.id}-{suffix}"
        suffix += 1
    if candidate_id != lesson.id:
        lesson = replace(lesson, id=candidate_id)

    path = lessons_dir / f"{lesson.id}.md"
    path.write_text(lesson.render(), encoding="utf-8")
    return path


def read_lesson(path: Path | str) -> dict[str, Any]:
    """Read and parse a single lesson `.md` file at `path` (via
    `schema.parse_lesson` -- "the one parser", per Task 3's brief, that
    both `index.build_index` and this function use) into a plain dict of
    every `Lesson` field, plus a `path` key (string) for callers that
    need to locate the file again.
    """
    path = Path(path)
    lesson = parse_lesson(path.read_text(encoding="utf-8"))
    result = asdict(lesson)
    result["path"] = str(path)
    return result


def list_lessons(lessons_dir: Path | str) -> list[dict[str, Any]]:
    """Read every `*.md` file under `lessons_dir` (sorted by filename for
    determinism) and return each as a dict (see `read_lesson`).

    `lessons_dir` not existing yet is not an error -- returns `[]`,
    mirroring `index.build_index`'s identical treatment of a
    not-yet-created lessons directory. A file that fails to parse is
    skipped (logged via `logging.warning`, module logger
    `server.store`) rather than aborting the whole listing -- the same
    per-file error isolation `index.build_index` uses and for the same
    reason: one corrupted `.md` file must not take down `list_lessons`
    for every other valid lesson.
    """
    lessons_dir = Path(lessons_dir)
    if not lessons_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for lesson_path in sorted(lessons_dir.glob("*.md")):
        try:
            results.append(read_lesson(lesson_path))
        except Exception as exc:
            logger.warning(
                "list_lessons: skipping unparseable lesson file %s: %s: %s",
                lesson_path,
                type(exc).__name__,
                exc,
            )
    return results


def _resolve_lesson_path(lesson_id: str, lessons_dir: Path) -> Path:
    """Validate that `lesson_id` is a bare filename component and
    resolve it to `lessons_dir/<lesson_id>.md`. Raises `ValueError` on
    anything else.

    This is the security-relevant choke point closing a Task 5 review
    finding: `Path(lessons_dir) / f"{lesson_id}.md"` alone is NOT safe
    against a caller-supplied `lesson_id`, because pathlib's `/` silently
    *discards the left operand* when the right one is absolute --
    `Path("/tmp/lessons") / "/etc/passwd"` == `Path("/etc/passwd")`, not
    an error and not a path under `/tmp/lessons` -- and relative `..`
    segments inside `lesson_id` (e.g. `"../../../../tmp/evil"`) are
    followed by `Path.exists()`/`.unlink()` without normalization. Since
    `delete_lesson` is reachable directly from `server/main.py`'s
    `prune_lesson` MCP tool with a caller-supplied `id` and zero prior
    validation, either shape let a caller delete an arbitrary
    `.md`-suffixed file anywhere the server process can write, not just
    a file actually under `lessons_dir`.

    Two independent checks, because neither alone is sufficient:

      1. Name-only check: `lesson_id` must be non-empty, must equal
         `Path(lesson_id).name`, and must not be `.` or `..`. The
         equality check alone rules out absolute paths and any embedded
         `/`, but NOT a bare `".."` -- on this pathlib implementation
         `Path("..").name == ".."` (confirmed), i.e. `".."` is its own
         `.name`, so it passes the equality check and needs its own
         explicit rejection alongside `"."`.
      2. Resolved-parent check: after building the candidate path from a
         `lesson_id` that already passed check 1, `.resolve()` it and
         require its parent to be exactly `lessons_dir.resolve()`. This
         is real defense in depth, not redundant with check 1 -- it
         catches anything the string-shape check might miss (e.g. a
         symlink sitting at `lessons_dir/<id>.md` that points outside
         `lessons_dir`) rather than trusting the id's shape alone.

    Only `delete_lesson` calls this today. `write_lesson` never needs
    it: the `Lesson.id` it writes from is built internally by
    `server/main.py`'s `save_lesson` via `make_lesson_id`/`slugify`
    (this module, above), which only ever emits `[a-z0-9]` tokens
    hyphen-joined with a `YYYY-MM-DD` date prefix -- never raw external
    input, and structurally incapable of containing `/` or `..`.
    `read_lesson` never needs it either: every call site (`list_lessons`
    below, and `server/main.py`'s `search_lessons`) passes an already-
    resolved `Path` obtained by globbing `lessons_dir` or reading it back
    out of the index, never a bare id string reconstructed from caller
    input.
    """
    lessons_dir = Path(lessons_dir)
    if not lesson_id or lesson_id in (".", "..") or lesson_id != Path(lesson_id).name:
        raise ValueError(
            f"invalid lesson id {lesson_id!r}: must be a bare filename "
            "component (no path separators, not absolute, not '.' or '..')"
        )

    candidate = lessons_dir / f"{lesson_id}.md"
    if candidate.resolve().parent != lessons_dir.resolve():
        raise ValueError(
            f"invalid lesson id {lesson_id!r}: resolves outside lessons_dir"
        )
    return candidate


def delete_lesson(lesson_id: str, lessons_dir: Path | str) -> bool:
    """Delete `lessons_dir/<lesson_id>.md`, if it exists.

    Returns `True` if a file was removed, `False` if no file matched
    `lesson_id` -- including when `lessons_dir` itself doesn't exist yet
    (mirrors `list_lessons`'s treatment of a not-yet-created lessons
    directory: not an error, just nothing to do). A missing match is a
    normal, expected outcome (pruning an id that's already gone, or was
    never saved) for the caller (`server/main.py`'s `prune_lesson` tool)
    to surface as `{"deleted": false}`, not something this function
    raises on.

    Raises `ValueError` if `lesson_id` is not a bare filename component
    (see `_resolve_lesson_path`) -- e.g. an absolute path, a relative
    path containing `..`, or anything else that would let the
    constructed path escape `lessons_dir`. This is deliberately a raise,
    not a silent `False`: every id this module itself ever produces
    (`make_lesson_id`/`slugify`, above) is already a safe bare filename,
    so a `lesson_id` that fails this check cannot arise from any normal
    internal flow -- it can only arrive via a caller invoking the
    `prune_lesson` MCP tool directly with a hand-crafted malicious id.
    That is a fundamentally different situation from "no lesson has this
    id" (a normal, expected `False`), and collapsing it into `False`
    would mask a malformed/hostile-input bug as an unremarkable no-op.
    """
    lessons_dir = Path(lessons_dir)
    path = _resolve_lesson_path(lesson_id, lessons_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
```

## server/main.py
```
#!/usr/bin/env python3
"""Hindsight MCP server.

Exposes the `hindsight` tool surface (`search_lessons`, `save_lesson`,
`list_lessons`, `prune_lesson`, `clear_capture_marker`, `reindex_lessons`)
over stdio using the official MCP Python SDK's FastMCP helper.

Task 4 status: real behavior, replacing Task 1's stubs. Wires Task 2's
`schema.py`/`scrub.py` and Task 3's `index.py` together via `store.py`:
  - `save_lesson` scrubs every free-text field (`scrub.py`) before
    anything touches disk, builds a `Lesson` (`schema.py` -- with an
    auto-derived `id` and retrieval `tags`, see `_derive_tags` below),
    writes it to `.debug-memory/lessons/<id>.md` (`store.py`), rebuilds
    the local similarity index (`index.py`), best-effort `git add`s the
    new file, and returns `{id, path, wrote, warnings?}`.
  - `search_lessons` embeds `query` against the cached index and expands
    each hit back into the full lesson content the tool contract
    promises.
  - `list_lessons` reads every saved lesson from disk via `store.py`.

Task 5 adds `prune_lesson`: deletes a saved lesson's `.md` file by id
(`store.delete_lesson`) and rebuilds the index so a pruned lesson stops
being searchable immediately.

Task 7 review fix adds `clear_capture_marker`: deletes the per-session
capture marker `hooks/mark_error.py` writes at
`${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`. Originally
`agents/lesson-distiller.md` deleted this itself via the `Bash` tool
(`rm -f "${CLAUDE_PLUGIN_DATA}/..."`), but `${CLAUDE_PLUGIN_DATA}` is
only exported to hook processes and MCP/LSP server subprocesses, not to
a `Bash`-tool invocation made during a normal agent turn (confirmed
against `https://code.claude.com/docs/en/plugins-reference.md`; see also
the filed report of the identical failure mode for the sibling
`CLAUDE_PROJECT_DIR` variable, anthropics/claude-code#33815) -- so the
variable expanded to empty, the `rm -f` silently no-op'd on a
nonexistent path, and the marker was never actually deleted. This MCP
tool moves the deletion into the server process itself, which reads
`CLAUDE_PLUGIN_DATA` successfully today (see `_cache_dir` below, already
relied on by every other tool in this file).

Task 8 adds `reindex_lessons`: an unconditional full rebuild of the local
similarity index (`index.build_index`), for the "teammate committed new
lesson files, this machine's cache is stale" case `search_lessons`'s own
on-demand build doesn't cover (see `reindex_lessons`'s own docstring).

Runtime paths (never hardcoded, never resolved by hand into `.mcp.json`
-- that file keeps `${CLAUDE_PLUGIN_ROOT}` as a literal, Claude-Code-
substituted token, unrelated to the two variables this module reads):
  - Lessons live at `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`.
  - The index cache lives at `${CLAUDE_PLUGIN_DATA}`.
  Confirmed against the official Claude Code docs
  (https://code.claude.com/docs/en/mcp.md, "Add a local stdio server"
  and "Environment variables" sections, fetched during this task):
  "Claude Code sets `CLAUDE_PROJECT_DIR` in the spawned server's
  environment... Read it from inside your server process... e.g.
  `os.environ["CLAUDE_PROJECT_DIR"]` in Python", and "All three [`
  CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PROJECT_DIR`] are
  exported as environment variables to hook processes and to MCP and LSP
  server subprocesses." So this is a real process-environment variable
  Claude Code injects at launch -- not something the generic, host-
  agnostic `mcp` Python SDK itself parses, expands, or has any notion of
  -- read directly via `os.environ.get(...)`, exactly the fallback path
  the Task 4 brief anticipated if the SDK didn't auto-expand it.
  Neither variable is set when this module is imported/run outside a
  real Claude Code session (e.g. `pytest`, manual local testing) -- see
  `_lessons_dir`/`_cache_dir` below for the documented fallback used in
  that case.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

import index
import scrub
import store
from schema import Lesson, parse_lesson

logger = logging.getLogger(__name__)

mcp = FastMCP("hindsight")


# --- Runtime path resolution ------------------------------------------------


def _lessons_dir() -> Path:
    """Resolve `.debug-memory/lessons/` under `${CLAUDE_PROJECT_DIR}`
    (see module docstring for how that env var gets into this process).

    Falls back to the current working directory when `CLAUDE_PROJECT_DIR`
    is unset, which only happens outside a real Claude Code session
    (standalone scripts, `pytest` without an explicit override). This is
    a documented fallback for that situation, not a guess at real
    runtime behavior -- Claude Code always sets the variable for a real
    MCP stdio server subprocess per the docs cited above. Tests in this
    repo don't rely on the fallback; they set `CLAUDE_PROJECT_DIR`
    explicitly via `monkeypatch.setenv` so each test is isolated to its
    own `tmp_path`. Creates the directory if it doesn't exist yet (a
    freshly cloned consuming repo has no `.debug-memory/` until the
    first lesson is saved).
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    base = Path(project_dir) if project_dir else Path.cwd()
    lessons_dir = base / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    return lessons_dir


def _cache_dir() -> Path:
    """Resolve the index cache directory from `${CLAUDE_PLUGIN_DATA}`
    (real deployments: `~/.claude/plugins/data/<plugin-id>/`, per the
    Claude Code docs), same runtime-resolution approach as
    `_lessons_dir` (see its docstring for the env-var-injection details).

    Falls back to a `.debug-memory/.index-cache` directory under the
    resolved project dir when `CLAUDE_PLUGIN_DATA` is unset (same
    standalone/test scenario as `_lessons_dir`'s fallback) so those runs
    still get a stable, writable cache location without a real plugin
    install. Tests override via `monkeypatch.setenv` rather than relying
    on this.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        cache_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        cache_dir = base / ".debug-memory" / ".index-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# --- capture marker resolution (Task 7 review fix) --------------------------

# `hooks/mark_error.py` / `hooks/capture.py` sanitize a session_id to this
# charset before using it in a marker filename (unsafe chars -> `_`).
# Duplicated here (a third copy) rather than imported, for the exact same
# reason those two hook scripts duplicate it between themselves rather
# than sharing a module: hooks are separate, dependency-free `python3`
# subprocesses (see `hooks/mark_error.py`'s module docstring), unrelated
# to this server process's own import graph -- there's no shared module
# either side could import from without inventing a new coupling for
# ~1 line of logic. Kept byte-for-byte identical to both hook scripts'
# copies so a given real `session_id` always resolves to the same marker
# path on the write side (`mark_error.py`), the read side (`capture.py`),
# and this delete side.
_SESSION_ID_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_session_id(session_id: str) -> str:
    """Replace every character outside `[A-Za-z0-9_-]` with `_`, exactly
    matching `hooks/mark_error.py`'s `_marker_path` sanitization (see
    that function and this module's own note above).
    """
    return _SESSION_ID_SAFE_CHARS_RE.sub("_", session_id)


def _resolve_marker_path(session_id: str, plugin_data_dir: Path) -> Path:
    """Validate `session_id` and resolve it to
    `plugin_data_dir/session-<sanitized session_id>.marker`.

    Mirrors `store.py`'s `_resolve_lesson_path` (see that function's
    docstring for the full path-containment reasoning this adapts),
    adjusted for this directory/filename pattern instead of
    `lessons_dir`/`<id>.md`:

      1. Name-only check, on the RAW `session_id` (before sanitizing):
         must be non-empty, must equal `Path(session_id).name`, and must
         not be `.` or `..`. This rejects a `session_id` shaped like
         `/etc/passwd` or `../../etc/evil` outright -- `ValueError`, the
         same way `prune_lesson`'s `id` validation rejects an analogous
         hostile `id` -- rather than silently sanitizing a path
         separator into something that happens to land somewhere
         unintended. A real Claude Code `session_id` is always a plain
         UUID-shaped string (same reasoning `_resolve_lesson_path`
         itself gives for why every internally-produced id already
         passes this check: a shape that fails it cannot arise from any
         normal internal flow, only a hand-crafted/adversarial value).
         Characters that aren't path separators (spaces, colons, other
         punctuation, non-ASCII, ...) pass this check fine -- they're
         exactly what step 2's sanitization exists to handle, and doing
         so here still produces the identical marker filename
         `hooks/mark_error.py` writes for that same "weird but not
         traversal-shaped" `session_id`.
      2. Resolved-parent check: after sanitizing and building the
         candidate path, its resolved parent must be exactly
         `plugin_data_dir.resolve()` -- real defense in depth (e.g. a
         symlink planted at the marker's path), not redundant with step
         1, matching `_resolve_lesson_path`'s own two-check structure.
    """
    if (
        not session_id
        or session_id in (".", "..")
        or session_id != Path(session_id).name
    ):
        raise ValueError(
            f"invalid session_id {session_id!r}: must be a bare filename "
            "component (no path separators, not absolute, not '.' or '..')"
        )

    plugin_data_dir = Path(plugin_data_dir)
    safe_id = _sanitize_session_id(session_id)
    candidate = plugin_data_dir / f"session-{safe_id}.marker"
    if candidate.resolve().parent != plugin_data_dir.resolve():
        raise ValueError(
            f"invalid session_id {session_id!r}: resolves outside the "
            "plugin data directory"
        )
    return candidate


# --- git add (best-effort, never blocks the tool call) ----------------------


def _maybe_git_add(file_path: Path, project_dir: Path) -> None:
    """Stage `file_path` with `git add` iff `project_dir` (the consuming
    repo's root -- i.e. the directory `.debug-memory/` lives directly
    under, NOT `lessons_dir` itself, which is two levels deeper) has a
    `.git` entry. `Path.exists()` covers both a normal repo (`.git` is a
    directory) and a worktree/submodule checkout (`.git` is a file).

    Per Global Constraints ("stage with git if a repo exists, never
    auto-commit") and the Task 4 brief ("never error the tool call
    because git is absent"): this function never raises. No `.git`, git
    missing from `PATH`, or any other failure from the `git add`
    invocation itself are all silently swallowed (logged at most) --
    staging a file for the user's next manual commit is a courtesy on
    top of a successful save, not a required part of one. This never
    runs `git commit` -- only `git add`.

    This repository itself has no `.git` (confirmed:
    `Path(__file__).resolve().parents[1] / ".git"` does not exist here),
    so calling this against this repo's own tree is a real, verified
    no-op, not just a theoretical one.
    """
    if not (project_dir / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "-C", str(project_dir), "add", "--", str(file_path)],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        logger.warning(
            "save_lesson: git add failed or git is unavailable; continuing "
            "without staging (this never fails the save itself)",
            exc_info=True,
        )


# --- tag auto-derivation -----------------------------------------------------
#
# Task 4 brief's tags decision: `save_lesson` intentionally has no `tags`
# parameter (matches the original spec's tool contract, which never listed
# one). `schema.Lesson.tags` still backs the mandatory "## Tags for
# retrieval" body section (and therefore `Lesson.match_text()`, which
# `index.py` embeds for search), so it's populated here from the other
# fields instead of a human-curated input.

_TAG_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_TAG_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "is",
        "was", "with", "at", "by", "from", "this", "that", "it", "as",
    }
)


def _derive_tags(domain: list[str], error_signature: str, title: str) -> list[str]:
    """Auto-derive `Lesson.tags` from `domain + error_signature + title`
    keywords: dedupe, lowercase, individual tokens (not one joined blob
    string -- `Lesson.tags` is a `list[str]`, one bullet per tag in the
    rendered body, and `Lesson.match_text()` already whitespace-joins
    them for embedding, so no extra joining belongs here).
    """
    seen: set[str] = set()
    tags: list[str] = []
    for source in (*domain, error_signature, title):
        for token in _TAG_TOKEN_RE.findall(source or ""):
            token = token.lower()
            if len(token) < 2 or token in _TAG_STOPWORDS or token in seen:
                continue
            seen.add(token)
            tags.append(token)
    return tags


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- MCP tools ---------------------------------------------------------------


@mcp.tool()
def search_lessons(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Search saved debugging lessons for ones relevant to `query`.

    Embeds `query` against the local similarity index (`index.py`, cache
    at `${CLAUDE_PLUGIN_DATA}`) and expands each hit that clears the
    similarity threshold back into the full lesson content, per Global
    Constraints' output shape: `{id, title, score, failed_approaches,
    root_cause, fix, path}`. Returns `[]` if nothing clears the
    threshold -- never a weak match dressed as strong (that guarantee
    lives in `index.search` itself; this function doesn't loosen it).

    On-demand index build (post-Task-4-review fix): if `index.json`
    doesn't exist yet in `${CLAUDE_PLUGIN_DATA}` -- e.g. a repo freshly
    cloned/pulled from a teammate who already committed lessons under
    `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`, searched on this
    machine before this machine's own `save_lesson` ever ran -- this
    builds the index once from whatever lesson files already exist
    before searching, rather than silently returning `[]` (which would
    be indistinguishable from "no relevant lessons exist"). `index.
    build_index` is idempotent and purely derived from the markdown
    files, so this is safe and cheap. Only triggered when the cache file
    is genuinely *missing*; an existing-but-stale index is left alone
    here (out of scope for this fix) -- that's what the save-triggered
    rebuild in `save_lesson` and a future manual reindex command (Task
    8) are for. Any lesson file skipped by this on-demand build (parse
    failure) is logged, not raised: `search_lessons` returns a
    `list[dict]`, not a single dict, so there's no natural top-level
    slot to attach a `warnings` field the way `save_lesson` does (see
    that function's own `warnings` handling) -- logging keeps this path
    from silently swallowing the problem without changing this
    function's return shape.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    index_path = cache_dir / index.INDEX_FILENAME
    if not index_path.exists():
        built_path = index.build_index(lessons_dir, cache_dir)
        skipped = json.loads(built_path.read_text(encoding="utf-8")).get("skipped", [])
        for entry in skipped:
            logger.warning(
                "search_lessons: on-demand index build skipped a lesson "
                "file and excluded it from search: %s: %s",
                entry["path"],
                entry["error"],
            )

    hits = index.search(query, cache_dir, k=k)

    results: list[dict[str, Any]] = []
    for hit in hits:
        lesson_path = Path(hit["path"])
        try:
            lesson = parse_lesson(lesson_path.read_text(encoding="utf-8"))
        except Exception as exc:
            # The index references a file that went missing or became
            # malformed since the index was last built (manual edit/
            # delete outside this server, or a stale cache). Skip it
            # rather than fail the whole search -- the same per-file
            # error isolation index.build_index itself documents and
            # uses (broad `Exception`, not just ValueError/OSError:
            # malformed YAML raises yaml.YAMLError, a different
            # hierarchy than parse_lesson's own ValueError).
            logger.warning(
                "search_lessons: skipping stale/unreadable index entry %s: %s: %s",
                lesson_path,
                type(exc).__name__,
                exc,
            )
            continue
        results.append(
            {
                "id": hit["id"],
                "title": lesson.title,
                "score": hit["score"],
                "failed_approaches": lesson.failed_approaches,
                "root_cause": lesson.root_cause,
                "fix": lesson.fix,
                "path": hit["path"],
            }
        )
    return results


@mcp.tool()
def save_lesson(
    title: str,
    domain: list[str],
    error_signature: str,
    symptom: str,
    failed_approaches: list[str],
    root_cause: str,
    fix: str,
    confidence: Literal["confirmed", "probable"] = "probable",
) -> dict[str, Any]:
    """Save a debugging lesson learned during this session.

    Pipeline: scrub every free-text field (`scrub.py`) -> build a
    `Lesson` (`schema.py`; auto-derives `id` and retrieval `tags` -- see
    `_derive_tags`, no `tags` parameter on this tool by design, see that
    function's docstring) -> write it to
    `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/<id>.md` (`store.py`) ->
    rebuild the local similarity index (`index.py`) -> best-effort
    `git add` the new file (`_maybe_git_add`) -> return `{id, path,
    wrote: true}`.

    If the index rebuild's most recent run skipped any lesson file
    because it failed to parse (`index.json`'s `skipped` list --
    `index.py`, added after the Task 3 review so one corrupt file can't
    silently take down search over every other lesson), that is
    surfaced here as a `warnings` field on this call's own return value
    rather than swallowed: a systemic `parse_lesson` bug would otherwise
    look like a clean, successful save while quietly excluding every
    lesson (including past ones, not just this one) from search.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    scrubbed = scrub.scrub_payload(
        {
            "title": title,
            "domain": domain,
            "error_signature": error_signature,
            "symptom": symptom,
            "failed_approaches": failed_approaches,
            "root_cause": root_cause,
            "fix": fix,
        }
    )

    created_at = _utc_now_iso()
    lesson = Lesson(
        id=store.make_lesson_id(scrubbed["title"], created_at),
        title=scrubbed["title"],
        domain=scrubbed["domain"],
        error_signature=scrubbed["error_signature"],
        created_at=created_at,
        confidence=confidence,
        symptom=scrubbed["symptom"],
        failed_approaches=scrubbed["failed_approaches"],
        root_cause=scrubbed["root_cause"],
        fix=scrubbed["fix"],
        tags=_derive_tags(scrubbed["domain"], scrubbed["error_signature"], scrubbed["title"]),
    )

    path = store.write_lesson(lesson, lessons_dir)
    saved_id = path.stem  # store.write_lesson may have adjusted the id on a collision

    index_path = index.build_index(lessons_dir, cache_dir)
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    skipped = index_data.get("skipped", [])

    _maybe_git_add(path, lessons_dir.parent.parent)

    result: dict[str, Any] = {"id": saved_id, "path": str(path), "wrote": True}
    if skipped:
        result["warnings"] = [
            f"lesson file failed to index and was excluded from search: "
            f"{entry['path']}: {entry['error']}"
            for entry in skipped
        ]
    return result


@mcp.tool()
def list_lessons() -> list[dict[str, Any]]:
    """List all saved debugging lessons."""
    return store.list_lessons(_lessons_dir())


@mcp.tool()
def prune_lesson(id: str) -> dict[str, Any]:
    """Delete a saved debugging lesson by id (Task 5).

    Deletes `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/<id>.md`
    (`store.delete_lesson`) and, if a file was actually removed, rebuilds
    the local similarity index (`index.build_index` -- same call pattern
    `save_lesson` already uses) so the pruned lesson stops being
    returned by `search_lessons` immediately, not just on the next
    unrelated rebuild.

    Returns `{"deleted": true}` if a file was removed, `{"deleted":
    false}` if no file matched `id` -- pruning an id that's already gone
    (or was never saved) is a normal outcome, not an error. The index
    rebuild is skipped in that case: nothing on disk changed, so the
    existing index (or lack of one) is already consistent with reality.
    A stale index entry left behind by some *other* means (e.g. a lesson
    file deleted by hand outside this tool) still degrades gracefully --
    `search_lessons` already skips index entries whose file has gone
    missing (see its own docstring) -- so this isn't a correctness gap,
    just an avoided no-op rebuild.

    Path-traversal note (post-Task-5-review fix): `id` is caller-
    supplied and, before this fix, was concatenated straight into a
    filesystem path with no validation -- `id="/etc/passwd"` or
    `id="../../../../some/file"` could delete an arbitrary `.md`-
    suffixed file anywhere this process can write, not just a saved
    lesson. `store.delete_lesson` now rejects any `id` that isn't a bare
    filename component by raising `ValueError`, which is intentionally
    *not* caught here -- FastMCP's tool dispatch turns an uncaught
    exception into an `isError: true` tool result for the caller, which
    is the right outcome for what is, in practice, only ever a hand-
    crafted malicious/malformed `id` (every id this server itself
    generates, via `store.make_lesson_id`, is already a safe bare
    filename -- see `store.delete_lesson`'s own docstring for the full
    reasoning). Letting it surface as a clear tool error beats
    collapsing it into `{"deleted": false}`, which would look identical
    to the ordinary "no such lesson" case.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    deleted = store.delete_lesson(id, lessons_dir)
    if deleted:
        index.build_index(lessons_dir, cache_dir)

    return {"deleted": deleted}


@mcp.tool()
def clear_capture_marker(session_id: str) -> dict[str, Any]:
    """Delete the per-session capture marker `hooks/mark_error.py` wrote
    at `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (Task 7 review
    fix), if it exists.

    Called by `agents/lesson-distiller.md` after a successful
    `save_lesson`, so a later `Stop` event in the same session doesn't
    re-emit `hooks/capture.py`'s capture nudge for an incident that's
    already been saved. Moved here from a `Bash`-tool `rm -f` in the
    distiller agent itself because `${CLAUDE_PLUGIN_DATA}` is not
    reliably present in a `Bash`-tool subprocess's environment (see this
    module's own docstring for the full story); this server process
    reads it successfully today via `_cache_dir`, which resolves to the
    exact same directory `hooks/mark_error.py` writes the marker into
    (both read the same `CLAUDE_PLUGIN_DATA` env var with no
    subdirectory appended -- confirmed by reading both implementations
    side by side before writing this tool).

    Returns `{"cleared": True}` if a marker file was found and deleted,
    `{"cleared": False}` if no marker existed for this `session_id` --
    mirrors `prune_lesson`'s "not found is not an error" pattern above:
    a session that never hit a tool failure (so `mark_error.py` never
    ran) has no marker to clear, which is a normal, expected outcome,
    not a failure of this tool.

    Raises `ValueError` on a `session_id` shaped like a path-traversal
    attempt (see `_resolve_marker_path`) -- deliberately uncaught, same
    as `prune_lesson`'s `id` validation above: FastMCP turns this into
    an `isError: true` tool result, which is the right outcome for what
    is, in practice, only ever a hand-crafted/malicious `session_id`.
    """
    plugin_data_dir = _cache_dir()
    marker_path = _resolve_marker_path(session_id, plugin_data_dir)

    if not marker_path.exists():
        return {"cleared": False}
    marker_path.unlink()
    return {"cleared": True}


@mcp.tool()
def reindex_lessons() -> dict[str, Any]:
    """Full rebuild of the local similarity index from every lesson file
    currently on disk (Task 8's `hindsight reindex` command).

    Thin wrapper around `index.build_index(_lessons_dir(), _cache_dir())`
    -- the exact same full-rebuild-from-markdown call `save_lesson` and
    `prune_lesson` already make as a side effect of every write/delete
    (see their own docstrings) -- just invokable directly, on demand,
    with no write/delete attached. Useful after a `git pull` brings in
    teammates' newly-committed lesson files: this machine's local index
    cache (`${CLAUDE_PLUGIN_DATA}`, machine-local, never git-committed --
    see this module's own docstring) doesn't know about those files yet,
    and `search_lessons`'s own on-demand build (see its docstring) only
    triggers when `index.json` is entirely *missing*, not when it's
    merely stale -- so a manual reindex is still the only way to pick up
    new lessons on a machine that already has *some* index cached.

    Deliberately runs inside this MCP server process rather than as a
    `Bash`-tool-invoked script, for the same reason `clear_capture_marker`
    above was moved into this server instead of a `Bash`-tool `rm -f`:
    `${CLAUDE_PROJECT_DIR}`/`${CLAUDE_PLUGIN_DATA}` are only reliably
    exported to a hook process or an MCP/LSP server subprocess, not to a
    `Bash`-tool invocation made during a normal agent turn (see this
    module's own docstring, and the Task 7 review fix, which hit exactly
    this bug for marker deletion). A reindex invoked via `Bash` could
    silently rebuild an index at the wrong path -- one `search_lessons`
    never reads from -- while still printing a plausible-looking "N
    lessons indexed" success message. Calling `index.build_index` from
    here instead guarantees this always rebuilds the exact same index
    every other tool in this file reads from and writes to.
    `skills/hindsight/SKILL.md`'s `/hindsight reindex` subcommand calls
    this tool for that reason. `server/reindex.py` (Task 8) is a
    separate, lower-level standalone CLI entry point for reindexing
    outside a live Claude Code session (CI, a maintainer's own terminal)
    -- see that script's module docstring for why it does NOT back
    `/hindsight reindex` itself.

    Returns `{"indexed": <N>, "skipped": [...], "lessons_dir": <str>,
    "index_path": <str>}`. `indexed` is the number of lesson files that
    parsed and were embedded into the rebuilt index. `skipped` mirrors
    `save_lesson`'s own `skipped`-surfacing: a list of `{path, error}` for
    any lesson file that failed to parse during this rebuild (`[]` in the
    common case where every lesson file parses cleanly).
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    index_path = index.build_index(lessons_dir, cache_dir)
    index_data = json.loads(index_path.read_text(encoding="utf-8"))

    return {
        "indexed": len(index_data.get("records", [])),
        "skipped": index_data.get("skipped", []),
        "lessons_dir": str(lessons_dir),
        "index_path": str(index_path),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## server/reindex.py
```
#!/usr/bin/env python3
"""Standalone CLI: full rebuild of the hindsight local similarity index.

Usage (`uv`, not bare `python3` -- this imports `index.py`, which needs
`fastembed`, and `main.py`, which needs `mcp`; see `server/requirements.txt`
and this repo's own `.mcp.json`, which launches the MCP server the exact
same way):

    uv run --no-project --with-requirements server/requirements.txt \\
        server/reindex.py [--lessons-dir DIR] [--cache-dir DIR]

Always a FULL rebuild -- `index.build_index` re-reads every `*.md` file
under `lessons_dir` from scratch every time it's called (see that
function's own docstring); this script never attempts an incremental
update. Prints how many lessons were indexed and, if any lesson files
failed to parse, which ones and why (`skipped`, same shape
`save_lesson`'s own `warnings` surfaces).

Path resolution: `--lessons-dir`/`--cache-dir` are optional. Omitted,
they fall back to `main.py`'s own `_lessons_dir()`/`_cache_dir()` -- the
exact same `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA`-then-cwd resolution
every MCP tool in this server already uses (imported from `main.py`
rather than re-implemented a third time here, matching this codebase's
existing "one parser"/"one sanitizer" preference -- see e.g.
`schema.parse_lesson`'s and `main._sanitize_session_id`'s own docstrings
for the same reasoning applied elsewhere). A run from inside a real
Claude Code project directory with those two env vars actually exported
(or set by hand) resolves the same `lessons_dir`/`cache_dir` the MCP
server itself reads from and writes to.

IMPORTANT -- this is NOT what `/hindsight reindex` calls. `${CLAUDE_
PLUGIN_DATA}` (and `${CLAUDE_PROJECT_DIR}`) are only reliably exported as
real environment variables to a hook process or an MCP/LSP server
subprocess -- NOT to a `Bash`-tool invocation made during a normal agent
turn (see `main.py`'s own module docstring, and the Task 7 review fix for
`clear_capture_marker`, which hit exactly this failure mode: a `Bash`
`rm -f "${CLAUDE_PLUGIN_DATA}/..."` silently no-op'd because the shell
never saw the variable, and the fix was to move that logic into the MCP
server process instead). Running *this* script via the `Bash` tool from
inside a live session would hit the identical problem -- `_lessons_dir()`/
`_cache_dir()`'s env-var reads would silently fail and fall back to
cwd-relative directories that do NOT match the real, Claude-Code-managed
plugin data directory the running MCP server actually reads its index
cache from. It would look like it worked (a plausible "N lessons
indexed" message) while rebuilding an index nobody ever searches.

`skills/hindsight/SKILL.md`'s `/hindsight reindex` subcommand therefore
calls the `reindex_lessons` MCP tool (`server/main.py`) instead, which
runs inside the MCP server process and always resolves the real env vars
correctly -- see that tool's own docstring for the full reasoning. This
script exists for everything else a full rebuild is useful for outside
that specific in-session context: CI, a maintainer's own terminal with
`CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` exported by hand, or pointed at
an explicit `--lessons-dir`/`--cache-dir` pair (e.g. for local testing
against a scratch fixtures directory, independent of any real plugin
install).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import index
from main import _cache_dir, _lessons_dir


def reindex(lessons_dir: Path, cache_dir: Path) -> dict:
    """Rebuild the index at `cache_dir` from every lesson `.md` file
    under `lessons_dir`, and return a summary dict: `{"indexed": <N>,
    "skipped": [...], "lessons_dir": <str>, "index_path": <str>}` -- the
    exact same shape `server/main.py`'s `reindex_lessons` MCP tool
    returns (this function IS that tool's implementation, extracted so
    both the CLI below and, in principle, a test can call it directly
    without going through `argparse`).
    """
    index_path = index.build_index(lessons_dir, cache_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "indexed": len(data.get("records", [])),
        "skipped": data.get("skipped", []),
        "lessons_dir": str(lessons_dir),
        "index_path": str(index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Full rebuild of the hindsight local similarity index from "
            "every lesson .md file on disk."
        )
    )
    parser.add_argument(
        "--lessons-dir",
        type=Path,
        default=None,
        help=(
            "Directory of lesson .md files to index. Defaults to the same "
            "CLAUDE_PROJECT_DIR-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/lessons under the current "
            "working directory if CLAUDE_PROJECT_DIR is unset)."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write index.json to. Defaults to the same "
            "CLAUDE_PLUGIN_DATA-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/.index-cache if unset) -- see "
            "this script's module docstring for why that default will NOT "
            "match a real installed plugin's actual cache directory unless "
            "CLAUDE_PLUGIN_DATA is exported."
        ),
    )
    args = parser.parse_args()

    lessons_dir = args.lessons_dir if args.lessons_dir is not None else _lessons_dir()
    cache_dir = args.cache_dir if args.cache_dir is not None else _cache_dir()

    result = reindex(lessons_dir, cache_dir)

    print(f"Reindexed {result['indexed']} lesson(s) from {result['lessons_dir']}")
    if result["skipped"]:
        print(f"Skipped {len(result['skipped'])} file(s) that failed to parse:")
        for entry in result["skipped"]:
            print(f"  - {entry['path']}: {entry['error']}")
    print(f"Index written to {result['index_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
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
# Wired up starting Task 3 (server/index.py).
fastembed==0.8.0

# YAML frontmatter parsing (schema.py's parse_lesson(), the inverse of
# Lesson.render()). render()'s emission stays hand-rolled (see schema.py's
# module docstring for why); parsing takes the PyYAML dependency instead
# of hand-rolling a YAML-escape unescaper. Was already an indirect
# dependency (pulled in transitively by mcp) and used directly by
# server/tests/test_schema.py since Task 2 — pinned explicitly here from
# Task 3 onward since production code (schema.py) now imports it too, not
# just tests.
PyYAML==6.0.3

# Test runner for server/tests/ (schema.py, scrub.py, and later modules).
# Run with:
#   uv run --no-project --with-requirements server/requirements.txt \
#       pytest server/tests/
pytest==8.3.4
```
