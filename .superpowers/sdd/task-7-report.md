# Task 7 Report: Automatic capture — session marker, Stop hook, lesson-distiller agent

## Status: COMPLETE

## Files created

- `hooks/mark_error.py` — new `PostToolUseFailure` hook script. Touches
  an empty marker file at `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`.
  Creates the plugin-data directory if missing. Emits no stdout at all
  (deliberately — see below). Never fails/blocks: malformed/non-UTF-8
  stdin, missing `session_id`, or filesystem errors all degrade to a
  silent exit 0.
- `hooks/capture.py` — new `Stop` hook script. Reads `session_id` from
  the Stop payload, checks for that session's marker file. No marker (or
  no usable `session_id`, or malformed stdin) → exit 0, empty stdout.
  Marker exists → prints the exact required `hookSpecificOutput` JSON
  and exits 0. Never deletes the marker.
- `agents/lesson-distiller.md` — new plugin subagent. Frontmatter:
  `name: lesson-distiller`, `description`, `tools: Read, Bash,
  mcp__hindsight__save_lesson`, `model: inherit`. Body: decide whether
  the incident is actually resolved (decline otherwise); structure the
  dispatch-prompt summary into `save_lesson`'s exact input shape
  (title, domain[], error_signature, symptom, failed_approaches[],
  root_cause, fix, confidence — `probable` unless verified); never
  fabricate a failed-approach; scrub secrets/tokens/customer data itself
  before calling (belt-and-suspenders on `server/scrub.py`); call
  `save_lesson`; on success, `rm -f` the session's marker file via Bash
  using the same `session_id` sanitization the hooks use; report back.
- `hooks/tests/test_mark_and_capture.py` — 17 tests, standalone-runnable
  and pytest-discoverable (mirrors `test_retrieve.py`'s style). Covers:
  marker creation at the right path, plugin-data-dir auto-creation,
  silent stdout from `mark_error.py`, missing-`session_id` no-ops,
  malformed/non-UTF-8 stdin resilience (both scripts), the capture
  nudge's exact JSON on a matching marker, the no-op case for a
  different/no-marker session, marker survival after `capture.py` runs,
  an end-to-end mark→capture same-session flow, an end-to-end
  no-failures-ever-happened flow, a path-traversal-shaped `session_id`
  round-trip/sanitization-consistency check, and a stdlib-only-imports
  AST check for both scripts.

## Files edited

- `hooks/hooks.json` — added `mark_error.py` as a second command inside
  the existing `PostToolUseFailure` matcher group (Task 6's `retrieve.py`
  entry untouched, same array, order preserved), and a new `Stop` event
  section running `capture.py`. `hooks/retrieve.py` itself was not
  touched.

## Test summary

`python3 hooks/tests/test_mark_and_capture.py` → 17/17 passed.
`python3 -m pytest hooks/tests/ -v` → 22/22 passed (17 new + 5 pre-existing
Task 6 `test_retrieve.py` tests, confirming Task 6's behavior is intact).
`uv run --no-project --with-requirements server/requirements.txt pytest server/tests/ -q`
→ 107/107 passed (untouched; `server/` was not modified).

## Verification notes

- **`Stop` payload's `session_id` field**: fetched
  `https://code.claude.com/docs/en/hooks.md` live (not assumed by
  analogy with `PostToolUseFailure`). Its "Common input fields" section
  explicitly lists `session_id` ("Current session identifier") as a
  field present on *every* hook event's payload; a second, more targeted
  fetch of the `Stop`-specific section's own JSON example also showed
  `session_id`. Both are cited in `hooks/capture.py`'s module docstring.
- **`additionalContext` merge behavior**: fetched the docs' "Hook
  execution"/JSON-output guidance to confirm two hooks registered for
  the same event both run and, if both emit `additionalContext`, Claude
  receives all of them concatenated. Since `mark_error.py` emits no
  `hookSpecificOutput` at all, this is moot in practice, but it confirms
  adding a second `PostToolUseFailure` command is safe and can't corrupt
  or duplicate `retrieve.py`'s existing nudge.
- **Exact nudge text**: verified programmatically — regex-extracted the
  brief's literal `additionalContext` string and asserted byte-for-byte
  equality against `capture.py`'s `ADDITIONAL_CONTEXT` constant before
  writing any tests (360 chars, one em dash U+2014, straight ASCII
  apostrophes). The test suite also asserts this against the real
  subprocess's stdout, not just a second hand-copied literal.
- **Subagent frontmatter/tool-restriction shape**: confirmed against
  `https://code.claude.com/docs/en/sub-agents.md` (fields: `name`,
  `description`, `tools` as a comma-separated allowlist string, `model`,
  etc.; MCP tools are named `mcp__<server>__<tool>` in that list) and
  cross-checked against a real installed agent file
  (`.../superpowers/.../agents/code-reviewer.md`).

## Judgment calls (documented in-file where they matter most)

1. **Marker-write script is a separate file (`mark_error.py`), not an
   edit to `retrieve.py`.** Chosen over extending `retrieve.py` directly
   because the environment constraints explicitly said not to touch
   `retrieve.py`'s core behavior; a second hooks.json command entry is
   the brief's own suggested alternative and keeps Task 6's file, tests,
   and behavior completely undisturbed.
2. **`mark_error.py` emits no stdout at all** (not even an empty
   `hookSpecificOutput`), so it can never interact with or duplicate
   `retrieve.py`'s nudge for the same event, confirmed safe per the
   merge-behavior check above.
3. **Env-var helper duplicated a second time, not factored into a
   shared `hooks/` module.** The brief only forbade importing from
   `server/`; sharing between `mark_error.py`/`capture.py` themselves
   was left open. Chose to duplicate (byte-for-byte identical in both
   files) to keep every hook script fully standalone/dependency-free,
   matching the precedent Task 6's `retrieve.py` set (verified by its
   own `test_no_non_stdlib_imports`). Documented in both files'
   docstrings.
4. **`session_id` sanitized to `[A-Za-z0-9_-]`** before being used in a
   marker filename (unsafe chars replaced with `_`), in both hook
   scripts and the agent's deletion command, identically. Not explicitly
   required by the brief, but mirrors the precedent set by
   `server/main.py`'s `prune_lesson` path-traversal fix; covered by a
   dedicated round-trip test.
5. **`lesson-distiller`'s `tools` includes `Bash`**, beyond the brief's
   literal "hindsight MCP tools plus Read" — required because deleting
   the marker file has no dedicated tool; `Bash rm -f` is the only way
   to do it. Documented in the agent file itself.
6. **Whether `$CLAUDE_PLUGIN_DATA` is actually visible inside the
   subagent's `Bash` tool subprocess is unconfirmed** — the docs
   explicitly document env-var injection into hook/MCP/LSP subprocesses,
   but not into ordinary `Bash`-tool invocations during a normal turn.
   Design choice: have the agent reference `$CLAUDE_PLUGIN_DATA`
   directly in its `rm` command (mirroring how `hooks.json` itself
   references `${CLAUDE_PLUGIN_ROOT}`), and treat a failed/no-op
   deletion as non-fatal and self-reported rather than a hard error —
   this degrades gracefully to "the nudge might fire once more on a
   later `Stop` in the same session," which is the same acceptable
   failure mode the "don't delete from the hook" design already accepts
   for an unresolved session. Documented at length in
   `agents/lesson-distiller.md` step 4.
7. **`lesson-distiller`'s tool access excludes `search_lessons`** (no
   dedup-against-existing-lessons capability). Kept to the brief's
   literal minimal scope (structure → save → delete marker) rather than
   expanding it.

