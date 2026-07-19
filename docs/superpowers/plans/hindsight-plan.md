# Hindsight — Implementation Plan

Source spec: user-provided Hindsight build doc (2026-07-18). This plan
breaks the spec's phases into concrete, independently-dispatchable tasks
for subagent-driven-development.

## Environment note (binding for every task)

**No git.** This working tree is not a git repository and no task may run
any `git` command (init, add, commit, diff, worktree, etc). Implementers
write/edit files directly with no VCS. The controller tracks progress via
`docs/superpowers/plans/progress.md`, not commit hashes. Task review
packages are built by concatenating the task's touched files (with
headers), not `git diff`.

**Placeholder variables are literal.** Wherever the spec shows
`${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, or `${CLAUDE_PROJECT_DIR}`,
write that exact literal string into `.mcp.json` / `hooks.json` / code —
these are Claude Code's own runtime substitution variables, resolved by
the harness at load time in whatever machine installs the plugin. Do NOT
hardcode any path from this build machine.

## Global Constraints (apply to every task, copy verbatim into reviewer prompts)

- Repo root: `/Users/ilaakshmishra/Documents/hindsight` (plugin repo itself;
  lessons are NOT stored here — they live in each *consuming* team's repo
  under `.debug-memory/lessons/`).
- Plugin name: `hindsight`.
- MCP server language: **Python**.
- Local embeddings: **fastembed**, model **`BAAI/bge-small-en-v1.5`**
  (384-dim). Pin this exact model string everywhere it's referenced so
  every teammate's index is byte-compatible.
- Lesson folder: `.debug-memory/lessons/` at the consuming repo's root,
  path built from `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`.
- Index cache: `${CLAUDE_PLUGIN_DATA}` (rebuildable from the markdown
  lessons at any time — never treat it as source of truth).
- Lesson schema: YAML frontmatter (`id`, `title`, `domain[]`,
  `error_signature`, `created_at`, `confidence: confirmed|probable`) +
  markdown body sections `## Symptom`, `## Approaches that FAILED (do not
  repeat)`, `## Root cause`, `## Fix`, `## Tags for retrieval`. Match text
  built from `title` + `error_signature` + `domain` + retrieval tags —
  never raw stack traces with file paths/line numbers.
- `search_lessons(query: str, k: int = 3)` → array of
  `{ id, title, score, failed_approaches, root_cause, fix, path }`, empty
  list if nothing clears the similarity threshold (never return a weak
  match dressed as strong).
- `save_lesson(title, domain[], error_signature, symptom,
  failed_approaches[], root_cause, fix, confidence)` → scrub secrets →
  render via template → write to `.debug-memory/lessons/` → update index
  → **stage with git if a repo exists, never auto-commit** → return
  `{ id, path, wrote: true }`.
- Secrets never written: regex pass (AWS keys, bearer tokens, `sk-`
  style keys, connection strings, private key blocks, long high-entropy
  strings) runs inside `save_lesson` before anything touches disk.
- No task may add scope beyond its brief (no auth, no cloud sync, no
  extra tools) — this is a local-first, git-native plugin.

---

## Task 1: Plugin skeleton + empty MCP server

Create the plugin manifest and an MCP server that starts, registers, and
exposes empty tool stubs — verifiable end to end before any real logic
exists.

Files:
- `.claude-plugin/plugin.json` — manifest: name `hindsight`, version
  `0.1.0`, description (use the README one-liner from the spec), and
  whatever fields Claude Code plugin manifests require (check an existing
  installed plugin's `plugin.json` under
  `/Users/ilaakshmishra/.claude/plugins/cache/` for the exact required
  shape before inventing fields).
- `.mcp.json` — registers the server. Command must launch
  `${CLAUDE_PLUGIN_ROOT}/server/main.py` (literal string, not resolved).
  Use a `python3` (or `uv run`) command array. Working directory should
  not be assumed; use absolute paths built from the plugin-root variable.
