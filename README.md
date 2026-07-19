# hindsight

[github.com/IlaakshMishra/hindsight](https://github.com/IlaakshMishra/hindsight)

Hindsight gives your team shared, on-demand memory of every debugging
session. Solve an error once, and every teammate's Claude skips the dead
ends next time. Lives in your repo. Sends nothing to the cloud.

**Prerequisite:** [`uv`](https://docs.astral.sh/uv/) must be installed on
your machine — the MCP server, the hook scripts, and the standalone
reindex CLI are all launched via `uv run`, which resolves a real Python
regardless of whether your system's interpreter is named `python3` or
`python` (auto-provisions its own isolated environment on first use — no
manual `pip install`/venv setup required).

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
/plugin marketplace add IlaakshMishra/hindsight
/plugin install hindsight
```

(Or, from a local checkout instead of GitHub: `/plugin marketplace add .`
from inside this repo.)

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

## Example

A worked walkthrough of the automatic loop — no `/hindsight` command
needed for any of this, it just happens:

**Day 1 — a teammate hits an error and fixes it.**

1. They're debugging an ECS task that starts then immediately stops. A
   `Bash` tool call (`aws ecs describe-tasks ...`) comes back showing a
   `ResourceInitializationError`. That failed tool call fires
   `PostToolUseFailure`, which nudges Claude: *"A tool call just failed —
   `hindsight search_lessons` can surface past team lessons on similar
   errors..."* Claude calls `search_lessons("ECS task stops immediately,
   ResourceInitializationError pulling image")`. Nothing relevant comes
   back yet — this is the first time anyone's hit it.
2. Claude and the developer spend twenty minutes ruling out task-role
   permissions and image issues, then find the real cause: the task's
   subnet has no NAT route and no VPC endpoints, so it can't reach ECR.
   They add the missing endpoints. The task starts.
3. The developer keeps working. Eventually their turn ends — `Stop`
   fires. A marker was set back in step 1 (any `PostToolUseFailure` sets
   one), so the hook nudges Claude that this session's failure looks
   resolved and the `lesson-distiller` agent can turn it into a saved
   lesson. Claude dispatches `lesson-distiller` with a short summary: the
   error signature, what was tried and ruled out, the root cause, the
   fix. The agent scrubs anything secret-shaped, calls `save_lesson`, and
   a new file lands at
   `.debug-memory/lessons/2026-07-18-ecs-task-vpc-subnet.md`.
4. The developer commits it along with their actual fix — it's just a
   markdown file, reviewable in the same PR.

**Day 12 — a different teammate hits a similar error.**

5. Same symptom, different service. Their tool call fails the same way,
   the same `PostToolUseFailure` nudge fires, Claude calls
   `search_lessons("task fails to pull image, stuck initializing")`. This
   time the Day-1 lesson clears the similarity threshold and comes back
   with its `failed_approaches` (task role, image rebuild — both dead
   ends) and its `fix` (VPC endpoints or a NAT route). Claude treats the
   fix as a starting hypothesis, not gospel — the codebase may have
   changed — but skips straight past the two dead ends the first
   developer already ruled out, and checks the subnet routing first.

No one ran `/hindsight save` or `/hindsight search` by hand anywhere in
this — that's the point. The manual subcommands exist for the cases
automation doesn't cover: seeding the library from an old incident that
predates this plugin, checking what's saved, or forcing a reindex after
`git pull`.

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