## Concerns

- Judgment call #6 above (Bash-tool env var visibility) is the one
  genuine open question I could not resolve from documentation alone —
  it can only be confirmed by watching a real dispatched
  `lesson-distiller` run in a live Claude Code session. The design
  degrades safely either way (worst case: one redundant `Stop` nudge
  later in the same session), so I did not treat this as blocking, but
  flagging it for whoever does the first live end-to-end run.
- `agents/lesson-distiller.md` and the Stop-hook nudge text both
  reference `subagent_type: lesson-distiller` — this task doesn't wire
  up *automatic* dispatch (Claude decides whether/when to dispatch based
  on the nudge, per the brief's factual-not-imperative phrasing); that's
  expected per spec, not a gap.
- No `server/` files were touched, and `hooks/retrieve.py` is untouched
  (confirmed via `git`-free diff review — this environment has no `.git`
  in the repo root, so I visually diffed via `Read` before/after rather
  than `git diff`).

## Fix: marker cleanup via MCP tool instead of Bash

### Bug (recap)

`agents/lesson-distiller.md` deleted the per-session capture marker with
a `Bash`-tool `rm -f "${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker"`.
A reviewer confirmed via live docs
(`code.claude.com/docs/en/plugins-reference.md`) that
`CLAUDE_PLUGIN_DATA`/`CLAUDE_PLUGIN_ROOT`/`CLAUDE_PROJECT_DIR` are only
exported to hook processes and MCP/LSP server subprocesses, not to a
`Bash`-tool invocation during a normal agent turn (the sibling variable
`CLAUDE_PROJECT_DIR` has an identical filed report of the same failure
mode: anthropics/claude-code#33815). So `${CLAUDE_PLUGIN_DATA}` expanded
to empty, the command became `rm -f "/session-<id>.marker"`, and `rm -f`
silently no-op'd — the marker was never deleted, and `hooks/capture.py`'s
`Stop` nudge kept re-firing for the rest of the session even after the
lesson was already saved. This was Judgment Call #6 in the original
Task 7 report, flagged as an unconfirmed open question at the time; this
fix resolves it in the direction the report's own risk analysis
anticipated.

### Fix

Moved marker deletion into the `hindsight` MCP server (`server/main.py`),
which already reads `${CLAUDE_PLUGIN_DATA}` successfully today via
`_cache_dir()` (used by every existing tool in that file).

**`server/main.py`** — new tool `clear_capture_marker(session_id: str) ->
dict[str, Any]`:
- Reuses `_cache_dir()` directly for the plugin-data directory. Verified
  by reading both `_cache_dir()` and `hooks/mark_error.py`'s
  `_plugin_data_dir()` side by side: both resolve to exactly
  `Path(os.environ["CLAUDE_PLUGIN_DATA"])`, no subdirectory appended on
  either side — so this tool and the hook that writes the marker agree
  on the same real directory.
- New helper `_sanitize_session_id()` — a third byte-for-byte copy of
  `hooks/mark_error.py`'s `_SAFE_CHARS_RE.sub("_", session_id)` regex
  (`[^A-Za-z0-9_-]` → `_`), read directly from `hooks/mark_error.py` to
  confirm the exact pattern before replicating it. Duplicated rather
  than imported, for the same reason the two hook scripts already
  duplicate it between themselves (see that file's own docstring):
  hooks are separate, dependency-free subprocesses from this server
  process, no shared module either side already imports from.
- New helper `_resolve_marker_path(session_id, plugin_data_dir)` —
  mirrors `store.py`'s `_resolve_lesson_path` two-check structure
  (read directly before writing this): (1) a name-only check on the
  *raw* `session_id` — non-empty, equals `Path(session_id).name`, not
  `.`/`..` — raising `ValueError` on anything path-traversal-shaped
  (`/etc/passwd`, `../../etc/evil`, an embedded `/`), the same way
  `prune_lesson` rejects a hostile `id`; (2) a resolved-parent check on
  the sanitized candidate path as defense in depth (symlink escape),
  matching `_resolve_lesson_path`'s own rationale for why neither check
  alone is sufficient.
- `clear_capture_marker` itself: resolve the path, return `{"cleared":
  False}` if it doesn't exist, otherwise `unlink()` and return
  `{"cleared": True}` — mirrors `prune_lesson`'s not-found-is-not-an-
  error pattern exactly. A path-traversal-shaped `session_id` raises
  `ValueError` uncaught (FastMCP turns that into an `isError: true` tool
  result), same as `prune_lesson`.

**Judgment call — raw-`session_id` rejection vs. mark_error.py's always-
sanitize behavior.** `hooks/mark_error.py` never rejects a `session_id`;
it always sanitizes, silently replacing every unsafe character
(including `/` and `..`) with `_`. The brief asked for two things that
turn out to be in tension for a `session_id` that literally contains a
`/`: (a) mirror `_resolve_lesson_path`'s *rejection* behavior for a
path-traversal-shaped `session_id`, and (b) confirm the tool's
sanitized filename matches what `mark_error.py` actually wrote. Chose:
reject (raise `ValueError`) on a *raw* `session_id` containing a path
separator or `.`/`..`, before any sanitization runs — prioritizing (a),
since it's the literal, explicit instruction ("reject a session_id that
would escape the plugin-data directory") and matches the established
`prune_lesson` security precedent. Non-separator sanitizable characters
(spaces, colons, punctuation, non-ASCII) still pass this check and are
still sanitized identically to `mark_error.py`, so (b) is satisfied for
every *realistic* case — real Claude Code `session_id`s are plain
UUID-shaped strings with no separators, so this distinction is only
reachable via a hand-crafted adversarial value, never a real session.
Documented at length in `_resolve_marker_path`'s docstring. Net effect:
for an actually-hostile `session_id`, this tool refuses to touch
anything rather than silently deleting a differently-named file — the
same failure mode `agents/lesson-distiller.md` step 4 already treats as
non-fatal-and-self-reported (worst case: one redundant `Stop` nudge
later in the session, never a wrong deletion).

**`agents/lesson-distiller.md`**:
- `tools:` frontmatter: removed `Bash` (nothing else in the agent body
  used it — re-read the full file to confirm; steps 1–3 are pure
  reasoning/tool-calls, step 5 is a text report), added
  `mcp__hindsight__clear_capture_marker`. Final list: `Read,
  mcp__hindsight__save_lesson, mcp__hindsight__clear_capture_marker`.
- Step 4 rewritten: calls `mcp__hindsight__clear_capture_marker` with
  the dispatch prompt's `session_id` instead of building an `rm -f`
  shell command. Same non-fatal/self-reported degradation on failure as
  before (lesson is already saved by that point, so a failed clear is
  reported, not treated as an overall task failure). Added a short
  explanatory aside noting the earlier `Bash`-based approach and why it
  didn't reliably work, so a future reader doesn't wonder why this
  looks different from the Task 7 report's original design.

**`hooks/capture.py`**: `hooks/mark_error.py` has no reference to "the
distiller deletes this via Bash" anywhere in its docstring or comments
(confirmed by re-reading the whole file and grepping for `Bash`/
`distiller`/`deletes`/"delete.*marker" — no match), so it needed no
edit. `hooks/capture.py` did have one relevant sentence ("Deletion only
happens after a real save, from `agents/lesson-distiller.md`") that,
while not literally wrong, didn't name the mechanism — updated it to
say deletion happens "from `agents/lesson-distiller.md` calling the
`hindsight` MCP server's `clear_capture_marker` tool," with a brief note
that an earlier version used `Bash` and why that didn't work, for the
same future-reader reason as the `agents/lesson-distiller.md` aside
above.

### New tests (`server/tests/test_main.py`)

Added `import json`, `import os`, `import sys` and a `MARK_ERROR_PY`
path constant (pointing at the real `hooks/mark_error.py`, two levels up
from `server/tests/`). Nine new tests, using the existing
`isolated_project` fixture:

- `test_clear_capture_marker_deletes_an_existing_marker` — marker on
  disk → `{"cleared": True}`, file actually gone.
- `test_clear_capture_marker_is_a_no_op_on_a_missing_marker` —
  `{"cleared": False}`, no error, nothing on disk.
- `test_clear_capture_marker_leaves_other_sessions_markers_alone` —
  deletes only the targeted session's marker.
- `test_clear_capture_marker_rejects_relative_traversal_session_id_and_leaves_victim_file_alone`,
  `test_clear_capture_marker_rejects_absolute_path_session_id_and_leaves_victim_file_alone`,
  `test_clear_capture_marker_rejects_session_id_with_embedded_slash`,
  `test_clear_capture_marker_rejects_dot_dot_session_id`,
  `test_clear_capture_marker_rejects_empty_session_id` — direct adaptation
  of `prune_lesson`'s existing path-traversal rejection tests (same
  victim-file-survives assertion pattern), for `clear_capture_marker`'s
  own `_resolve_marker_path` check.
- `test_clear_capture_marker_matches_mark_error_pys_sanitization` — runs
  the real `hooks/mark_error.py` as a subprocess (same invocation
  pattern `hooks/tests/test_mark_and_capture.py` itself uses) with a
  `session_id` containing sanitizable-but-non-separator characters
  (`"session: weird chars! ☃"`), confirms it wrote exactly one marker
  file, then calls `main.clear_capture_marker` with the same raw
  `session_id` and asserts it found and deleted that exact file — a real
  cross-process confirmation that the two independent sanitization
  copies (`hooks/mark_error.py`'s and `main._sanitize_session_id`'s)
  actually agree, not just two hand-copied regexes asserted equal to
  each other.

### Test run output

`python3 hooks/tests/test_mark_and_capture.py`:
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
PASS test_no_non_stdlib_imports
All 17 tests passed
```

`python3 -m pytest hooks/tests/ -v` → **22/22 passed** (17 `test_mark_and_capture.py`
+ 5 pre-existing `test_retrieve.py`, unchanged — confirms this fix,
which touches no hook script logic, left Task 6/7's hook behavior
intact).

`uv run --no-project --with-requirements server/requirements.txt pytest server/tests/ -v`
→ **116/116 passed** (107 pre-existing + 9 new `clear_capture_marker`
tests in `test_main.py`; every pre-existing test in
`test_main.py`/`test_store.py`/`test_schema.py`/`test_scrub.py`/
`test_index.py` still passes unchanged).

### Files changed

- `server/main.py` — new `clear_capture_marker` MCP tool +
  `_sanitize_session_id`/`_resolve_marker_path` helpers + module
  docstring update.
- `server/tests/test_main.py` — 9 new tests + supporting imports/constant.
- `agents/lesson-distiller.md` — `tools:` frontmatter (removed `Bash`,
  added `mcp__hindsight__clear_capture_marker`) + step 4 rewritten.
- `hooks/capture.py` — one docstring sentence updated to name the actual
  deletion mechanism.
- `hooks/mark_error.py` — no change needed (no reference to the old
  Bash-based deletion mechanism existed in this file).

### Status: COMPLETE
