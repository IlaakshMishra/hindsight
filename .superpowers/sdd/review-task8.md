# Review package: Task 8 (no git — full file dump)

## Full file tree
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/marketplace.json
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

## .claude-plugin/plugin.json
```
{
  "name": "hindsight",
  "version": "0.1.0",
  "description": "Shared memory for debugging sessions: search and save hard-won fixes across your team so nobody re-debugs the same error twice."
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

## server/main.py (full, incl new reindex_lessons tool)
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
