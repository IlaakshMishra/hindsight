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
