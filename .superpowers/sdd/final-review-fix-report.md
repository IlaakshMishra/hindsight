# Final Whole-Project Review — Fix Report

Fixes for findings C1, I1, I2, I4, M1 from the final cross-cutting review
of the hindsight plugin. I3 and M2/M3 are explicitly deferred per the
task brief — not touched in this pass.

## Status

All five findings fixed. Both test suites green:

- `uv run --no-project --with-requirements server/requirements.txt pytest server/tests/` → **128 passed** (was 120; +8 new tests)
- `python3 -m pytest hooks/tests/` → **23 passed** (was 22; +1 new test)
- `python3 hooks/tests/test_mark_and_capture.py` (standalone script mode) → **18/18 passed**

No existing test was deleted or weakened to make this pass — the ones
that needed updating (fixture/env-setup changes forced by the C1/I1
fixes) were updated to assert the *new* correct behavior, not relaxed.

---

## C1 (Critical): index cache shared across all projects on a machine

### Root cause

`server/main.py`'s `_cache_dir()` returned `${CLAUDE_PLUGIN_DATA}`
directly. That directory is one-per-plugin-per-**machine** (`~/.claude/
plugins/data/<plugin-id>/`), not one-per-project. `index.json` lived at a
single fixed path shared by every project on a machine. Saving a lesson
in project A rebuilt that one shared `index.json` from project A's
lessons; switching to project B and calling `search_lessons` would
silently return project A's lessons (paths pointing into A's repo)
because the on-demand build only fires when `index.json` is entirely
*missing*, not when it belongs to a different project. `list_lessons`
(already per-project, reads `_lessons_dir()` directly) and
`search_lessons` (reading the shared cache) would disagree.

### Fix

