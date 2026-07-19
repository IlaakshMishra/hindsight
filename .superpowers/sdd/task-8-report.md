# Task 8 report: Distribution (Phase 5)

## Status

DONE. No blockers. All required files created/updated, both test suites
green, `claude plugin validate` clean (one pre-existing, expected
warning), reindex command built and verified end-to-end.

## Files created

- `.claude-plugin/marketplace.json` — single-plugin marketplace manifest,
  `source: "./"` pointing at this repo itself.
- `server/reindex.py` — standalone CLI entry point for a full index
  rebuild, runnable outside a live Claude Code session.

## Files edited

- `README.md` — full rewrite, replacing Task 1's "skeleton only" stub.
- `server/main.py` — added one new tool, `reindex_lessons()`, plus two
  docstring updates (module-level tool list, Task 8 note). No existing
  tool's body was touched.
- `server/tests/test_main.py` — added 4 tests for `reindex_lessons`.
- `skills/hindsight/SKILL.md` — added `/hindsight reindex` subcommand,
  updated the frontmatter description, intro paragraph, and usage summary
  to include it.
- `docs/superpowers/plans/progress.md` — appended the Task 8 entry,
  matching every prior task's documentation pattern in that file.

## `marketplace.json`: schema and placement

The brief said "`marketplace.json` at repo root." I read three real,
locally-installed marketplaces before writing anything
(`/Users/ilaakshmishra/.claude/plugins/marketplaces/gatecheck/`,
`.../claude-plugins-official/`, `.../caveman/`) — all three actually live
at `<repo>/.claude-plugin/marketplace.json`, not a bare
`<repo>/marketplace.json`. I confirmed this is a hard requirement, not
just convention, by testing `claude plugin validate` against a scratch
directory with a marketplace.json at bare repo root (no `.claude-plugin/`
wrapper): it fails outright —
`✘ directory: No manifest found in directory. Expected .claude-plugin/marketplace.json or .claude-plugin/plugin.json`.
So I placed it at `.claude-plugin/marketplace.json`, reading the brief's
"repo root" as the informal/conceptual location (same way `plugin.json`
is casually described as "at repo root" while actually living one level
deeper), not a literal bare-file instruction.

Schema, modeled directly on `gatecheck`'s real, currently-installed
marketplace.json (name, description, `owner`, `plugins: [{name,
description, source, category}]`):

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "hindsight",
  "description": "...",
  "owner": { "name": "IlaakshMishra" },
  "plugins": [
    {
      "name": "hindsight",
      "description": "Shared memory for debugging sessions: ...",
      "source": "./",
      "category": "development"
    }
  ]
}
```

Two judgment calls on `owner`:
- `owner` is a **required** object (confirmed by testing: omitting it
  entirely produces a hard validation error, `owner: Invalid input:
  expected object, received undefined` — unlike `plugin.json`'s optional
  `author`, which only warns). I could not leave it blank the way Task 1
  deliberately left `plugin.json`'s `author` blank.
- `owner.name`: set to `"IlaakshMishra"` — the real local machine owner's
  identity, evidenced by this exact same person's other real, installed,
  published plugin (`gatecheck`, owned by `IlaakshMishra`) living
  alongside this repo under the same home directory. This is inferring
  the actual owner from real environment evidence, not inventing a
  fictitious identity.
- `owner.url`: deliberately omitted (confirmed optional via testing). I
  did not fabricate a `github.com/IlaakshMishra/hindsight` URL — this
  repo has no `.git` and no known remote (confirmed: not a git repo per
  the environment description), so claiming a repo URL would be inventing
  something that doesn't exist, the same "don't fabricate" principle the
  brief applied explicitly to the demo GIF.

`plugins[0].description` reuses `plugin.json`'s existing (Task
1-approved) description verbatim, for consistency across the two
manifest surfaces — I did not invent new marketing copy for this field,
and I left `plugin.json` itself completely untouched (out of this task's
explicit file list).

## Validation result

```
$ claude plugin validate .
Validating marketplace manifest: /Users/ilaakshmishra/Documents/hindsight/.claude-plugin/marketplace.json

⚠ Found 1 warning:

  ❯ plugins[0] plugin.json → author: No author information provided. Consider adding author details for plugin attribution

