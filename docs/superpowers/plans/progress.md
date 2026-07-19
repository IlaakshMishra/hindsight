# Hindsight build — progress ledger

No git in this project (user constraint). Tasks tracked by file path, not
commit hash.

## Post-ship bug: hooks failed for users without `python3` on PATH

User-reported production bug (after all 8 tasks + final review shipped):
`hooks.json` launched all three hooks via bare `command: "python3"`.
Users whose only interpreter on PATH is named `python` (some
Windows/Linux setups) got a silently failing hook — no nudge, no marker,
no capture, no visible error. Measured `uv run --no-project` startup
against this machine's `python3` (resolved through a pyenv shim): `uv`
was *faster* cached (~35ms vs ~96ms) — the original "avoid uv's startup
cost" rationale for using bare python3 didn't hold up, and `uv` is
already a hard prerequisite for this plugin (the MCP server needs it).
Fixed: all three `hooks.json` entries now launch via `command: "uv"`,
`args: ["run", "--no-project", <script>]` — resolves a real Python
regardless of what's named what on PATH. Updated stale comments in
`hooks/retrieve.py` and both hook test files that asserted the old
"bare python3, no uv" rationale. Added `hooks/tests/test_hooks_json.py`
(3 new tests) pinning hooks.json's actual command shape, specifically to
catch a future accidental revert to bare python3/python. Verified: full
suite 26/26 (was 23), `claude plugin validate .` clean, and a live
end-to-end invocation via the exact `uv run --no-project` command
hooks.json now specifies.

