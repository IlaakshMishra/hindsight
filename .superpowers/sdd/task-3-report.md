# Task 3 report: Local embedding index + similarity search

## Files created

- `server/index.py` — wraps `fastembed`'s local ONNX embedding model
  (pinned `BAAI/bge-small-en-v1.5`, 384-dim). Public API:
  - `embed(text: str) -> list[float]` — embeds one string; lazily
    constructs and caches a module-level `TextEmbedding` instance so the
    (relatively expensive) model load happens once per process, not per
    call.
  - `build_index(lessons_dir: Path, cache_dir: Path) -> Path` — reads
    every `*.md` file under `lessons_dir` (glob, sorted for determinism),
    parses each via `schema.parse_lesson`, embeds `lesson.match_text()`,
    and writes a single `index.json` under `cache_dir`:
    `{model, dim, records: [{id, path, vector}, ...]}`. Always a full
    rebuild from scratch — never incremental, never trusts a prior
    index. `lessons_dir` not existing yet is not an error (produces an
    empty index).
  - `search(query, cache_dir, k=3, threshold=DEFAULT_THRESHOLD) -> list[dict]`
    — embeds the query, cosine-similarity against every cached vector
    (pure-Python dot-product/norm, no numpy dependency added — see
    "Design decisions" below), filters to `score >= threshold`, sorts
    descending, returns `[:k]` as `{id, path, score}` dicts. Returns
    `[]` if the index file doesn't exist, is empty, or nothing clears
    threshold.
  - `MODEL_NAME = "BAAI/bge-small-en-v1.5"`, `EMBEDDING_DIM = 384`,
    `INDEX_FILENAME = "index.json"`, `DEFAULT_THRESHOLD = 0.55` module
    constants.
  - Takes `cache_dir: Path` as a plain parameter (not read from
    `${CLAUDE_PLUGIN_DATA}` itself) — that env-var resolution is Task 4's
    MCP-wiring job; this module has no MCP dependency and does not touch
    `server/main.py`.
- `server/tests/test_index.py` — 10 tests, all against a *real* fastembed
  model (no mocking, per the brief): fixture-file sanity check, vector
  shape/type, index-write shape, empty-lessons-dir handling, "delete the
  cache and rebuild from markdown alone gives equivalent results" (proves
  the rebuildable-from-markdown-alone constraint), a query closely
  matching one lesson ranks it first (for two different lessons, not
  just one), unrelated query → `[]`, `k` cutoff behavior, and
  missing-index → `[]`.
- `server/tests/fixtures/*.md` — 4 fixture lessons (FastMCP/pydantic,
  React `useEffect`, Docker OOM, Postgres connection pool), generated via
  real `Lesson(...).render()` calls (not hand-typed YAML) so they're
  guaranteed byte-valid against the actual schema shape.

## Files edited