Added `_project_slug()` to `server/main.py` — a pure string transform
(no filesystem I/O), deriving a stable, filesystem-safe slug from
`${CLAUDE_PROJECT_DIR}` (or `Path.cwd()` fallback, matching
`_lessons_dir`'s own fallback):

```
"<sanitized-basename>-<12 hex chars of sha256(project_dir)>"
```

e.g. `my-api-a1b2c3d4e5f6`. The basename half is for human readability
when browsing `${CLAUDE_PLUGIN_DATA}` by hand; it is **not** relied on
for uniqueness (two repos can share a basename like `api`). The
sha256-derived 12-hex-char suffix is what guarantees no collision — 48
bits of entropy is comfortably enough for a developer's local repo
count.

`_cache_dir()` now returns `Path(plugin_data) / _project_slug()` when
`CLAUDE_PLUGIN_DATA` is set. Since `search_lessons`, `save_lesson`,
`prune_lesson`, `reindex_lessons`, and `clear_capture_marker` already
funnel through `_cache_dir()`, the fix is centralized — no other tool
body needed a change.

The **fallback** path (`CLAUDE_PLUGIN_DATA` unset — standalone/test only)
is untouched in shape: it's already nested under `${CLAUDE_PROJECT_DIR}`
(or cwd), i.e. already per-project on its own, so no slug partitioning is
applied there (would be redundant double-nesting). Only its *leaf name*
changed, as part of the I4 fix below.

### Markers moved under the same partition

`clear_capture_marker` already called `_cache_dir()`, so it inherited the
partitioning for free. To keep the write side (`hooks/mark_error.py`) and
read side (`hooks/capture.py`) in agreement, both hook scripts got a
byte-for-byte duplicate `_project_slug()` (same duplication precedent
already used for `_SAFE_CHARS_RE`/`_plugin_data_dir` across these files —
hooks are standalone, dependency-free `python3` scripts by design, not
importers of `server/`). All three copies (main.py, mark_error.py,
capture.py) must stay identical; each docstring cross-references the
other two and calls this out explicitly.

Markers now live at
`${CLAUDE_PLUGIN_DATA}/<project slug>/session-<id>.marker` instead of
directly under `${CLAUDE_PLUGIN_DATA}/`. This wasn't strictly required
for correctness (session ids are globally unique, so cross-project
marker collisions were never a real risk) but keeps one consistent
partitioning scheme instead of a mix of per-project and machine-global
files sitting side by side.

### Tests added

- `server/tests/test_main.py::test_project_slug_is_stable_and_distinct_per_project` — same `CLAUDE_PROJECT_DIR` → stable slug; different dirs sharing a basename → different slugs (hash suffix differs).
- `server/tests/test_main.py::test_cache_dir_fallback_when_plugin_data_unset` — fallback path unaffected, uses canonical leaf name.
- `server/tests/test_main.py::test_cache_is_partitioned_per_project_not_shared_across_projects` — **the regression test the brief asked for**: two different `CLAUDE_PROJECT_DIR` values pointed at the SAME `CLAUDE_PLUGIN_DATA`. Saves a lesson in "project A," confirms `search_lessons`/`list_lessons` in "project B" don't see it and vice versa, then confirms two distinct `<slug>/index.json` subdirectories actually exist under the shared root.
- `hooks/tests/test_mark_and_capture.py::test_marker_partitioning_is_isolated_per_project_dir` — companion test at the hook layer: two different `CLAUDE_PROJECT_DIR` values, same `CLAUDE_PLUGIN_DATA`, same `session_id` (deliberately, to prove isolation comes from project partitioning and not session-id uniqueness) — project B's `capture.py` run must not see project A's marker.

The `isolated_project` pytest fixture in `server/tests/test_main.py` was
changed to call `main._cache_dir()` after setting env vars and return
that (the real, partitioned path) as `cache_dir`, instead of the raw
`CLAUDE_PLUGIN_DATA` value. This kept ~25 pre-existing tests (which build
paths like `cache_dir / "index.json"`) working unchanged, since they now
point at wherever the tools actually write. One test
(`test_clear_capture_marker_matches_mark_error_pys_sanitization`) that
spawns `hooks/mark_error.py` as a real subprocess had to be updated to
pass the subprocess the *raw* plugin data root (`cache_dir.parent`) plus
the matching `CLAUDE_PROJECT_DIR`, so the subprocess computes the
identical partitioned path the in-process `main.clear_capture_marker`
call resolves to.

### Documentation

Updated: `server/main.py` module docstring, `_cache_dir`/
`clear_capture_marker` docstrings; `hooks/mark_error.py` and
`hooks/capture.py` module docstrings; `README.md` (ASCII diagram + prose,
now shows `${CLAUDE_PLUGIN_DATA}/<project slug>/`).

---

## I1 (Important): capture nudge never passes session_id to Claude

### Root cause

`hooks/capture.py` read `session_id` from the `Stop` payload to decide
*whether* to nudge, but the `additionalContext` text itself was a fixed
string that never included it. Claude Code does not surface a hook's raw
JSON input fields into model context — only what a hook prints in
`additionalContext` is visible. `agents/lesson-distiller.md` expects to
be dispatched *with* a `session_id` so it can call
`clear_capture_marker(session_id)` after a save, but nothing handed the
dispatching Claude turn that value. Result: `clear_capture_marker` fails
to find/clear the marker, and the nudge re-fires every subsequent `Stop`
for the rest of the session — reproducing the exact bug Task 7 already
fixed once, via a different gap.

### Fix

`hooks/capture.py`'s fixed `ADDITIONAL_CONTEXT` constant became
`ADDITIONAL_CONTEXT_TEMPLATE`, filled per-call by
`_build_additional_context(session_id)`. The **real, unsanitized**
`session_id` (not the filesystem-safe `safe_id` used for the marker
filename) is interpolated directly into the text, in backticks:

> "This session hit a tool failure earlier. If it's now resolved, the
> lesson-distiller agent (subagent_type: lesson-distiller) can turn it
> into a saved lesson from this session's session_id, `<the actual id>`,
> and a concise summary — error signature, symptom, failed approaches,
> root cause, fix — with secrets/tokens/customer data excluded. Not worth
> dispatching if the error wasn't actually resolved this session."

Kept factual/descriptive phrasing (not imperative) per the existing
rationale in this file and `retrieve.py` (imperative phrasing on a hook's
own output risks tripping Claude's prompt-injection defenses, surfacing
the raw text to the user instead of being acted on) — only the
session_id clause was added, the rest of the Task 7 brief's verbatim text
is unchanged.

`agents/lesson-distiller.md`'s frontmatter `description` (read by the
*dispatching* Claude turn) previously said to use "the same session_id
the Stop hook payload carried" — which implied the raw payload was
somehow visible. Corrected to say explicitly: read it from the capture
nudge's own printed text, not the raw JSON payload.

