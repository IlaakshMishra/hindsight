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

