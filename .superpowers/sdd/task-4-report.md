# Task 4 report: Wire real store.py + MCP tool logic

## Files created

- `server/store.py` — lesson file I/O. Public API:
  - `slugify(text: str) -> str` — lowercase/ASCII-fold/hyphenate, drops a
    small filler-word list (`a`, `the`, `with`, ...), caps at 6 words.
  - `make_lesson_id(title, created_at) -> str` — `YYYY-MM-DD-short-slug`,
    date from `created_at[:10]`, slug from `slugify(title)`. Matches the
    shape of `server/tests/fixtures/*.md` (e.g.
    `2026-07-18-fastmcp-pydantic-floor`).
  - `write_lesson(lesson: Lesson, lessons_dir) -> Path` — renders via
    `Lesson.render()`, writes `lessons_dir/<id>.md`, creates
    `lessons_dir` if missing. Id-collision safe: if the target filename
    already exists, appends `-2`, `-3`, ... to the id until free, and
    updates the *written* lesson's own frontmatter `id` to match (via
    `dataclasses.replace`) so content and filename never disagree —
    never silently overwrites a previously saved lesson.
  - `read_lesson(path) -> dict` — `parse_lesson` + `dataclasses.asdict`
    + a `path` key.
  - `list_lessons(lessons_dir) -> list[dict]` — every `*.md` under
    `lessons_dir`, sorted by filename; `[]` if the dir doesn't exist;
    a per-file `except Exception` skip (logged) so one corrupt lesson
    can't take down the whole listing, mirroring `index.build_index`'s
    documented reasoning for the same pattern.
- `server/tests/test_store.py` — 12 unit tests: slugify shape/stopwords/
  word-cap/never-empty, id date+slug composition, write creates missing
  dirs, id-collision gets a free suffix (both the 2nd and 3rd collision),
  read round-trips write, list on missing dir, list sorted, list skips a
  malformed file.