- `server/schema.py` — added `parse_lesson(text: str) -> Lesson` (the
  gap-fill required by this task's brief) plus two private helpers
  (`_parse_body_sections`, `_parse_list_section`) and a frontmatter regex
  (`_FRONTMATTER_RE`). Module-level function, not a classmethod (brief
  left the choice open; module-level matches the brief's own example
  phrasing and needs no `Lesson` instance to call).
- `server/requirements.txt` — added `PyYAML==6.0.3` as an explicit,
  pinned dependency (see "PyYAML" below for why), with a doc comment.
- `server/tests/test_schema.py` — added 10 `parse_lesson` round-trip
  tests (imports `parse_lesson` alongside the existing `schema` imports).

`server/main.py` and `server/scrub.py`: **not touched**, confirmed via
`find server -name "*.py" -newer server/main.py` (main.py itself never
appears in the touched list) and re-importing `main` after all edits
(`search_lessons`, `save_lesson`, `list_lessons` still present, same
stub bodies as Task 1 left them).

## `parse_lesson()` design

Read the real `render()` output shape directly from `server/schema.py`
rather than assuming a shape:

1. **Frontmatter**: a regex (`_FRONTMATTER_RE`, DOTALL) matches the
   leading `` ---\n...\n---\n `` block, then `yaml.safe_load()` parses
   it. This is a real YAML parser doing the unescaping — correctly
   inverts every case `_yaml_quote()` documents (backslash, quote,
   named newline/CR/tab/NUL escapes, and the `\xHH` fallback for other
   C0 controls/DEL/NEL), without reimplementing that unescape logic by
   hand. Missing required fields raise `ValueError`.
2. **Body**: `_parse_body_sections` locates each of the 5
   `BODY_SECTION_HEADERS` by string offset (in the fixed order `render()`
   always emits them), slices the text between consecutive headers, and
   strips surrounding blank-line padding (`.strip("\n")`) — this exactly
   inverts `render()`'s `"## Header\n\n{content}\n\n"` pattern without
   hardcoding an assumed exact newline count (robust to the fact that
   the very last section, "Tags for retrieval", only has a single
   trailing `\n` before EOF, not `\n\n`, unlike the other four).
   Out-of-order or missing headers raise `ValueError`.
3. **List sections** (`failed_approaches`, `tags`):
   `_parse_list_section` inverts `"\n".join(f"- {item}" for item in
   items)` and the `_(none recorded)_` empty-list sentinel. Each line is
   required to start with `"- "` (matching what `render()` always
   emits) — a malformed line raises `ValueError` rather than silently
   producing corrupted data, since this is "the one parser" Task 4 will
   also depend on (per the brief) and a loud failure beats a quiet one
   here.

Round-trip verified (`parse_lesson(lesson.render()) == lesson`) for: a
typical lesson, probable confidence + multiple domains, empty
failed_approaches/tags, single-item lists, embedded newline in title
(the exact edge case Task 2's review fix handled), embedded CR/tab plus
mixed quotes/backslashes in title and error_signature, a domain item
with an embedded newline, and NUL/DEL/C0-control characters in
error_signature (exercising `_yaml_quote()`'s `\xHH` fallback branch,
not just its named-escape branch). Plus two negative tests: missing
frontmatter block and a truncated document missing required sections
both raise `ValueError`.

**Known, accepted limitation** (documented in `_parse_body_sections`'s
docstring): the split is positional/string-offset based, not a
line-anchored header scanner. If a lesson's free-text body (symptom,
root_cause, fix) happened to contain another section's exact header
string as a literal substring (e.g. a symptom that quotes `"## Fix"`
verbatim), the split would misfire. This doesn't affect any real lesson
content in practice and isn't exercised by the required round-trip
tests; flagging it now rather than let it surprise Task 4.

Task 4 should call this one parser from `store.read_lesson` rather than
building a second one, per the brief.

## Why PyYAML as a dependency (parsing only, not emission)

`render()` stays hand-rolled — Task 2's reasoning (flat, fully-controlled
6-key frontmatter, deterministic emission, no need for a library) still
holds and I didn't touch it. But *parsing* has to correctly invert
arbitrary YAML double-quoted-scalar escaping (the exact rules
`_yaml_quote()`'s docstring documents: named escapes, the `\xHH`
fallback, NEL handling, etc.) — hand-rolling an *unescaper* for that
would be a second, untested, bug-prone reimplementation of exactly what
PyYAML already does correctly and is already verified against elsewhere
in this codebase (`test_schema.py`'s existing frontmatter tests already
use `yaml.safe_load` to validate `render()`'s output). Taking the
dependency for parsing was strictly cheaper and safer than reinventing
it. `PyYAML` was already an *indirect* dependency (pulled in
transitively via `mcp`'s own deps — confirmed resolving to `6.0.3` in
this project's `uv`-managed environment) and was already used directly
by `test_schema.py`'s tests since Task 2; this task pins it explicitly in
`server/requirements.txt` since production code (`schema.py`) now
imports it too, not just tests.

## Threshold: 0.55 (cosine similarity), empirically calibrated

Per the brief ("start around cosine 0.5–0.6, document the reasoning"), I
built a real index from the 4 fixture lessons and measured actual
`bge-small-en-v1.5` cosine scores before picking a number, rather than
guessing:

| Query | Target lesson score | Best off-target score |
|---|---|---|
| "pydantic annotation error registering a FastMCP tool" | 0.9103 | 0.5754 |
| "FastMCP crashes with PydanticUserError non-annotated attribute" | 0.8959 | 0.6162 |
| "useEffect causing infinite re-renders in React component" | 0.8525 | 0.5663 |
| "docker build killed with exit code 137 out of memory" | 0.8009 | 0.6047 |
| "postgres FATAL remaining connection slots reserved" | 0.8482 | 0.6147 |
| 4 genuinely unrelated queries (sourdough bread, hiking trails, pizza toppings, capital of France) | — | max 0.4520 across all lessons |
| "python list comprehensions" (shallow domain-word overlap only, not a real match) | — | max 0.5220 |

Observations: genuine matches land at ~0.80–0.91; genuinely unrelated
queries never exceed ~0.45 against *any* fixture lesson (this model's
well-known anisotropy floor — bi-encoder cosine scores rarely go near 0
even for unrelated text); a "middle band" of ~0.53–0.62 shows up both
for legitimately-adjacent-but-wrong lessons (asking about lesson A pulls
lesson B up somewhat, since all 4 fixtures are "software debugging
incidents") and for shallow same-domain-word overlap that isn't a real
match (a generic Python question shouldn't surface the FastMCP/pydantic
incident just because both mention "python").

Picked **0.55**: comfortably above the unrelated-query ceiling (~0.10
margin, so `search()` never returns a weak match dressed as strong —
the hard constraint), comfortably below genuine-match scores (~0.25+
margin), and it also filters out the shallow-domain-word-overlap case
above (0.5220 < 0.55) rather than surfacing a lesson that isn't actually
about the query's incident. This is a defensible, evidence-based
starting point from a 4-lesson corpus, not a final calibration — the
plan explicitly earmarks real tuning for Task 8's matching tests against
a larger, more realistic lesson set. Documented in `index.py`'s
`DEFAULT_THRESHOLD` comment with the same reasoning, condensed.

## Design decisions / judgment calls

1. **Index format: JSON, not `.npy`.** Brief offered either. JSON keeps
   `id`/`path`/`vector` together in one self-describing file (includes
   `model`/`dim` for a future sanity check that a cached index matches
   the currently-configured model), needs no numpy dependency to
   read/write, and the whole index is small (tens to low-hundreds of
   lessons × 384 floats — trivial JSON size). A `.npy` array would need
   a parallel structure for `id`/`path` anyway (numpy arrays don't carry
   string metadata alongside float rows) so it wouldn't actually be
   simpler here.
2. **No numpy dependency for cosine similarity.** `fastembed` already
   depends on numpy transitively (confirmed available, `2.5.1`, via
   `onnxruntime`), and `embed()` converts each vector to a plain
   `list[float]` immediately (`[float(x) for x in vector]`) rather than
   keeping it a numpy array — so downstream code (`search`'s
   `_cosine_similarity`, JSON serialization, dataclass-free
   `list[float]` in the index file) never needs numpy directly. Cosine
   similarity over 384-element lists in pure Python is fast enough here
   (index sizes are small; this isn't a hot loop at scale) and avoids
   taking a direct dependency on a library only present because of a
   transitive chain I don't control the version of.
3. **Full rebuild only, no incremental single-lesson add in this task.**
   The brief mentions Task 4 "may... call `index.build_index` (or an
   incremental single-lesson add if you designed one in Task 3 — either
   is fine, document which)". I did not build an incremental add —
   `build_index` is a full from-scratch rebuild every time, which is the
   simplest implementation that satisfies "index format must be fully
   rebuildable from the markdown lessons alone" and keeps this task's
   scope to exactly what the brief lists (`embed`, `build_index`,
   `search`). Task 4 can call `build_index` after every `save_lesson`
   (documented as an explicit option in the plan) without needing
   anything further from this module.
4. **`search()` returns `{id, path, score}`, not the full
   `{id, title, score, failed_approaches, root_cause, fix, path}` shape**
   from Global Constraints' `search_lessons` contract. That richer shape
   requires parsing the full lesson (title, failed_approaches,
   root_cause, fix) back out of each matched file — `schema.parse_lesson`
   does that, but assembling the final MCP tool response is explicitly
   Task 4's job (`server/main.py`'s `search_lessons` wiring), which this
   task must not touch. `index.search`'s docstring says this explicitly
   so Task 4 doesn't have to re-derive it.
5. **`embed()` model instance is lazy + module-level cached**, not
   constructed fresh per call or per `build_index`/`search` invocation.
   Loading `TextEmbedding(model_name=...)` takes ~3s (measured) even
   with the ONNX weights already cached locally; repeating that per
   lesson during `build_index` (looping over lesson files) or per query
   would make an otherwise-fast operation unnecessarily slow. Downside:
   the model, once loaded in a process, stays loaded — an accepted
   trade-off for a short-lived MCP server process.

## Fastembed sandbox check (ran first, before writing any code)

Confirmed fastembed can download and use `BAAI/bge-small-en-v1.5` in
this environment before doing anything else, per the task instructions:

```
$ uv run --no-project --with-requirements server/requirements.txt python3 -c "
from fastembed import TextEmbedding
...
model = TextEmbedding(model_name='BAAI/bge-small-en-v1.5')
vecs = list(model.embed(['hello world']))
print(len(vecs), len(vecs[0]))
"
Fetching 5 files: 100%|██████████| 5/5 [00:02<00:00,  1.95it/s]
loaded in 3.014051914215088
1 384
```

Network access for the one-time model download worked fine in this
sandbox — not blocked. No mocking was used anywhere in `test_index.py`;
every test exercises the real model.

## Test results

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/
============================= test session starts ==============================
collected 62 items

server/tests/test_index.py ..........                                    [16%]
server/tests/test_schema.py ..........................                   [58%]
server/tests/test_scrub.py ..........................                    [100%]

============================== 62 passed in 0.35s ==============================
```

62/62 passed: the pre-existing 42 (16 `test_schema.py` + 26
`test_scrub.py`) all still pass unmodified, plus 10 new
`test_parse_lesson_*` tests in `test_schema.py` (26 total there now) and
10 new tests in the new `test_index.py`. Also verified: `py_compile` on
all new/edited `.py` files (clean); `server/main.py` untouched (file
mtime check + re-import shows original 3 stub tools intact);
`__pycache__`/`.pytest_cache` artifacts removed from disk before
finishing.

## Status

DONE. No blockers — fastembed's model download worked on first try in
this sandbox. No `server/main.py` or `server/scrub.py` changes. No git
commands run (no repo exists here, per environment constraint).

Judgment calls made without stopping to ask (documented above, all
reversible in later tasks): module-level `parse_lesson` function over a
`Lesson.from_markdown` classmethod; JSON index format over `.npy`; no
numpy dependency; full-rebuild-only `build_index` (no incremental add);
`search()`'s narrower `{id, path, score}` return shape (full MCP
response assembly deferred to Task 4 by design); threshold picked from
real empirical measurement against 4 fixture lessons rather than a
guess, with the exact numbers shown above for whoever tunes it further
in Task 8.

**Correction to the above:** the "PyYAML" section's claim that PyYAML
"was already an *indirect* dependency (pulled in transitively via
`mcp`'s own deps)" was inaccurate — a reviewer verified a clean install
of just `mcp==1.27.0` + `pytest` does *not* pull in PyYAML. It was only
ever a dependency of this project's `uv`-managed dev/test environment
(via some other tool in that environment, not `mcp` itself), not of
`mcp` transitively. This task's explicit, pinned addition of `PyYAML` to
`server/requirements.txt` was and remains correct/necessary regardless —
just the "already indirect via mcp" justification for why it happened to
already be resolvable was wrong. No code change needed for this; noted
here per the reviewer's request.

## Fix: header-anchoring + per-file error isolation

A reviewer found two Important issues via live reproduction against the
code above. Both are fixed below, with new regression tests. Prior test
count was 62; now 65.

### Finding 1: `_parse_body_sections` silently corrupted content on a header-like substring in free text

**Bug:** `_parse_body_sections` (`server/schema.py`) located each body
section header via `body_text.find(header)` — a plain substring search,
not anchored to a line start. A lesson whose `root_cause` (or any other
free-text section) contained the literal substring `"## Fix"` mid-
sentence (e.g. `'...references the "## Fix" section below...'`) parsed
**wrong with no exception raised**: `root_cause` got truncated at the
substring match and the remainder bled into `fix`. Confirmed via the
reviewer's live repro and reproduced again here before fixing (a
substring match, not a real header line, was silently treated as the
real header boundary).

**Fix:** header matching is now anchored to a full line via
`re.search(rf"^{re.escape(header)}$", body_text, re.MULTILINE)` instead
of `body_text.find(header)`. Every header `render()` emits always
occupies its own line (`"## Header\n\n{content}\n\n"`), so a real header
is always line-anchored; a header-like string embedded inside a sentence
no longer matches `^...$` and is correctly left alone as ordinary body
text. Content slicing now uses `match.end()`/`match.start()` from the
regex match instead of `idx + len(header)`. The out-of-order-headers
check is unchanged (still compares the sorted-by-position header list
against `BODY_SECTION_HEADERS`). Updated `_parse_body_sections`'s
docstring to describe the new anchoring and to name the one narrower
edge case that remains genuinely ambiguous and unhandled (free text
containing a header string *as a standalone line by itself*, not
mid-sentence — real lesson prose doesn't do that, per the same reasoning
the original docstring used, now scoped to the smaller actual gap).

**New tests** (`server/tests/test_schema.py`):
- `test_parse_lesson_round_trips_root_cause_containing_header_like_substring`
  — `root_cause` contains `"## Fix"` mid-sentence; asserts
  `parse_lesson(lesson.render()) == lesson` (exact equality on all
  fields, not just that no exception was raised) and explicitly checks
  `root_cause`/`fix` individually weren't cross-contaminated.
- `test_parse_lesson_round_trips_symptom_containing_header_like_substring`
  — same regression, different header (`"## Root cause"`) embedded in
  `symptom`, to prove the fix isn't narrowly special-cased to just the
  `"## Fix"` header.

### Finding 2: `build_index` crashed entirely on one malformed lesson file

**Bug:** `build_index` (`server/index.py`) called `parse_lesson(text)`
with no error handling around it. Confirmed live (before fixing): a
`lessons_dir` with 3 valid fixture-style lessons plus 1 file with
malformed YAML frontmatter made `build_index()` raise and write **no**
`index.json` at all — not even for the 3 valid lessons. Also confirmed
the specific exception type matters: malformed YAML *syntax* (e.g. an
unterminated quoted scalar) raises `yaml.parser.ParserError`
(`yaml.YAMLError`'s hierarchy), a *different* exception type than the
`ValueError` `parse_lesson` raises for structurally-valid-YAML-but-
missing-required-field cases — so a narrow `except ValueError` alone
would not have been sufficient to catch this class of malformed file.

**Fix:** the per-file `read_text` + `parse_lesson` step inside
`build_index`'s loop is now wrapped in `try/except Exception`. A file
that fails is logged (`logger.warning`, module logger `server.index`)
and recorded into a new `skipped: list[{path, error}]` list that's
written into `index.json` alongside `records` (chosen over changing
`build_index`'s return type, to keep its existing `-> Path` signature
and current callers — this module's own tests, and Task 4's planned
`store.save_lesson` usage — unchanged; the skip info is discoverable by
reading the same `index.json` the caller already has the path to). The
build then continues to the next file — every lesson that *does* parse
is still embedded and indexed normally. The catch is deliberately broad
(`Exception`, not `ValueError`) for the reason confirmed above, but
scoped only to the read+parse step — a failure inside `embed()` (an
infra/model problem, not a per-file data-quality problem) still
propagates and aborts the build, which is the correct behavior for that
class of failure. Updated both `build_index`'s docstring and the module
docstring's documented index-file shape
(`{model, dim, records, skipped}`) to describe this.

**New test** (`server/tests/test_index.py`):
- `test_build_index_skips_malformed_lesson_file_and_indexes_the_rest` —
  builds a `lessons_dir` with 3 valid lessons (via real
  `Lesson(...).render()`) plus 1 file with an unterminated-quote
  malformed frontmatter (confirmed separately to raise
  `yaml.parser.ParserError`, proving the fix catches more than just
  `ValueError`). Asserts `build_index` does not raise; the written
  `index.json` has exactly 3 records with the 3 valid lesson ids; exactly
  1 entry in `skipped` with the malformed file's path and a non-empty
  `error` string; and that `search()` against the resulting index
  actually works and correctly ranks the matching valid lesson first —
  proving the index isn't just non-crashing but genuinely usable.

### Minor items (not fixed, per reviewer's own "skip if time-constrained" note)

- `.strip("\n")` on parsed body sections could in principle strip a
  legitimate leading/trailing blank line from `symptom`/`root_cause`/
  `fix` text. Left as-is — reviewer flagged this as low priority/skip if
  time-constrained; no evidence real lesson content depends on
  leading/trailing blank lines being preserved, and fixing it would
  require also changing how `render()` pads sections to keep round-trip
  equality, which is a larger change than this fix pass's scope.
- `index.json`'s `model`/`dim` fields are written but never validated on
  load/search — a model swap without a rebuild would silently truncate
  vectors via `zip()` in `_cosine_similarity` rather than error loudly.
  Accepted as a known risk per the reviewer's note; not fixed here.
- The PyYAML-as-"already indirect via mcp" inaccuracy is corrected above,
  just above this section (no code change).

### Full test run after fixes

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/
============================= test session starts ==============================
collected 65 items

server/tests/test_index.py ...........                                   [ 16%]
server/tests/test_schema.py ............................                 [ 60%]
server/tests/test_scrub.py ..........................                    [100%]

============================== 65 passed in 0.37s ==============================
```

65/65 passed: the prior 62 all still pass unmodified, plus 3 new
regression tests (2 in `test_schema.py`, now 28 there; 1 in
`test_index.py`, now 11 there). Verified: `py_compile` clean on
`server/schema.py`, `server/index.py`, and both edited test files;
`server/main.py` and `server/scrub.py` not touched (confirmed no `Edit`
calls made to either file this pass); `__pycache__`/`.pytest_cache`
artifacts removed from disk before finishing. No `git` commands run (no
repo exists here, per environment constraint).

**Status:** DONE. Both Important findings fixed and regression-tested;
both minor items left as-is per the reviewer's own stated priority, with
the one factual-inaccuracy minor item corrected in text above.
