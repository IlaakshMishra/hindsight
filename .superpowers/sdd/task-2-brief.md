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