✔ Validation passed with warnings
(exit 0)
```

This is the *same* warning Task 1 got (`author` missing on
`plugin.json`), now surfaced through the marketplace path since
`marketplace.json`'s presence makes `validate .` check the marketplace
manifest (which in turn validates each listed plugin) rather than
`plugin.json` directly. Confirmed `plugin.json` still validates cleanly
on its own too (`claude plugin validate .claude-plugin/plugin.json` →
same single warning). `--strict` correctly turns it into a failure (exit
1), as designed — expected, not a bug, since `author` is genuinely still
absent (Task 1's original judgment call, left as-is; not in this task's
file list to touch). **Nothing new was flagged** by re-running validate
now that hooks/agents/skills exist — the growth since Task 1 introduced
no new validation issues.

## README.md

Replaced Task 1's stub entirely. Sections, in order: title + spec-section-13
one-liner (verbatim), `uv` prerequisite, "Why not just a bigger CLAUDE.md?"
(spec section 1, used verbatim per the brief's "use it verbatim... do not
paraphrase" instruction — I used the full text rather than a condensed
excerpt, satisfying the "use" branch of "condense/use"), install
instructions, the architecture diagram (spec section 3, copied
byte-for-byte and verified programmatically — see below — plus a short
prose note directly under it clarifying the capture hook fires on `Stop`,
not `SessionEnd`, per the brief's explicit instruction), a tool-surface
table (signatures re-derived from actually reading `server/main.py`, not
from the brief's summary alone), the `/hindsight` skill's subcommands
including the new `reindex`, and a demo-GIF placeholder that explicitly
states no GIF has been recorded yet (no fabrication).

Verified programmatically (not just by eye) that both verbatim text
requirements were met exactly:
- The architecture diagram: an exact Python string-containment check
  against the diagram text as given in the task prompt — passed
  byte-for-byte on the first try (no ASCII-art corruption).
- Spec section 13 and section 1: whitespace-normalized containment
  checks both passed — the README soft-wraps these paragraphs at normal
  Markdown line lengths (which renders identically to the single-line
  source), so a raw substring check initially reported false negatives
  purely from the wrapping; normalizing whitespace before comparing
  confirmed the actual *content* is unmodified.

Install instructions use `<path-or-git-url-to-this-repo>` as an explicit,
clearly-labeled placeholder rather than a fabricated GitHub URL, since
this repo has no real remote yet (not a git repo at all in this
environment) — documented inline in the README itself, not just here.

## `hindsight reindex`: design decision

The brief framed this as implementer's judgment between a `/hindsight
reindex` SKILL.md subcommand and a standalone CLI, and flagged that a
standalone CLI needs `uv run`, not plain `python3`. I built **both**, but
they're not interchangeable, and `/hindsight reindex` does **not** shell
out to the standalone CLI — this is the one real design decision in this
task worth explaining in full.

**The problem:** `index.build_index` needs a `(lessons_dir, cache_dir)`
pair. Every existing tool in `server/main.py` resolves those from
`${CLAUDE_PROJECT_DIR}`/`${CLAUDE_PLUGIN_DATA}`, which Claude Code injects
as real environment variables into the MCP server subprocess. Task 7's
review already discovered (and fixed, for `clear_capture_marker`) that
those same variables are **not** reliably present in a `Bash`-tool
subprocess invoked mid-session — `${CLAUDE_PLUGIN_DATA}` expands to
nothing there, since Claude Code only exports it to hook processes and
MCP/LSP server subprocesses, confirmed against the official docs and
already relied upon throughout this codebase (see `server/main.py`'s own
module docstring). I re-confirmed this is still the load-bearing fact by
re-reading that docstring and the Task 7 fix before deciding here, rather
than re-deriving it from scratch.

If `/hindsight reindex` had been implemented as "shell out via `Bash` to
`uv run ... server/reindex.py`," the CLI's env-var fallback would
silently resolve to a *cwd-relative* cache directory
(`<cwd>/.debug-memory/.index-cache/`), not the real
`${CLAUDE_PLUGIN_DATA}` location the actual running MCP server reads its
index from. The command would print a plausible "Reindexed N lessons"
success message while rebuilding an index nobody ever searches — a worse
failure mode than not having the feature, because it fails silently and
looks like it worked.

**The fix:** I added `reindex_lessons()` as a genuine new MCP tool in
`server/main.py` — a thin wrapper: `index.build_index(_lessons_dir(),
_cache_dir())`, returning `{"indexed": N, "skipped": [...],
"lessons_dir", "index_path"}`. It runs inside the MCP server process,
where those two env vars are always resolved correctly (same as every
other tool in the file). This is purely additive — one new
`@mcp.tool()` function appended after `clear_capture_marker`; none of the
five existing tools' bodies changed — consistent with "don't modify
server/main.py's existing tool logic." `/hindsight reindex` in
`skills/hindsight/SKILL.md` calls `mcp__hindsight__reindex_lessons`, the
same calling convention as its four sibling subcommands.

`server/reindex.py` still exists as a real, separately-useful, `uv
run`-launched standalone CLI (`--lessons-dir`/`--cache-dir` optional,
defaulting to the same env-var resolution via importing `_lessons_dir`/
`_cache_dir` from `main.py` rather than re-implementing that logic a
third time) — for CI, a maintainer's own terminal, or pointing at an
explicit test fixtures directory. Its own module docstring documents in
detail why it is *not* what `/hindsight reindex` calls, so a future
reader doesn't wire it in that way by mistake later.

### Verification

**pytest** (`server/tests/test_main.py`, 4 new tests, extending the
existing `isolated_project`-fixture pattern used for every other tool):
- `test_reindex_lessons_rebuilds_from_scratch_and_reports_count` — 3
  fixture lessons on disk, `reindex_lessons()` reports `indexed == 3`,
  and a subsequent `search_lessons` call finds the expected top hit.
- `test_reindex_lessons_on_fresh_project_reports_zero`.
- `test_reindex_lessons_surfaces_skipped_malformed_files` — one
  malformed lesson file, confirms it's reported in `skipped`, not
  silently dropped.
- `test_reindex_lessons_picks_up_a_stale_cache_unlike_search_lessons_on_demand_build`
  — the regression test that actually justifies the feature's existence:
  saves one lesson (building a cache), then drops a second lesson file
  directly on disk (simulating a `git pull`), confirms `search_lessons`
  does *not* find it yet (proving the on-demand-build fallback really
  doesn't cover staleness, only absence), then confirms `reindex_lessons`
  fixes it.

**Standalone CLI, run for real** against a scratch fixtures directory
(brief's explicit ask: "create a small lessons directory with 2-3
fixture lesson files, run reindex against it, confirm it reports the
right count and produces a working index"):

```
$ uv run --no-project --with-requirements server/requirements.txt \
    server/reindex.py --lessons-dir <scratch>/lessons --cache-dir <scratch>/cache