### Tests updated

`hooks/tests/test_mark_and_capture.py`'s `EXPECTED_ADDITIONAL_CONTEXT`
(a single fixed string) became `EXPECTED_ADDITIONAL_CONTEXT_TEMPLATE` +
`_expected_additional_context(session_id)`, mirroring capture.py's own
template. Every test asserting nudge text now builds the session-specific
expected string rather than comparing against one hardcoded constant:
`test_capture_emits_nudge_when_marker_exists`,
`test_end_to_end_mark_then_capture_same_session`,
`test_sanitization_is_consistent_between_write_and_read` (the last one
specifically checks the hostile, path-traversal-shaped session_id appears
**verbatim, unsanitized** in the nudge text — proving the marker-filename
sanitization and the display text are independent).

---

## I2 (Important): index.json writes are non-atomic

### Root cause

`index.build_index` did `index_path.write_text(...)` — truncate-then-
write, not atomic. A concurrent `search()` call racing a rebuild could
observe the file mid-truncation; `json.loads()` on that content raises
`JSONDecodeError` and crashes the search tool call.

### Fix

`build_index` now writes to a temp file in the *same directory* as
`index.json` (`tempfile.mkstemp(dir=cache_dir, prefix=".index.json.",
suffix=".tmp")`), then `os.replace(tmp_name, index_path)` — atomic
rename on POSIX, same filesystem guaranteed since the temp file lives
alongside the target. On any failure before the replace, the temp file is
best-effort cleaned up and the original exception re-raised (no masking).
`search()` itself needed no change — the atomic write means it never
observes a half-written file in the first place.

### Tests added (`server/tests/test_index.py`)

- `test_build_index_leaves_previous_index_intact_if_the_atomic_replace_fails` — monkeypatches `os.replace` to raise mid-build after a real prior index exists; asserts the old `index.json` is byte-for-byte untouched and still valid JSON, and no leftover temp file remains.
- `test_build_index_still_produces_a_valid_index_after_the_atomic_write_change` — sanity check that a normal successful build still produces exactly one file (`index.json`, no stray temp file) with the expected record count.

---

## I4 (Important, latent/fallback-only): fallback dir names diverged

### Root cause

When `CLAUDE_PLUGIN_DATA` is unset, `hooks/mark_error.py`/
`hooks/capture.py` fell back to `.debug-memory/.plugin-data` while
`server/main.py`'s `_cache_dir()` fallback used
`.debug-memory/.index-cache` — different names for what must be the same
directory in the fallback case. A marker written by a hook running
without `CLAUDE_PLUGIN_DATA` set was never found by
`clear_capture_marker` running the same way. (Real installs are
unaffected — both sides always get the real env var — this only bit
standalone/test runs without it.) `clear_capture_marker`'s docstring also
falsely claimed to resolve to "the exact same directory" the hook writes
into.

### Fix

Canonical fallback leaf name picked: **`.hindsight-cache`**, used
identically in all three files (`server/main.py`'s
`_FALLBACK_CACHE_LEAF`, and the literal-duplicated constant of the same
name in both hook scripts). Verified via a manual smoke test
(`CLAUDE_PROJECT_DIR` set, `CLAUDE_PLUGIN_DATA` unset, real
`server/reindex.py` CLI run) that the index actually lands at
`.debug-memory/.hindsight-cache/index.json`.

