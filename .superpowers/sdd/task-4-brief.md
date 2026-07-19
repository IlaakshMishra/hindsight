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