- `server/tests/test_main.py` — 11 integration tests against the real
  `search_lessons`/`save_lesson`/`list_lessons` functions (called
  directly — see "How tests call the tools" below), including the
  brief's required scenario (see "Required integration test" below).
  (Corrected count — see "Fix: on-demand index build for fresh-clone
  search" below for the post-review count of 12.)

## Files edited

- `server/main.py` — replaced all three Task 1 stubs with real logic
  (see "Design" below). `server/schema.py`, `server/scrub.py`,
  `server/index.py`, `server/tests/test_index.py`,
  `server/tests/test_schema.py`, `server/tests/test_scrub.py`: **not
  touched**.

No git commands were run by me anywhere in this task (confirmed
`find . -maxdepth 1 -name ".git"` returns nothing in this repo, both
before and after). `server/main.py`'s own code *does* conditionally
shell out to `git add` (per the brief) — that code path is exercised by
tests via a monkeypatched `subprocess.run` (not a real `git` process) or
via the natural absence-of-`.git` no-op path, never by me typing `git`
into a shell.

## Design

### `save_lesson` pipeline

`scrub.scrub_payload` (title/domain/error_signature/symptom/
failed_approaches/root_cause/fix, as one dict) → build `schema.Lesson`
(auto id via `store.make_lesson_id`, auto tags via `_derive_tags`) →
`store.write_lesson` → `index.build_index` (full rebuild, matching Task
3's documented "always full rebuild" design — no incremental add was
built in Task 3, so there's nothing incremental to call here) → read
back `index.json`'s `skipped` list → best-effort `_maybe_git_add` →
return `{id, path, wrote: true, warnings?}`.

`confidence` is passed straight through to `Lesson(confidence=...)`,
not through `scrub_payload` — it's a `Literal["confirmed","probable"]`,
not free text, so there's nothing to scrub.

### `search_lessons`

Calls `index.search(query, cache_dir, k=k)`, then for each hit re-reads
and `parse_lesson`s the file at `hit["path"]` to fill in
`title`/`failed_approaches`/`root_cause`/`fix` (per `index.search`'s own
docstring, which explicitly hands this assembly job to Task 4). A hit
whose file has gone missing or become unparseable since the index was
built is skipped (logged), not fatal to the rest of the search — same
per-file isolation philosophy `index.build_index` documents.

Does **not** rebuild the index itself (only `save_lesson` does, per the
brief: "`search_lessons(query, k=3)`: calls `index.search`"). Documented
consequence in `search_lessons`'s own docstring: a `.debug-memory/
lessons/` freshly cloned from a teammate with no local `index.json` yet
returns `[]` until this machine's own `save_lesson` runs once, or a
future reindex command (Task 8) exists. Kept minimal deliberately —
auto-rebuild-on-missing-cache wasn't asked for and risks colliding with
Task 8's planned dedicated reindex mechanism.

### Tags decision

No `tags` parameter added to `save_lesson` (matches the brief's binding
note and the original spec's tool contract). `_derive_tags(domain,
error_signature, title)` in `main.py` tokenizes all three fields
(`[A-Za-z0-9]+`), lowercases, dedupes, drops a small stopword list, and
returns a `list[str]` — not one joined string, since `Lesson.tags` is a
`list[str]` (one bullet per tag in the rendered "## Tags for retrieval"
section) and `Lesson.match_text()` already whitespace-joins them for
embedding, so no extra joining belongs in `_derive_tags` itself. Verified
in `test_main.py::test_save_lesson_derives_tags_from_domain_error_and_title`
that e.g. `domain=["kubernetes","infra"]`, `error_signature=
"CrashLoopBackOff"` produces `kubernetes`, `infra`, `crashloopbackoff` as
tags actually present in the written file's body.

### Skipped-lessons surfacing

After `save_lesson`'s `index.build_index` call, `index.json` is re-read
and its `skipped` list checked. If non-empty, `save_lesson`'s return
value gets a `warnings: list[str]` key — one human-readable string per
skipped file (`"lesson file failed to index and was excluded from
search: <path>: <error>"`). Absent entirely (no `warnings` key at all,
not an empty list) when nothing was skipped, so a caller can check
`"warnings" in result` as the signal. Verified with a test that
pre-seeds a malformed lesson file, calls `save_lesson`, and asserts the
warning surfaces with the malformed file's path in it — plus a
negative test that a clean save has no `warnings` key at all.

### `git add`

`_maybe_git_add(file_path, project_dir)`: checks `(project_dir /
".git").exists()` (covers both a normal repo's `.git` directory and a
worktree/submodule's `.git` file) as a fast pre-check, then shells out to
`git -C <project_dir> add -- <file_path>` with `capture_output=True`
(so a talkative git subprocess can never leak bytes onto this stdio MCP
server's own stdout/stderr transport) and `check=False`, wrapped in a
broad `try/except Exception` (git missing from `PATH`, or literally
anything else) that only logs and never re-raises. `project_dir` passed
in is `lessons_dir.parent.parent` — i.e. the actual consuming-repo root
(`.debug-memory/lessons/`'s grandparent), **not**
`Path(lessons_dir).parent` as the brief's own illustrative snippet
literally wrote. I believe that snippet has an off-by-one relative to
the brief's own stated lesson-folder path
(`${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`, i.e. `.git` lives two
levels above `lessons_dir`, not one) — the brief's alternative
suggestion, `git rev-parse` in a try/except, has no such issue and
points at the same conclusion, so I used the corrected two-levels-up
path. Verified as a genuine no-op in this repo (no `.git` present) and
tested three ways: (1) no `.git` in the tmp project dir → save succeeds,
no error; (2) `.git` dir present + a monkeypatched `subprocess.run` →
confirms the exact `git -C <dir> add -- <path>` invocation is attempted;
(3) `.git` present + a monkeypatched `subprocess.run` that raises
`FileNotFoundError` → save still succeeds. None of these three actually
invoke a real `git` binary.

### Runtime path resolution

Read the official Claude Code docs (fetched live during this task,
`code.claude.com/docs/en/mcp.md`, "Add a local stdio server" +
"Environment variables" sections) rather than assume: *"Claude Code sets
`CLAUDE_PROJECT_DIR` in the spawned server's environment... Read it from
inside your server process... e.g. `os.environ["CLAUDE_PROJECT_DIR"]` in
Python"*, and *"All three [`CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`,
`CLAUDE_PROJECT_DIR`] are exported as environment variables to hook
processes and to MCP and LSP server subprocesses."* So this is a real
Claude-Code-injected process env var, not something the generic `mcp`
Python SDK itself expands — confirmed by inspecting the installed SDK
too (no Claude-specific env handling in it). `_lessons_dir()` /
`_cache_dir()` in `main.py` read `os.environ.get("CLAUDE_PROJECT_DIR")`
/ `os.environ.get("CLAUDE_PLUGIN_DATA")` directly, exactly the fallback
path the brief anticipated. Both create their target directory
(`mkdir(parents=True, exist_ok=True)`) if missing.

**Fallback when unset** (only happens outside a real Claude Code
session — standalone scripts, `pytest` without an explicit override):
`_lessons_dir()` falls back to `Path.cwd() / ".debug-memory" /
"lessons"`; `_cache_dir()` falls back to `<resolved-project-dir> /
".debug-memory" / ".index-cache"`. Documented in both functions'
docstrings as a fallback for that specific situation, not a guess at
real runtime behavior. All of `server/tests/test_main.py`'s tests set
both env vars explicitly via `monkeypatch.setenv` to an isolated
`tmp_path` rather than relying on the fallback, so test behavior never
depends on it (or on this repo's own cwd).

### How tests call the tools

Confirmed by reading `mcp.server.fastmcp.FastMCP.tool`'s source before
relying on it: the `@mcp.tool()` decorator registers the function as a
side effect (`self.add_tool(fn, ...)`) and then `return fn`s the
*original, unwrapped* function. So `main.save_lesson`,
`main.search_lessons`, `main.list_lessons` remain ordinary,
directly-callable Python functions after decoration —
`server/tests/test_main.py` calls them directly
(`main.save_lesson(**payload)` etc.), the same pattern
`server/tests/test_index.py` already uses for `index.py`'s functions,
rather than spinning up the MCP stdio transport per-test. I additionally
verified end-to-end over the *real* stdio transport, spawned exactly the
way the real `.mcp.json` specifies (see "Verification" below) — so both
the direct-call unit/integration layer and the actual wire protocol are
covered.

## Deviations / judgment calls (all documented inline in the code too)

1. **`store.write_lesson(lesson: Lesson, lessons_dir)` takes a
   `Lesson`, not a raw `payload` dict**, despite the brief's sketch
   `write_lesson(payload, lessons_dir)`. The brief's own prose for
   `save_lesson`'s pipeline is "scrub payload via scrub.py → build
   lesson via schema.py → write via store.py" — i.e. `main.py` builds
   the `Lesson` (including the auto-derived `id`/`tags`), and `store.py`
   just renders+writes it. Building a second, parallel "dict → Lesson"
   construction path inside `store.py` would duplicate what
   `Lesson.__init__`/`__post_init__` already does. Documented in
   `store.py`'s module docstring.
2. **`write_lesson` disambiguates on id collision** rather than silently
   overwriting a same-day-same-slug lesson. Not explicitly required by
   the brief, but a same-day collision (e.g. two "Docker OOM" incidents
   in one day) silently destroying a previously captured lesson felt
   like a real, cheap-to-prevent correctness risk worth closing now
   rather than leaving as a landmine. Because a collision can change the
   actually-written id, `save_lesson` reports `path.stem` (the id the
   file was *actually* written under) rather than the pre-collision-
   check `lesson.id`, so the returned `{id, ...}` always matches reality.
3. **`list_lessons`/`search_lessons` skip a malformed/missing file per-
   entry rather than erroring the whole call**, mirroring
   `index.build_index`'s Task-3-review-fixed pattern and its documented
   reasoning (one bad file must never take down everything else). Not
   explicitly asked for in this task's brief, but keeping this
   consistent with the already-reviewed pattern in `index.py` seemed
   safer than inventing a third, different failure behavior.
4. **`search_lessons` does not rebuild the index on a cache miss.** Kept
   strictly to the brief's literal instruction ("calls `index.search`").
   Documented the resulting gap (fresh clone, no local cache yet → `[]`
   until a local `save_lesson` or a future reindex command) in the
   function's own docstring rather than silently working around it or
   silently leaving it unmentioned.
5. **Small stopword lists duplicated between `store.py` (slug-word
   filtering) and `main.py` (tag-keyword filtering).** Left un-factored
   — they're conceptually different (filename brevity vs. retrieval
   keywords) even though the ~15-word lists overlap heavily, and
   introducing a shared constant/module for two small local lists felt
   like more abstraction than the actual duplication warrants. Flagging
   as a low-priority, intentionally-accepted duplication rather than an
   oversight.
6. **`_maybe_git_add`'s `project_dir` argument is `lessons_dir.parent.parent`**,
   correcting what I believe is an off-by-one in the brief's own
   illustrative `Path(lessons_dir).parent / ".git"` snippet — see "git
   add" above for the full reasoning.

## Test results

Required test scenario (brief, verbatim requirements) —
`server/tests/test_main.py::test_save_lesson_three_times_then_search_finds_the_right_one_and_secret_never_written`:
calls `save_lesson` three times with distinct fixture payloads (the
second seeded with a fake AWS access key,
`AKIAIOSFODNN7EXAMPLE`, in its `symptom` field), then calls
`search_lessons` with a query matching the first lesson and asserts it's
returned first with the exact `{id, title, score, failed_approaches,
root_cause, fix, path}` shape; separately reads back **all three**
written `.md` files from disk and asserts the fake AWS key string is
absent from every one of them (`grep`-equivalent `not in` check).

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/ -v
============================= test session starts ==============================
collected 88 items

server/tests/test_index.py::... (11 tests)                              PASSED
server/tests/test_main.py::... (11 tests)                                PASSED
server/tests/test_schema.py::... (28 tests)                              PASSED
server/tests/test_scrub.py::... (26 tests)                               PASSED
server/tests/test_store.py::... (12 tests)                               PASSED

============================== 88 passed in 0.65s ==============================
```

88/88 passed (the pre-existing 65 — 11 in `test_index.py`, 28 in
`test_schema.py`, 26 in `test_scrub.py` — all still pass unmodified,
confirmed `server/schema.py`, `server/scrub.py`, `server/index.py`, and
their test files were not touched, plus 23 new: 12 in `test_store.py`,
11 in `test_main.py`).

### Full real-stdio-transport verification (beyond what pytest covers)

Spawned the server *exactly* the way the real `.mcp.json` specifies
(parsed `.mcp.json` itself in the test harness, substituted
`${CLAUDE_PLUGIN_ROOT}` the way Claude Code would — no hardcoding of
command/args), with `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` pointed at
an isolated temp dir via the spawned process's own `env`, and drove it
through a real MCP `ClientSession` (`initialize` → `tools/list` → four
`tools/call`s): `list_lessons` (empty) → `save_lesson` (with a leaked
fake AWS key in the payload) → `search_lessons` → `list_lessons` again.

```
$ uv run --no-project --with-requirements server/requirements.txt python3 <script>
Spawning: uv ['run', '--no-project', '--with-requirements', '.../server/requirements.txt', '.../server/main.py']
Registered tools: ['list_lessons', 'save_lesson', 'search_lessons']
list_lessons (empty) -> {'result': []}
save_lesson -> {'id': '2026-07-18-stdio-round-trip-test-lesson', 'path': '.../consuming-repo/.debug-memory/lessons/2026-07-18-stdio-round-trip-test-lesson.md', 'wrote': True}
Secret scrubbed from disk: OK
search_lessons -> {'result': [{'id': '2026-07-18-stdio-round-trip-test-lesson', 'title': 'Stdio round-trip test lesson', 'score': 0.857..., 'failed_approaches': [...], 'root_cause': '...', 'fix': '...', 'path': '...'}]}
list_lessons (after save) -> 1 lesson(s)
No .git in project dir; save_lesson succeeded anyway -> git-add no-op confirmed

ALL CHECKS PASSED
```

Confirms end to end, over the actual wire protocol and the actual
`.mcp.json` command: exactly 3 tools registered; `save_lesson` scrubs a
leaked AWS key before it ever reaches disk; `search_lessons` returns the
right lesson with the full required shape; `list_lessons` reflects the
save; the git-add path is a genuine no-op with no `.git` present, with
no error surfaced to the caller.

Also ran `py_compile` on every new/edited `.py` file (clean), and
removed `__pycache__`/`.pytest_cache` artifacts from disk before
finishing.

## Status

DONE. No blockers. No `git` commands run by me anywhere (confirmed no
`.git` exists in this repo, both before and after this task). All
judgment calls above are documented and, where they touch behavior not
explicitly pinned by the brief (write_lesson's collision handling,
list_lessons/search_lessons per-file skip, search_lessons not auto-
rebuilding), are reversible in a later task if new information surfaces.

## Fix: on-demand index build for fresh-clone search

Reviewer found one Important issue: `search_lessons` returned `[]`
silently on a freshly-cloned repo. The lesson `.md` files live under
`${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/` (git-committed, shared),
but the similarity index cache lives under `${CLAUDE_PLUGIN_DATA}`
(local machine data, never git-committed). Deviation #4 in the original
report ("search_lessons does not rebuild the index on a cache miss")
had documented this as a known, deliberate limitation rather than a
bug — the review correctly identified it as a functional defect
instead: it defeats the product's headline scenario (every teammate's
Claude skips dead ends other people already hit), since a teammate who
pulls committed lessons and searches before ever personally calling
`save_lesson` gets a result indistinguishable from "nothing relevant
exists."

### What changed

`server/main.py`'s `search_lessons` (around what is now lines 203-251):
before calling `index.search`, it now checks whether
`{cache_dir}/index.json` exists. If it doesn't, it calls
`index.build_index(lessons_dir, cache_dir)` once first, then proceeds
to `index.search` as before. This required adding a
`lessons_dir = _lessons_dir()` call to `search_lessons` (previously it
only resolved `cache_dir`, since it never needed the raw lesson files
itself).

Kept strictly to "only when the cache file is genuinely missing," per
the fix direction: an existing `index.json` — however stale — is left
alone by this code path. `index.build_index` is a full rebuild every
time it runs (confirmed again by rereading its docstring: "Always a
full rebuild from scratch... the cache is never treated as
authoritative"), so calling it once on a missing cache is safe and
idempotent; it does *not* get called on every search (verified by the
new test's second assertion that `index.json` exists afterward, and by
the fact `index.search`'s own missing-index short-circuit — `if not
index_path.exists(): return []` — is now simply never hit by
`search_lessons` in the fresh-clone case, since the file exists by the
time `index.search` runs).

**Warnings-surfacing decision:** `save_lesson` attaches an optional
top-level `warnings: list[str]` key to its return dict when
`index.build_index` skips a malformed lesson file. `search_lessons`
returns `list[dict[str, Any]]`, not a single dict — there's no natural
top-level slot to hang a `warnings` field off of without changing the
function's return shape (e.g. wrapping results in `{"results": [...],
"warnings": [...]}`, a breaking change to every existing caller
expecting a bare list, including the Global Constraints' own documented
contract and this task's own prior tests). I judged that reshaping a
tool's return contract to plumb through a rare, best-effort diagnostic
was a worse trade than the alternative, so this on-demand build's
`skipped` list is logged via `logger.warning` (one line per skipped
file, same message shape/detail as `save_lesson`'s existing
`build_index`-skip handling) rather than surfaced in the return value.
This is a narrower guarantee than `save_lesson`'s (a caller can't
introspect it without log access), documented as a deliberate,
shape-driven judgment call in `search_lessons`'s own docstring rather
than silently matching or silently diverging from `save_lesson`'s
pattern without explanation.

### New test

`server/tests/test_main.py::test_search_lessons_builds_index_on_demand_when_cache_is_missing`:
writes the existing `server/tests/fixtures/2026-06-02-react-useeffect-infinite-loop.md`
fixture file's exact content directly into an isolated `lessons_dir`
(`Path.write_text`, never calling `save_lesson`) — reusing a fixture
already proven (in `server/tests/test_index.py::
test_query_matching_a_different_lesson_ranks_that_one_first`) to clear
the similarity threshold and rank first for the query "useEffect
causing an infinite re-render loop in a React component", rather than
inventing new lesson content whose score margin against the 0.55
threshold would be unverified. Asserts, *before* calling
`search_lessons`, that no `index.json` exists yet in `cache_dir` (the
actual fresh-clone precondition — cache_dir and lessons_dir are set up
by the same `isolated_project` fixture every other test in this file
uses, so a prior test's `save_lesson` call can't have built it). Then
calls `main.search_lessons(...)` and asserts the pre-existing lesson is
found, with the full `{id, title, score, failed_approaches, root_cause,
fix, path}` shape, and that `index.json` now exists (confirming the
on-demand build actually ran and produced a usable cache, not that the
result came from some other path).

Verified this test is a genuine regression test, not a vacuous pass:
temporarily reverted `search_lessons` to the pre-fix code (dropped the
`lessons_dir = _lessons_dir()` line and the whole
"if not index_path.exists(): build" block, restoring the original
direct `hits = index.search(query, cache_dir, k=k)` call) and reran
just this test — it failed with `AssertionError: expected the
pre-existing (not save_lesson-created) lesson to be found via an
on-demand index build; assert []`, exactly reproducing the reviewer's
reported symptom. Restored the fix from a backup copy afterward and
reran the full suite to confirm it passes again.

A test that only called `save_lesson` first (as suggested in the fix
direction as the tempting-but-wrong shortcut) would not have caught
this: `save_lesson` already triggers `index.build_index` itself as part
of its own pipeline (see "Design" above), so `index.json` would already
exist by the time `search_lessons` ran, masking the exact bug this
finding is about.

### Full test run

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/ -v
============================= test session starts ==============================
collected 89 items

server/tests/test_index.py::... (11 tests)                              PASSED
server/tests/test_main.py::... (12 tests)                                PASSED
server/tests/test_schema.py::... (28 tests)                              PASSED
server/tests/test_scrub.py::... (26 tests)                               PASSED
server/tests/test_store.py::... (12 tests)                               PASSED

============================== 89 passed in 0.56s ==============================
```

89/89 passed: the prior 88 (11 + 11 + 28 + 26 + 12, per the corrected
count above — `test_main.py` had 11 tests before this fix, not the
"12" the file-listing prose at the top of this report originally and
incorrectly claimed) plus 1 new
(`test_search_lessons_builds_index_on_demand_when_cache_is_missing` in
`test_main.py`, now 12 there). No other test file was touched by this
fix; `server/schema.py`, `server/scrub.py`, `server/index.py`,
`server/store.py`, and their test files remain untouched.

Ran `py_compile` on `server/main.py` and `server/tests/test_main.py`
(clean) and removed `__pycache__`/`.pytest_cache` artifacts before
finishing. No `git` commands run by me anywhere in this fix.

### Status

DONE. No blockers. The Important finding is fixed, regression-tested
(and the test verified to actually fail without the fix), and the
report's stale test-count claim is corrected in place above.