Reindexed 3 lesson(s) from <scratch>/lessons
Index written to <scratch>/cache/index.json
```

Then, a separate script called `index.search` directly against that
rebuilt cache (no MCP dependency needed for this, since `index.py` has
none):

```
[
  {"id": "2026-06-02-react-useeffect-infinite-loop", "score": 0.861...},
  {"id": "2026-05-14-docker-build-oom-killed", "score": 0.561...}
]
OK: reindexed cache is searchable and returns the expected top hit
```

Also verified the CLI's argument-less fallback path (no `--lessons-dir`/
`--cache-dir`, `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` unset, cwd = a
scratch project dir with `.debug-memory/lessons/`): correctly resolved to
`<cwd>/.debug-memory/lessons` and wrote `<cwd>/.debug-memory/.index-cache/index.json`.

**Full MCP stdio round-trip** (same technique Task 1/4 used — spawns the
server exactly as `.mcp.json` specifies, via `uv run`, does a real
`initialize` + `tools/list`):

```
Registered tools: ['clear_capture_marker', 'list_lessons', 'prune_lesson',
                    'reindex_lessons', 'save_lesson', 'search_lessons']
ALL CHECKS PASSED: exactly 6 tools registered, including reindex_lessons
```

Confirms the new tool is real and reachable over the actual transport,
not just callable as a bare Python function in pytest.

## Test suite results

- **Server** (`uv run --no-project --with-requirements server/requirements.txt pytest server/tests/`):
  **120/120 passed** (116 prior + 4 new `reindex_lessons` tests).
- **Hooks** (`python3 -m pytest hooks/tests/`): **22/22 passed**,
  unchanged — hooks were not touched, out of this task's scope.

## Deviations / judgment calls summary

1. `marketplace.json` placed at `.claude-plugin/marketplace.json`, not a
   literal bare-file repo root — confirmed required by testing, not
   inferred.
2. `owner.url` omitted from `marketplace.json` (no real remote exists);
   `owner.name` set to the real local user's identity inferred from
   environment evidence (their other real, installed `gatecheck` plugin),
   not invented from nothing.
3. `plugin.json` left completely untouched — not in this task's file
   list, and its `author` omission was Task 1's own deliberate,
   documented "don't fabricate" call; re-litigating it wasn't this task's
   job.
4. `hindsight reindex` implemented as an MCP tool (`reindex_lessons`) +
   SKILL.md subcommand as the primary, correct path, **and** a standalone
   `server/reindex.py` CLI as a secondary, explicitly-scoped entry
   point — not an either/or as the brief's phrasing suggested, because
   the either/or framing didn't account for the
   `${CLAUDE_PLUGIN_DATA}`-invisible-to-Bash-tool problem this exact
   codebase already hit and fixed once before (Task 7). Fully justified
   and verified above, not just asserted.

## Concerns / follow-ups for a human

- No real git remote exists for this repo yet, so the install
  instructions' `<path-or-git-url-to-this-repo>` placeholder is
  necessarily generic. Once this repo is pushed somewhere, the README's
  install section should get the real URL substituted in (one-line
  edit).
- `marketplace.json`'s `owner.name` ("IlaakshMishra") is an inference
  from environment evidence, not a value explicitly provided anywhere in
  this task's instructions — worth a quick human confirmation that this
  is in fact the intended maintainer identity before this repo is ever
  actually published.