- `server/main.py` — MCP server (use the official `mcp` Python SDK,
  `pip install mcp`) exposing three tool stubs: `search_lessons`,
  `save_lesson`, `list_lessons`. Each stub validates its input schema and
  returns a hardcoded placeholder response (no real storage/embedding
  logic yet — that's Task 2). Server must start over stdio per the MCP
  Python SDK's standard pattern.
- `server/requirements.txt` (or `pyproject.toml`, implementer's choice,
  document which) pinning `mcp`, `fastembed`.
- `README.md` — stub with the one-line summary from the spec (section 13)
  and a "status: skeleton only" note; will be filled out in Task 8.

Verification: document in the report exactly how you confirmed the server
starts and lists its 3 tools (e.g. `claude --plugin-dir . ` then
inspecting available tools, or the MCP SDK's own stdio test harness /
`mcp dev` if installed). If `claude` CLI plugin loading can't be exercised
headlessly, a direct stdio round-trip test (send `tools/list`, assert 3
tools returned) is an acceptable substitute — state which you used.

---

## Task 2: Lesson schema + secret scrubber

Pure-logic modules, no MCP wiring yet. Fully unit-testable in isolation.

Files:
- `server/schema.py` — the lesson data model (dataclass or pydantic) with
  fields exactly matching Global Constraints' schema list, plus a
  `render()` method producing the markdown+frontmatter document matching
  `templates/LESSON_TEMPLATE.md` (create that template file too, copying
  the shape from the spec's section 5 example).
- `server/scrub.py` — `scrub(text: str) -> str` (or scrub a whole payload
  dict) redacting: AWS access/secret keys, generic bearer tokens, `sk-`
  prefixed API keys, DB connection strings (`postgres://user:pass@...`
  etc), `-----BEGIN...PRIVATE KEY-----` blocks, and long
  (>=32-char) high-entropy tokens. Redact in place with a `[REDACTED]`
  marker; never silently drop the surrounding sentence.

Tests (pytest, in `server/tests/`):
- `test_schema.py`: round-trip a lesson through `render()`, assert every
  required frontmatter field and body section is present and correctly
  formatted.
- `test_scrub.py`: feed payloads seeded with fake AWS keys, a fake
  `sk-...` key, a fake bearer token, a fake Postgres connection string,
  and a fake PEM private key block. Assert none survive in the scrubbed
  output. Also assert ordinary technical prose (stack traces, code,
  normal sentences) passes through unmodified.

This task has no MCP dependency — implementer should NOT touch
`server/main.py`.

---

## Task 3: Local embedding index + similarity search

**Gap found after Task 2 landed:** `server/schema.py` only writes lessons
(`Lesson.render()`) — there is no function to parse a lesson `.md` file
back into a `Lesson` (or at least its frontmatter + `match_text()`
inputs). Both this task's `build_index` and Task 4's `store.read_lesson`
need that. Add it once, in `schema.py` (natural owner of the `Lesson`
model — the inverse of `render()`), as part of this task:
- `parse_lesson(text: str) -> Lesson` (module-level function or
  `Lesson.from_markdown` classmethod, your call) — parses the YAML
  frontmatter block + the 5 body sections back into a `Lesson`. Reuse a
  real YAML parser for reading (safe to add `PyYAML` as a dependency for
  *parsing* even though Task 2 hand-rolled *emission* — document why in
  your report if you do). Round-trip test: `parse_lesson(lesson.render())
  == lesson` for a handful of fixture lessons including one with the
  escaped-character edge cases Task 2's fix handled (embedded newline in
  title, etc).
- Task 4 will call this from `store.read_lesson` — do not build a second,
  divergent parser there later; this is the one parser.

Files:
- `server/index.py` — wraps fastembed with model
  `BAAI/bge-small-en-v1.5`. Functions: `embed(text: str) -> list[float]`,
  `build_index(lessons_dir: Path, cache_dir: Path)` (reads all lesson
  markdown files, embeds each lesson's match text — title +
  error_signature + domain + retrieval tags per Global Constraints —
  and writes a flat vector file: e.g. a JSON or `.npy` array of
  `{id, path, vector}` records to `cache_dir`), `search(query: str,
  cache_dir: Path, k: int, threshold: float) -> list[dict]` (embeds the
  query, cosine-similarity against the cached vectors, returns top-k
  above threshold sorted descending by score, empty list if none clear
  threshold).
- Pick and document a default similarity threshold (implementer's
  judgment — start around cosine 0.5–0.6, document the reasoning in the
  report; this gets tuned empirically in Task 8's matching tests).
- Index format must be rebuildable from the markdown lessons alone at any
  time (no information lives only in the index).

Tests (`server/tests/test_index.py`): build an index from 3–4 fixture
lesson files (write small fixture `.md` lessons matching the schema
in a test-local `fixtures/` dir), assert a query closely matching one
lesson's title/tags ranks that lesson first, and assert a clearly
unrelated query returns an empty list (nothing clears threshold).

This task has no MCP dependency — implementer should NOT touch
`server/main.py`. It may depend on `server/schema.py` from Task 2 for
reading lesson frontmatter (Task 2 must be complete first — sequence
after Task 2).

---

## Task 4: Wire real store.py + MCP tool logic

Now connect everything: replace Task 1's stub tools with real behavior,
using Task 2's schema/scrub and Task 3's index.

Files:
- `server/store.py` — `write_lesson(payload, lessons_dir) -> Path`
  (renders via `schema.py`, writes the `.md` file, filename convention
  `<id>.md` where `id` is a slugified `YYYY-MM-DD-short-slug` per the
  spec's example), `read_lesson(path) -> dict`, `list_lessons(lessons_dir)
  -> list[dict]`.
- Update `server/main.py`:
  - `search_lessons(query, k=3)`: calls `index.search`, returns the
    exact output shape from Global Constraints (`id, title, score,
    failed_approaches, root_cause, fix, path`).
  - `save_lesson(...)`: scrub payload via `scrub.py` → build lesson via
    `schema.py` → write via `store.py` → call `index.build_index` (or an
    incremental single-lesson add if you designed one in Task 3 — either
    is fine, document which) to update the cache → `git add` the new
    file **only if `.git` exists in the lessons repo** (check with
    `Path(lessons_dir).parent / ".git"` or `git rev-parse` wrapped in a
    try/except that no-ops if git isn't present or isn't on PATH — never
    error the tool call because git is absent) → return `{id, path,
    wrote: true}`.
    **Note (from Task 3 review):** `build_index` now returns/writes a
    `skipped: [{path, error}]` list in `index.json` for lesson files that
    failed to parse, instead of aborting the whole build. `save_lesson`
    must check this after rebuilding and surface it somehow (e.g. append
    a `warnings` field to `save_lesson`'s own return value if `skipped`
    is non-empty right after this save) rather than silently ignoring
    it — a systemic `parse_lesson` bug would otherwise look like success
    while quietly excluding every lesson from search.
  - `list_lessons()`: returns `store.list_lessons`.
- **Tags decision (resolved during Task 2 review):** `schema.py`'s
  `Lesson.tags` field backs the mandatory "## Tags for retrieval" body
  section, but `save_lesson`'s input contract (Global Constraints above)
  has no `tags` parameter — matching the original spec's tool contract,
  which never listed one either. Do NOT add a new `tags` param to
  `save_lesson`. Instead, auto-derive the tags text from
  `domain + error_signature + title` keywords (dedupe, lowercase,
  whitespace-joined is sufficient — this feeds `match_text()`, not a
  human-curated field) when constructing the `Lesson` in `save_lesson`.
- Determine the lessons directory at runtime from
  `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/` (read the env var the
  MCP server actually receives at runtime — confirm in the MCP Python SDK
  docs/README how server-side code reads variables Claude Code injects at
  launch; if the SDK doesn't auto-expand `${CLAUDE_PROJECT_DIR}` into the
  process env, read it directly via `os.environ`). Create the directory
  if missing.

Tests: extend `server/tests/` with an integration test that calls
`save_lesson` three times with distinct fixture payloads (one seeded with
a fake secret to confirm it's scrubbed on the way to disk), then calls
`search_lessons` with a query matching one of them and asserts it's
returned; asserts a save with a fake AWS key never appears in the written
`.md` file's contents (read the file back, grep for the fake key,
assert absent).

Sequence: after Tasks 2 and 3.

---

## Task 5: `/hindsight` manual skill + list/prune tools

Files:
- Add `prune_lesson(id: str) -> {deleted: bool}` to `server/main.py` /
  `store.py` (deletes the `.md` file, rebuilds the index).
- `skills/hindsight/SKILL.md` — a skill (slash command `/hindsight`) with
  subcommands: `/hindsight save` (walks the user through providing the
  save_lesson fields, calls the tool), `/hindsight search <query>` (calls
  search_lessons, prints results with scores), `/hindsight list` (calls
  list_lessons), `/hindsight prune <id>` (confirms, then calls
  prune_lesson). Follow this plugin repo's existing skill file
  conventions if any exist yet (there won't be — base it on the
  `SKILL.md` frontmatter shape used by other installed plugins under
  `/Users/ilaakshmishra/.claude/plugins/cache/*/skills/*/SKILL.md` —
  read one for the exact frontmatter fields expected, e.g. `name`,
  `description`).

Tests: extend `server/tests/` for `prune_lesson` (save a fixture lesson,
prune it, assert the file is gone and the index no longer returns it for
a previously-matching query).

Sequence: after Task 4.

---

## Hook-event correction (binding — supersedes spec section 7)

Verified 2026-07-18 against https://code.claude.com/docs/en/hooks.md:

- `PostToolUseFailure` **is** a real event (fires after a tool call
  fails) — use it directly, no need to inspect `PostToolUse` for errors.
- `SessionEnd` does **not** support `hookSpecificOutput.additionalContext`
  — it's cleanup/logging only, no live model turn left to act on
  anything injected. **Do not use it for capture.**
- `Stop` **does** support `additionalContext` ("the conversation
  continues so Claude can act on the feedback") — this is the correct
  event for the capture nudge, not `SessionEnd`.
- `UserPromptSubmit` supports `additionalContext` too (available if a
  future task wants prompt-side pattern matching, per spec's optional
  mention — not required for Phase 3/4 below).

`hookSpecificOutput` JSON shape for all of the above:
```json
{"hookSpecificOutput": {"hookEventName": "<EventName>", "additionalContext": "..."}}
```
exit code 0.

Matcher syntax in `hooks.json` (for `PostToolUseFailure`/`PostToolUse`):
exact tool name (`"Bash"`), list (`"Edit|Write"`), regex (`"^Notebook"`),
or MCP pattern (`"mcp__servername__.*"`).

---

## Task 6: Automatic retrieval hook (Phase 3)

Files:
- `hooks/hooks.json` — register a `PostToolUseFailure` hook (matcher: all
  tools, i.e. no matcher restriction, since an error can come from any
  tool — Bash, Edit, a build command, etc). Hook script path uses
  `${CLAUDE_PLUGIN_ROOT}` literal.
- `hooks/retrieve.py` (or `.sh`, implementer's choice — Python
  recommended for consistency with the server) — reads the hook's JSON
  stdin payload, and unconditionally (every tool failure) emits on
  stdout:
  ```json
  {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": "A tool call just failed. hindsight search_lessons can surface past team lessons on similar errors, including approaches that didn't work. A relevant result is worth checking before proposing a fix; treat its fix as a hypothesis, not gospel, since the codebase may have changed. Low-relevance results aren't worth acting on."}}
  ```
  exit code 0. Keep the string under a few hundred characters — this
  fires on every failure, so it must stay cheap. Do NOT try to pre-filter
  "is this error-like" here; `PostToolUseFailure` already only fires on
  genuine tool failures.

  **Phrasing rationale (decided after Task 6 review):** Claude Code's
  hooks doc warns imperative-phrased `additionalContext` ("Before
  proposing a fix, call...") can trigger Claude's own prompt-injection
  defenses, causing it to surface the raw text to the user instead of
  acting on it — which would silently defeat this entire hook. Text
  above is deliberately factual/descriptive, not imperative, while
  preserving the same intent (check search_lessons, weigh relevance,
  treat fix as hypothesis, ignore weak matches). Apply this same
  factual-not-imperative phrasing rule to Task 7's `Stop` hook nudge
  below — it was written before this was discovered and needs the same
  treatment.
- No MCP call happens inside the hook itself — the hook only nudges;
  Claude (which sees the injected context on its next turn) decides
  whether and how to call `search_lessons`.

Test: a standalone script test (not needing a live Claude session) that
pipes a fabricated `PostToolUseFailure` JSON payload (matching the real
schema — check the doc's example payload shape) into the hook script and
asserts the exact `additionalContext` JSON is emitted on stdout with exit
0.

Sequence: independent of Tasks 1-5's Python server internals (only needs
the `search_lessons` tool name to exist, which Task 1 already stubs) —
may be dispatched any time after Task 1.

---

## Task 7: Automatic capture — session marker, Stop hook, lesson-distiller agent (Phase 4)

Files:
- `hooks/hooks.json` — add two more entries:
  1. `PostToolUseFailure` hook (can reuse or extend `retrieve.py`, or a
     separate `hooks/mark_error.py`) that, in addition to Task 6's
     retrieve nudge, writes a per-session marker file to
     `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (session_id from
     the hook payload's `session_id` field). Content doesn't matter, only
     existence. This must not fail or block if the directory doesn't
     exist yet — create it.
  2. `Stop` hook: `hooks/capture.py`. Reads the same `session_id` from
     its payload, checks whether
     `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` exists. If not,
     exit 0 with no output (no-op — nothing to capture). If it exists,
     emit:
     ```json
     {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "This session hit a tool failure earlier. If it's now resolved, the lesson-distiller agent (subagent_type: lesson-distiller) can turn it into a saved lesson from a concise summary — error signature, symptom, failed approaches, root cause, fix, with secrets/tokens/customer data excluded. Not worth dispatching if the error wasn't actually resolved this session."}}
     ```
     (Phrased factually, not imperatively, per the Task 6 correction above
     — same reasoning: an imperative "dispatch the agent... exclude
     secrets..." risks triggering Claude's prompt-injection defenses and
     getting surfaced as raw text instead of acted on.)
     Do NOT delete the marker file from inside this hook — deletion must
     only happen after a real save, so an unresolved session's next
     `Stop` firing (if the session continues) can still trigger capture
     once it IS resolved. Deletion of the marker is the distiller agent's
     job (see below), not the hook's.
- `agents/lesson-distiller.md` — a plugin-provided subagent (frontmatter:
  `name: lesson-distiller`, `description`, tool access limited to
  whatever's needed to call the `hindsight` MCP tools plus `Read` if it
  needs to re-check anything). Body instructs it to: take the incident
  summary it was dispatched with, structure it into the exact
  `save_lesson` input shape from Global Constraints (title, domain[],
  error_signature, symptom, failed_approaches[], root_cause, fix,
  confidence — mark `probable` unless the fix was actually verified
  working), never fabricate a failed-approach that wasn't actually tried,
  never include secrets/tokens/customer data (belt-and-suspenders on top
  of server-side `scrub.py`), call `save_lesson`, then delete the
  session's marker file at `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`
  (the session_id is passed to it in the dispatch prompt) so a later
  `Stop` in the same session doesn't re-trigger.

Tests:
- `hooks/tests/test_mark_and_capture.py` (or shell-based, implementer's
  choice): simulate `PostToolUseFailure` → assert marker file created;
  simulate `Stop` with that session_id → assert the capture
  `additionalContext` is emitted; simulate `Stop` with a session_id that
  has no marker → assert stdout is empty / no `additionalContext` (the
  no-op case from spec section 10's "no-op tests").

Sequence: after Task 6 (shares hook plumbing) and after Task 4 (the agent
dispatches `save_lesson`, which must be real by then).

---

## Task 8: Distribution (Phase 5)

Files:
- `marketplace.json` at repo root, following whatever schema Claude Code
  plugin marketplaces require (check an existing marketplace.json from
  an installed plugin under `/Users/ilaakshmishra/.claude/plugins/cache/`
  or `/Users/ilaakshmishra/.claude/plugins/` for the exact shape before
  inventing fields) — points at this repo, lists the `hindsight` plugin.
- `README.md` — replace Task 1's stub with the full version: the
  context-economics pitch (spec section 1, condensed), one-line install
  instructions (`/plugin marketplace add ...`, `/plugin install
  hindsight`), the architecture diagram from spec section 3, and a
  placeholder note for where a demo GIF will go (do not fabricate a GIF).
- A `hindsight reindex` command: decide and document whether this is a
  `/hindsight reindex` SKILL.md subcommand (extends Task 5's skill) or a
  standalone CLI entry point (`server/reindex.py` callable via
  `python3 -m server.reindex`) — implementer's judgment, but it must call
  `index.build_index` over the full `.debug-memory/lessons/` directory
  from scratch (full rebuild, not incremental) and report how many
  lessons were indexed.
- Run `claude plugin validate` (or document exactly why it couldn't be
  run in this environment) against the repo and report the result in the
  task report; fix any validation errors it surfaces.

Sequence: last — after all other tasks.

