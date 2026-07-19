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
                                        (in the git repo, source of truth)      (${CLAUDE_PLUGIN_DATA}/<project slug>/, rebuildable)
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
local embedding index is a rebuildable cache under
`${CLAUDE_PLUGIN_DATA}/<project slug>/` (never git-committed, never
authoritative) that makes `search_lessons` fast; see `/hindsight reindex`
below for when to force-rebuild it. `${CLAUDE_PLUGIN_DATA}` is one
directory per plugin *per machine*, shared across every project that has
this plugin installed — the `<project slug>` subdirectory (derived from
`${CLAUDE_PROJECT_DIR}`) keeps two different repos on the same machine
from sharing (and silently overwriting) one index.

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