`clear_capture_marker`'s docstring was corrected: the "resolves to the
exact same directory" claim was false before this pass (when markers
lived at the unpartitioned `${CLAUDE_PLUGIN_DATA}` root) and is
accurate now that all three files agree on the C1 partitioning scheme —
the docstring says so explicitly, including that this claim was
previously false.

`server/reindex.py`'s `--cache-dir` help text updated to reference the
new canonical fallback name and the partitioned production path.

### Test added

`server/tests/test_main.py::test_cache_dir_fallback_when_plugin_data_unset`
asserts `main._FALLBACK_CACHE_LEAF == ".hindsight-cache"` and that
`_cache_dir()`'s fallback actually resolves there.

---

## M1 (Minor, cheap): no model/dim validation on index load

### Fix

`index.search()` now checks, right after loading `index.json`:

```python
if data.get("model") != MODEL_NAME or data.get("dim") != EMBEDDING_DIM:
    ...
    index_path.unlink()
    return []
```

Chose **delete + return `[]`** over extending `search()`'s signature to
also rebuild inline (which would give `search()` a second responsibility
— building, not just searching — it doesn't otherwise have). Deleting
the stale/foreign `index.json` means the very next `search_lessons` call
sees a missing file and triggers its own existing on-demand-build logic
automatically — self-healing without widening `search()`'s contract or
touching `server/main.py`. Checked both `model` and `dim` (not just
`model`) since they can drift independently (hand-edited/corrupted
`index.json`). This also serves as defense-in-depth for C1: if some other
bug ever let one project's index leak into another's cache dir, this
catches the mismatch instead of `_cosine_similarity`'s `zip(a, b)`
silently truncating to the shorter vector and producing a meaningless
score dressed up as real.

### Tests added (`server/tests/test_index.py`)

- `test_search_returns_empty_and_deletes_index_on_model_mismatch`
- `test_search_returns_empty_and_deletes_index_on_dim_mismatch_alone`
- `test_search_accepts_index_with_matching_model_and_dim` (negative check — guard must not false-positive on a real index)

---

## Explicitly not fixed (per task brief)

- **I3** — full re-embed on every save doesn't scale past ~hundreds of lessons. Accepted known follow-up.
- **M2** — `write_lesson`'s TOCTOU collision check. Already an accepted residual risk from Task 4's review.
- **M3** — session_id sanitize-vs-reject asymmetry. Already assessed as intentional defense-in-depth, not a bug.

---

## Files changed

- `server/main.py` — `_project_slug()`, partitioned `_cache_dir()`, `_FALLBACK_CACHE_LEAF`, docstring updates (module + `_cache_dir` + `clear_capture_marker`).
- `server/index.py` — atomic write in `build_index`, model/dim guard in `search`, docstring updates.
- `server/reindex.py` — `--cache-dir` help text updated for the new fallback name and partitioned production path.
- `hooks/mark_error.py` — `_project_slug()` duplicate, partitioned `_plugin_data_dir()`, canonical fallback leaf, docstring updates.
- `hooks/capture.py` — `_project_slug()` duplicate, partitioned `_plugin_data_dir()`, canonical fallback leaf, `ADDITIONAL_CONTEXT_TEMPLATE` + `_build_additional_context(session_id)`, docstring updates.
- `agents/lesson-distiller.md` — frontmatter `description` corrected to say session_id must be read from the nudge text, not the raw hook payload.
- `README.md` — index-cache path references updated to show per-project partitioning.
- `server/tests/test_main.py` — `isolated_project` fixture now returns the real partitioned `cache_dir`; 3 new tests; 1 subprocess test's env setup fixed; 1 comment fixed (no longer describes a now-inaccurate directory depth).
- `server/tests/test_index.py` — 5 new tests (2 for I2, 3 for M1); added `json`/`pytest` imports.
- `hooks/tests/test_mark_and_capture.py` — `FAKE_PROJECT_DIR` + deterministic env setup, `_project_slug`/`_touch_marker` test helpers, templated expected-nudge-text helper, 1 new regression test, several existing tests' assertions updated for the new nesting/text.

## Test run output

### `uv run --no-project --with-requirements server/requirements.txt pytest server/tests/`

```
........................................................................ [ 56%]
........................................................                 [100%]
128 passed in 0.74s
```

### `python3 -m pytest hooks/tests/`

```
.......................                                                  [100%]
23 passed in 0.53s
```

### `python3 hooks/tests/test_mark_and_capture.py` (standalone mode, no pytest)

```
PASS test_mark_error_creates_marker_file_at_expected_path
PASS test_mark_error_creates_plugin_data_dir_if_missing
PASS test_mark_error_emits_no_stdout
PASS test_mark_error_no_op_on_missing_session_id
PASS test_mark_error_unconditional_even_on_malformed_stdin
PASS test_mark_error_unconditional_even_on_non_utf8_stdin
PASS test_capture_emits_nudge_when_marker_exists
PASS test_capture_no_op_when_different_session_has_no_marker
PASS test_capture_no_op_when_no_marker_at_all
PASS test_capture_does_not_delete_the_marker
PASS test_capture_no_op_on_missing_session_id
PASS test_capture_no_op_on_malformed_stdin
PASS test_capture_no_op_on_non_utf8_stdin
PASS test_end_to_end_mark_then_capture_same_session
PASS test_end_to_end_clean_session_writes_nothing
PASS test_sanitization_is_consistent_between_write_and_read
PASS test_marker_partitioning_is_isolated_per_project_dir
PASS test_no_non_stdlib_imports
All 18 tests passed
```

## Manual verification (not part of the automated suites)

Ran the real `server/reindex.py` CLI standalone against a scratch
directory to confirm both path modes on disk, not just in pytest's
monkeypatched environment:

- `CLAUDE_PROJECT_DIR` set, `CLAUDE_PLUGIN_DATA` unset → index landed at `.debug-memory/.hindsight-cache/index.json` (fallback, I4 canonical name).
- `CLAUDE_PROJECT_DIR` + `CLAUDE_PLUGIN_DATA` both set → index landed at `<plugin-data>/<basename>-<hash>/index.json` (production, C1 partitioning) — confirmed slug shape `hindsight-smoke-cae0291dd8d5`.

## Concerns / judgment calls worth flagging

1. **Slug collisions across `CLAUDE_PLUGIN_DATA` roots aren't addressed** — this fix partitions by project only, not by plugin version or install location. Out of scope for C1 as stated (which is specifically about the per-project sharing bug), but worth knowing if a future finding surfaces "moved my repo, lost my cache" — that's expected: the slug is a hash of the project dir path, so moving/renaming a repo directory changes its slug and orphans the old cache subdirectory (harmless — it's rebuildable, just an unused leftover directory, same as any stale cache).
2. **`clear_capture_marker` now creates an extra empty subdirectory as a side effect of merely checking marker existence** for a project that never had a real tool failure — this was already true before my change (the pre-existing `_plugin_data_dir()`/`_cache_dir()` both eagerly `mkdir(parents=True, exist_ok=True)` on every call, marker-check calls included) and I didn't change that eagerness, just relocated where it happens. Flagging in case a future review wants `_cache_dir()`/`_plugin_data_dir()` to become lazier (not exercised by this pass's findings).
3. Deleting a stale/foreign `index.json` inside `search()` (M1 fix) is a side effect a caller invoking `index.search()` directly (not via `search_lessons`) might not expect. I judged this acceptable and documented it prominently in `search()`'s own docstring, consistent with the module's existing "index cache always rebuildable, never authoritative" philosophy — flagging for visibility since it's a judgment call, not a directive from the finding.