- Task 1 (skeleton): DONE, reviewed, approved. `.claude-plugin/plugin.json`,
  `.mcp.json`, `server/main.py` (FastMCP stdio server, 3 stub tools),
  `server/requirements.txt`, `README.md`, `.gitignore`. Verified via
  direct MCP stdio round-trip (tools/list returns exactly
  search_lessons/save_lesson/list_lessons; each validates input and
  returns its placeholder) and `claude plugin validate .` (passes with
  only an expected missing-author warning). Full report:
  `.superpowers/sdd/task-1-report.md`.
  Review found one Important issue (server unlaunchable on a fresh
  checkout — original `.mcp.json` pointed at a gitignored, manually-built
  venv with no bootstrap) — fixed: `.mcp.json` now launches via
  `uv run --no-project --with-requirements server/requirements.txt
  server/main.py`, fully self-bootstrapping. README documents the `uv`
  prerequisite. Re-review: Approved.
  Note for later tasks: dev machines need `uv` installed
  (https://docs.astral.sh/uv/); there is no venv in the repo, `uv`
  manages its own cache.
- Task 2 (schema + scrub): DONE, reviewed, approved. `templates/
  LESSON_TEMPLATE.md`, `server/schema.py` (dataclass `Lesson`, hand-rolled
  YAML frontmatter — no pydantic/PyYAML dep), `server/scrub.py` (AWS
  keys, bearer tokens, sk- keys, connection strings, PEM blocks, labeled
  hex secrets, generic entropy catch-all), `server/tests/` (42 tests).
  `server/main.py` untouched, as required.
  Review found 2 Important issues, both fixed: (1) pure-hex exclusion
  let labeled hex secrets (`api_key: <40 hex chars>`) through unredacted
  — fixed w/ new `_LABELED_HEX_SECRET_RE`, context-gated like the AWS
  pattern, canonical digest lengths only (32/40/64), unlabeled hex still
  survives (git-SHA fix preserved); (2) hand-emitted YAML didn't escape
  newlines/control chars, corrupting round-trip — fixed, verified against
  full C0/DEL/NEL sweep. Re-review: Approved (42/42 tests, some minor
  test-assertion-rigor nits noted, non-blocking).
  Note for later tasks: `Lesson.tags` field exists on the schema backing
  "## Tags for retrieval" but has NO corresponding `save_lesson` tool
  parameter (matches the original spec's tool contract, which never
  listed a tags param either) — Task 4 must decide how the tags body
  section gets populated. Decision: auto-derive tags text from
  domain+error_signature+title keywords rather than adding a new
  save_lesson input param, to keep the tool contract exactly as
  specified.
- Task 3 (embedding index): DONE, reviewed, approved. `server/index.py`
  (fastembed `BAAI/bge-small-en-v1.5`, JSON index, cosine search,
  threshold 0.55), `server/schema.py` gained `parse_lesson()` (inverse of
  `render()` — resolved a real gap: Task 2 had no reader). Fixtures +
  tests in `server/tests/`. 65/65 tests pass.
  Review found 2 Important issues, both fixed: (1) body-section header
  matching used substring `.find()`, silently corrupting parse when free
  text contained a header-like substring mid-sentence — fixed w/
  line-anchored regex (`^header$`, MULTILINE); (2) `build_index` crashed
  entirely on one malformed lesson file — fixed w/ per-file try/except,
  bad files recorded in a `skipped: [{path, error}]` list in `index.json`
  instead of aborting the whole build; `embed()` failures still
  propagate (not swallowed). Re-review: Approved.
  Note for Task 4: `index.json` now has a `skipped` field — Task 4 should
  surface/check it (e.g. after `save_lesson` triggers a rebuild) rather
  than silently ignore it, since a systemic `parse_lesson` bug would
  otherwise route every lesson into `skipped` with build_index still
  reporting success.
- Task 4 (store + MCP wiring): DONE, reviewed, approved. `server/store.py`
  (write_lesson/read_lesson/list_lessons, id-collision-safe filenames),
  `server/main.py` fully wired: scrub → schema (tags auto-derived from
  domain+error_signature+title, scrubbed first) → store → index, real
  `${CLAUDE_PROJECT_DIR}`/`${CLAUDE_PLUGIN_DATA}` resolution, best-effort
  `git add` (no-ops safely if `.git` absent). 89/89 tests pass.
  Review found 1 Important issue, fixed: `search_lessons` returned
  silent `[]` on a freshly-cloned repo with committed-but-unindexed
  lessons (index cache is local-only, never git-committed) — fixed by
  building the index once on-demand when `index.json` is missing, before
  searching (never rebuilds an existing/stale index). Regression test
  simulates a teammate's already-committed lesson file with no local
  index and confirms it's found; implementer verified the test actually
  fails without the fix. Re-review: Approved.
  Known non-blocking edge case carried forward: a corrupt/unreadable
  existing `index.json` still crashes the tool call rather than
  degrading gracefully (pre-existing behavior, not introduced by this
  task) — fine to leave, a loud failure beats a silent empty result.
- Task 5 (/hindsight skill + list/prune): DONE, reviewed, approved.
  `skills/hindsight/SKILL.md` (subcommands save/search/list/prune,
  frontmatter verified against real installed plugins), `store.py`
  gained `delete_lesson`, `main.py` gained `prune_lesson` tool. 107/107
  tests pass.
  Review found 1 Important issue (security), fixed: `delete_lesson`/
  `prune_lesson` built a path from an unvalidated caller-supplied id with
  no containment check — an absolute-path or `../`-traversal id could
  delete arbitrary files outside `.debug-memory/lessons/`. Fixed w/ a
  single choke point `_resolve_lesson_path()` (store.py): name-only
  check (id must equal its own basename, reject `.`/`..`/empty) +
  resolved-parent check (defense in depth against symlink escapes).
  Invalid id raises `ValueError` (surfaces as a clean MCP tool error,
  verified against the actual installed SDK — doesn't crash the server).
  Swept `write_lesson`/`read_lesson`/`list_lessons`/`index.py` for the
  same bug class: none vulnerable (ids are always internally generated
  or already-constructed Path objects, never raw external strings).
  Re-review: Approved, hand-traced all attack shapes + verified live
  against the installed mcp SDK. Two cosmetic report-accuracy nits noted
  (non-blocking, no code impact).
- Task 6 (retrieval hook): DONE, reviewed, approved. `hooks/hooks.json`
  (`PostToolUseFailure`, no matcher, `timeout: 30`, plain `python3` via
  `${CLAUDE_PLUGIN_ROOT}` — stdlib-only, no `uv run` needed),
  `hooks/retrieve.py`. Payload schema independently verified against the
  raw hooks.md doc (not just a summarizer — a summarizing WebFetch of the
  same URL hallucinated two fields that don't exist in the real doc).
  5/5 tests pass.
  Review found 1 real bug + 1 design tension needing a human call, both
  resolved: (1) unguarded `sys.stdin.read()` crashed on non-UTF-8 bytes,
  silently killing the "unconditional nudge" guarantee — fixed via
  `sys.stdin.buffer.read().decode(errors="replace")`, non-raising by
  construction; (2) the spec's literal nudge text was imperative-phrased
  ("Before proposing a fix, call..."), and Claude Code's own hooks doc
  warns imperative phrasing can trigger prompt-injection defenses,
  causing Claude to surface the raw text instead of acting on it —
  would've silently neutered the whole hook. User chose to rephrase
  factually (kept in AskUserQuestion, not silently resolved). Final text
  (323 chars): "A tool call just failed. hindsight search_lessons can
  surface past team lessons on similar errors, including approaches that
  didn't work. A relevant result is worth checking before proposing a
  fix; treat its fix as a hypothesis, not gospel, since the codebase may
  have changed. Low-relevance results aren't worth acting on." Re-review:
  Approved.
  Note for Task 7: apply the SAME factual-not-imperative phrasing rule to
  the `Stop` hook's capture nudge — plan text already updated
  accordingly (see Task 7 section).
- Task 7 (capture: marker + Stop hook + lesson-distiller): DONE, reviewed,
  approved. `hooks/mark_error.py` (writes `session-<id>.marker` to
  `${CLAUDE_PLUGIN_DATA}` on any tool failure, runs alongside
  `retrieve.py` under the same `PostToolUseFailure` entry — both fire,
  Task 6 untouched/still passing), `hooks/capture.py` (`Stop` hook, true
  no-op when no marker, exact factual-phrased nudge when one exists),
  `agents/lesson-distiller.md` (builds save_lesson's full payload from a
  dispatch-prompt summary, confidence defaults to probable unless
  verified, never fabricates failed-approaches, excludes secrets on top
  of server-side scrub.py). 22/22 hook tests, 116/116 server tests.
  Review found 1 Important issue, fixed: `lesson-distiller.md` deleted
  the marker via `Bash rm -f "${CLAUDE_PLUGIN_DATA}/..."`, but that env
  var is only exported to hook/MCP/LSP subprocesses, NOT to a dispatched
  agent's Bash tool (confirmed via live docs + a filed GH issue on the
  sibling CLAUDE_PROJECT_DIR var) — var expanded empty, `rm -f` silently
  no-op'd, marker never cleared, Stop nudge would've re-fired every turn
  for the rest of the session even after a lesson was saved. Fixed by
  moving deletion into a new MCP tool, `clear_capture_marker(session_id)`
  in `server/main.py` (reuses `_cache_dir()`, same containment-check
  pattern as `prune_lesson`/`_resolve_lesson_path`, same session_id
  sanitization regex as `mark_error.py` — verified byte-identical via a
  cross-process test that runs the real hook script and confirms the MCP
  tool finds/deletes the exact file it wrote). `Bash` removed from the
  distiller's tool grant entirely. Re-review: Approved, hand-traced
  filename construction on both sides + reran all suites live.
- Task 8 (distribution): DONE, reviewed, approved (no Important/Critical
  findings — only cosmetic/DRY Minor nits). Reviewer independently
  re-verified every claim: reran `claude plugin validate .` (same clean
  pass), reproduced the `.claude-plugin/marketplace.json`-path
  requirement and the `owner`-required-field error live, byte-diffed the
  README's architecture diagram and one-liner against the real spec
  text, diffed all 12 shared `main.py` functions against the Task 7
  baseline (byte-identical — only `reindex_lessons` is net-new), and did
  a live 6-tool MCP stdio round-trip. `.claude-plugin/marketplace.json`
  (single-plugin marketplace pointing `source: "./"` at this repo,
  plugin marketplace pointing `source: "./"` at this repo, shape verified
  against the real installed `gatecheck`/`claude-plugins-official`
  marketplaces — confirmed empirically that `claude plugin validate`
  requires `.claude-plugin/marketplace.json`, not a bare root-level file,
  despite the brief's looser "repo root" phrasing; `owner.name` is
  required by the schema, `owner.url` is not — left `url` out rather than
  fabricate a repo URL that doesn't exist yet). `README.md` fully
  rewritten (context-economics pitch and one-liner from the spec text
  used verbatim, architecture diagram copied byte-for-byte and verified
  programmatically against the source text, install instructions, tool
  surface table, demo-GIF placeholder that doesn't claim a GIF exists).
  `server/main.py` gained one new additive tool, `reindex_lessons()`
  (full `index.build_index` rebuild, returns `{indexed, skipped,
  lessons_dir, index_path}`) — the 5 existing tools' bodies untouched.
  `server/reindex.py` (new): standalone CLI (`uv run --no-project
  --with-requirements server/requirements.txt server/reindex.py
  [--lessons-dir DIR] [--cache-dir DIR]`) for reindexing outside a live
  session. `skills/hindsight/SKILL.md` gained a `/hindsight reindex`
  subcommand. 120/120 server tests pass (116 + 4 new), 22/22 hook tests
  unchanged (hooks not touched, out of scope). `claude plugin validate .`
  passes with only the same pre-existing, expected `author` warning from
  Task 1 — nothing new flagged.
  Key judgment call: `/hindsight reindex` calls the new `reindex_lessons`
  MCP tool, NOT the standalone `server/reindex.py` CLI via the `Bash`
  tool — `${CLAUDE_PLUGIN_DATA}` (the real index-cache location) is only
  reliably exported to a hook process or an MCP/LSP server subprocess,
  not to a `Bash`-tool invocation mid-session (the exact bug class Task
  7's `clear_capture_marker` fix already found and fixed once for marker
  deletion). A Bash-invoked reindex would silently rebuild an index at
  the wrong path — one `search_lessons` never reads from — while still
  reporting a plausible "N lessons indexed" success. Running the rebuild
  inside the MCP server process itself (same pattern as
  `clear_capture_marker`) avoids that failure mode entirely.
  `server/reindex.py` still exists as a genuinely useful, separately
  documented lower-level entry point (CI, manual terminal use, or
  explicit `--lessons-dir`/`--cache-dir` for testing) — verified
  end-to-end against a 3-fixture scratch directory (reports "Reindexed 3
  lesson(s)", and a subsequent `index.search` call against the rebuilt
  cache correctly finds and ranks the matching lesson first).
  Full report: `.superpowers/sdd/task-8-report.md`.

## Final whole-plugin review (after all 8 tasks) — DONE, reviewed, approved

Dispatched on the most capable model per process (opus), full source
package (no git diff possible). Found what no single task's scope could:
2 real cross-cutting bugs, both fixed and re-verified live:

- **C1 (Critical):** `${CLAUDE_PLUGIN_DATA}` is per-plugin-*per-machine*,
  not per-project (confirmed against real on-disk layout + the official
  `project-artifact` skill's own self-partitioning precedent) —
  `_cache_dir()` pointed straight at it with no project component, so
  two repos on one machine silently shared/thrashed one `index.json`:
  Project B's `search_lessons` could return Project A's lessons with
  paths into Project A's repo, contradicting `list_lessons`. Fixed:
  `_project_slug()` (sha256 hash + readable basename of
  `CLAUDE_PROJECT_DIR`) added identically to `server/main.py`,
  `hooks/mark_error.py`, `hooks/capture.py`; `_cache_dir()` now returns
  `${CLAUDE_PLUGIN_DATA}/<slug>/`. Markers moved under the same
  per-project subdir. Regression test: two different `CLAUDE_PROJECT_DIR`
  values sharing one `CLAUDE_PLUGIN_DATA` — the exact shape no per-task
  suite could express. Re-review hand-traced slug generation
  byte-for-byte across all three files at runtime — identical.
- **I1 (Important):** `capture.py`'s Stop-hook nudge never actually
  included `session_id` in the emitted text, so the lesson-distiller
  agent (dispatched later, in a fresh context) had no reliable way to
  know which session's marker to clear via `clear_capture_marker` — same
  failure class as Task 7's original bug (nudge re-fires forever), via a
  different gap. Fixed: nudge text now interpolates the real session_id;
  verified no JSON-injection risk (whole payload goes through
  `json.dumps`).
- **I2 (Important, bundled in):** `index.json` writes were
  truncate-then-write, not atomic — a concurrent reader mid-rebuild could
  see truncated JSON and crash a tool call. Fixed via `tempfile.mkstemp`
  (same directory, same filesystem) + `os.replace`.
- **I4 (Important, latent/fallback-only, bundled in):** hooks and server
  used different fallback directory names when `CLAUDE_PLUGIN_DATA` is
  unset, so `clear_capture_marker` could never find a hook-written marker
  in that path (never hit in a real install — both sides always get the
  same env var together — but real in standalone/test runs). Fixed:
  canonical `.hindsight-cache` fallback leaf, identical in all three
  files.
- **M1 (Minor, bundled in):** `index.search()` now checks the stored
  `model`/`dim` against the pinned constants and self-heals (deletes a
  stale/foreign index, returns `[]`, next `search_lessons` call rebuilds
  on-demand) instead of silently comparing mismatched-dimension vectors.
- **Explicitly deferred, not fixed:** I3 (full re-embed on every
  save/prune doesn't scale past ~hundreds of lessons — real but bounded;
  README's "500-lesson library" pitch would want an incremental-save path
  eventually), M2 (write_lesson's TOCTOU id-collision check — already an
  accepted residual risk from Task 4), M3 (session_id
  sanitize-vs-reject asymmetry across hooks vs. the MCP tool — assessed
  as intentional defense-in-depth, not a bug).

Both suites green after the fix: server 128/128 (was 120), hooks 23/23
(was 22). Re-review: Approved.

**All 8 tasks + the final whole-plugin pass are complete and approved.
The plugin is functionally done.** Remaining before real-world use is
purely operational, not a code task: `git init` this repo (blocked all
session — user said no git ops), confirm/replace `marketplace.json`'s
inferred `owner.name`, and eventually record the demo GIF. I3 (scaling
past ~hundreds of lessons) is a known, documented follow-up, not a
blocker for early use.
