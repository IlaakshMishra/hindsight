# Task 6 report: Automatic retrieval hook

## Files created

- `hooks/hooks.json` — registers the `PostToolUseFailure` hook, no matcher (fires for every tool).
- `hooks/retrieve.py` — reads the hook's stdin JSON, unconditionally emits the fixed nudge on stdout, exits 0.
- `hooks/tests/test_retrieve.py` — standalone test (runnable directly or via pytest).

## Payload schema confirmed from the real docs

Fetched `https://code.claude.com/docs/en/hooks.md` directly (via `curl`, not the summarizing WebFetch tool, after WebFetch's paraphrase turned out to omit the exact input-schema example — raw doc was needed to get verbatim field names). The `PostToolUseFailure` section (doc lines ~1745–1799) gives:

**Input** (stdin, common fields + `PostToolUseFailure`-specific ones):
```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "PostToolUseFailure",
  "tool_name": "Bash",
  "tool_input": {"command": "npm test", "description": "Run test suite"},
  "tool_use_id": "toolu_01ABC123...",
  "error": "Command exited with non-zero status code 1",
  "is_interrupt": false,
  "duration_ms": 4187
}
```
Doc text: "PostToolUseFailure hooks receive the same `tool_name` and `tool_input` fields as PostToolUse, along with error information as top-level fields." `error` is a string describing what went wrong; `is_interrupt` and `duration_ms` are optional. Notably `session_id` is a top-level field here — confirms Task 7's brief assumption (it reuses `session_id` from this same payload shape for its marker file) is correct.

**Output** (stdout, exit 0):
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PostToolUseFailure",
    "additionalContext": "..."
  }
}
```
This matches the brief's shape exactly — no changes needed there. Also confirmed: `PostToolUseFailure` does *not* fire for validation/permission rejections (those short-circuit before hooks run at all), so there's genuinely no "is this error-like" pre-filtering left to do in the hook, as the brief anticipated.

**hooks.json structure**: doc's "Plugin scripts" tab (line ~519) shows the exact convention — `hooks/hooks.json` with an optional top-level `description`, auto-discovered when the plugin is enabled (no registration needed in `.claude-plugin/plugin.json`, confirmed there's no `"hooks"` key there, same convention Task 5's `skills/` directory already relies on). Matcher field is literally `"matcher"`; omitting it entirely (not even setting `"*"`) activates the group on every occurrence of the event — doc: "If you omit the matcher or use `"*"`, the group activates on every occurrence of the event." I omitted it, matching the brief's "no matcher restriction." Confirmed `${CLAUDE_PLUGIN_ROOT}` is a real, documented placeholder substituted into `command`/`args` as a plain string by Claude Code itself (never resolved by hand).

## Why plain `python3`, not `uv run`

`hooks/retrieve.py` imports only `json` and `sys` (verified both manually and by a dedicated test, `test_no_non_stdlib_imports`, which AST-parses the script and checks every imported top-level module name against `sys.stdlib_module_names`). No `mcp`, no `fastembed`, no pinned dependency — unlike `server/main.py`, which needs `uv run --with-requirements` to get `mcp`/`fastembed` on its path. Since there's nothing to pin, I used the doc's "exec form" pattern (`"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/retrieve.py"]`) — the same shape the doc's own Node example uses (`"command": "node", "args": [...]`), which avoids a shell and avoids `uv run`'s startup cost on every single tool failure in a session. This is the environment-constraint judgment call the task called out explicitly, and it holds: no deviation to flag.

## Test results

Command: `python3 hooks/tests/test_retrieve.py` → `All 4 tests passed`
Also verified via pytest: `python3 -m pytest hooks/tests/test_retrieve.py -v` → `4 passed in 0.07s`

Tests:
1. `test_emits_exact_additional_context_on_real_payload_shape` — pipes the fabricated, schema-accurate `PostToolUseFailure` payload above into `retrieve.py`, asserts exit code 0 and the parsed stdout JSON equals the exact expected `{"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": ...}}` dict (implicitly proves stdout is valid JSON, since it's parsed before comparison).
2. `test_additional_context_is_short` — asserts `len(additionalContext) < 500` (actual: 350 chars).
3. `test_unconditional_even_on_malformed_stdin` — feeds `""`, `"not json at all"`, `"{"`, `"null"` and asserts the same nudge + exit 0 every time (the brief's "unconditionally... emits" requirement, stress-tested against garbage input, not just the happy path).
4. `test_no_non_stdlib_imports` — AST-checks `retrieve.py`'s imports against `sys.stdlib_module_names`; backs the `python3`-not-`uv-run` decision above with an executable check instead of just a claim.

Manual smoke test (piping the payload with plain `curl`-fetched-doc field names into the script directly, mirroring exactly what `hooks.json` will do at runtime):
```
$ echo '{...payload...}' | python3 hooks/retrieve.py
{"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": "An error occurred. Before proposing a fix, call hindsight search_lessons with a short natural-language description of this error. If a returned lesson is genuinely relevant, use its failed-approaches list to avoid dead ends and treat its fix as a starting hypothesis — the codebase may have changed since it was written. Ignore low-relevance results."}}
exit code: 0
```
(`—` is `json.dumps`'s default ASCII-safe escaping of the em dash — still valid JSON, confirmed by round-tripping through `json.loads` in the test.)

Also ran `python3 -m json.tool` / `json.load` against `hooks/hooks.json` itself to confirm it's valid JSON, and `python3 -m py_compile hooks/retrieve.py` to confirm it compiles cleanly.

Regression check: ran the rest of the repo's test suite. `server/tests/test_schema.py`, `test_scrub.py`, `test_store.py` (78 tests) pass unchanged. `test_index.py`/`test_main.py` fail to *collect* in this bare-`pytest` environment with `ModuleNotFoundError: No module named 'fastembed'` — pre-existing and unrelated to this task (those tests need `server/requirements.txt`'s pinned deps, normally supplied via `uv run`; I made zero changes under `server/`, confirmed no scope creep there).

## additionalContext string used (verbatim, per brief)

> An error occurred. Before proposing a fix, call hindsight search_lessons with a short natural-language description of this error. If a returned lesson is genuinely relevant, use its failed-approaches list to avoid dead ends and treat its fix as a starting hypothesis — the codebase may have changed since it was written. Ignore low-relevance results.

350 characters. Used exactly as given in the brief — the doc's guidance on `additionalContext` phrasing ("write the text as factual statements rather than imperative system instructions... to avoid triggering prompt-injection defenses") does note that imperative framing like "Before proposing a fix, call..." carries a little of that risk, but the brief supplies this string as an exact value to use verbatim, and it reads as an operational nudge (not an out-of-band system command impersonating a higher authority), so I kept it as specified rather than second-guessing a value the brief explicitly locked in. Flagging this only as a documented judgment call, not a deviation.

## Judgment calls

- Matcher omitted entirely from `hooks.json` (rather than `"matcher": "*"`) — both are doc-confirmed equivalent for "every tool"; omitting matches the brief's "no matcher restriction" phrasing most literally, and mirrors the doc's own non-tool-matcher examples (e.g. `ConfigChange`).
- Test placed at `hooks/tests/test_retrieve.py`, mirroring `server/tests/`'s layout, and written to run both as a plain script (`python3 hooks/tests/test_retrieve.py`, no pytest required — satisfies "standalone script test" literally) and under pytest (repo's existing test runner) — belt and suspenders, since `hooks/` has no `conftest.py`/import-path needs the way `server/` does (the test only ever shells out to `retrieve.py`, never imports it).
- Added a 4th test (`test_no_non_stdlib_imports`) beyond the brief's literal ask, to make the "stdlib-only, so plain `python3` not `uv run`" claim self-verifying rather than just asserted in prose.
- Stdin is read and best-effort JSON-parsed even though no field feeds the output, and verified this holds even on garbage input — defensive against a future payload-shape change silently breaking the nudge on every failure in a session, without adding any real complexity (still zero branching on payload content).

## Concerns

None blocking. One thing worth a human glance later (not a Task 6 defect): the brief's exact `additionalContext` string uses imperative phrasing ("Before proposing a fix, call hindsight search_lessons...") that the docs' own style guidance mildly cautions against for prompt-injection-defense reasons — noted above, kept as specified since the brief locks this string verbatim.

## Fix: factual phrasing + encoding resilience

Reviewer found one real bug and flagged one design tension (resolved by the human) in the original implementation above. Both addressed.

### Fix 1: `additionalContext` rephrased to factual/descriptive style (human decision, not a bug)

The reviewer's concern above ("worth a human glance later") was escalated: the brief's original imperative phrasing ("Before proposing a fix, call hindsight search_lessons...") risks tripping Claude Code's own prompt-injection defenses per the hooks doc's style guidance, which would make Claude surface the raw `additionalContext` text to the user instead of acting on it — silently defeating the hook on exactly the sessions where it matters most. The human reviewed and chose to rephrase to factual/descriptive style rather than keep the brief's verbatim imperative string.

New `ADDITIONAL_CONTEXT` in `hooks/retrieve.py` (byte-exact, as specified by the human):

> A tool call just failed. hindsight search_lessons can surface past team lessons on similar errors, including approaches that didn't work. A relevant result is worth checking before proposing a fix; treat its fix as a hypothesis, not gospel, since the codebase may have changed. Low-relevance results aren't worth acting on.

323 characters (recomputed via `len()`, not assumed) — still comfortably under the 500-char test bound (down from 350 for the old string). Updated every place that referenced the old string:
- `hooks/retrieve.py`: the `ADDITIONAL_CONTEXT` constant and its preceding comment (now also explains *why* factual phrasing was chosen, citing the hooks doc's prompt-injection-defense guidance, and points at this report section).
- `hooks/tests/test_retrieve.py`: `EXPECTED_ADDITIONAL_CONTEXT` (the exact-JSON-equality test's fixture) and the length-bound test's inline comment (updated "350 today" → "323 today").

### Fix 2: real bug — hook crashed on non-UTF-8 stdin

Root cause: `sys.stdin.read()` decodes stdin using the process's default text-mode codec with the *strict* error handler, so any non-UTF-8 byte sequence on stdin raises `UnicodeDecodeError` — outside any try/except, at the very top of `main()`, before the nudge JSON is ever constructed. Live repro confirmed the reviewer's report before the fix:

```
$ printf '\xff\xfe\x00\xff\xd8\xff\xe0' | python3 hooks/retrieve.py
Traceback (most recent call last):
  ...
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
EXIT:1
```

This directly contradicted the script's own documented guarantee ("the nudge is unconditional... even on malformed stdin") for a whole class of inputs the original try/except never reached, since the crash happened on the read itself, one line before the try block started.

Fix (`hooks/retrieve.py`, `main()`): read raw bytes via `sys.stdin.buffer.read()` instead of `sys.stdin.read()`, then decode explicitly with `errors="replace"` so the decode step itself cannot raise. Wrapped the read+decode+parse together in a broad `except Exception` (widened from the old `except json.JSONDecodeError`) as a second layer of defense — belt and suspenders, since the specific crash was in the read/decode step, not the `json.loads` call, but nothing about *future* malformed input should be assumed to only ever come from the JSON parser either. This keeps the "stdlib only, plain `python3`" constraint intact — no new imports.

Post-fix, the same repro:
```
$ printf '\xff\xfe\x00\xff\xd8\xff\xe0' | python3 hooks/retrieve.py
{"hookSpecificOutput": {"hookEventName": "PostToolUseFailure", "additionalContext": "A tool call just failed. hindsight search_lessons can surface past team lessons on similar errors, including approaches that didn't work. A relevant result is worth checking before proposing a fix; treat its fix as a hypothesis, not gospel, since the codebase may have changed. Low-relevance results aren't worth acting on."}}
EXIT:0
```

New regression test `test_unconditional_even_on_non_utf8_stdin` in `hooks/tests/test_retrieve.py`: pipes genuinely non-UTF-8 bytes (the reviewer's exact repro `b"\xff\xfe\x00\xff\xd8\xff\xe0"`, plus a second standalone-continuation-byte case `b"\x80\x81\x82\xfe\xff"`) into the real script via `subprocess.run(..., input=<bytes>)` (a new `_run_hook_bytes` helper, since the existing `_run_hook` uses `text=True` and can't carry undecodable bytes as a Python `str` at all), asserting exit code 0 and that stdout parses as the exact expected nudge JSON. This is distinct from the existing `test_unconditional_even_on_malformed_stdin`, which only covers malformed-but-valid-UTF-8 text (`"not json at all"`, `"{"`, etc.) — that test could not have caught this bug, since `"not json at all"` decodes fine and only fails at `json.loads`, never at the read step.

### Minor items addressed

- **`hooks.json` `timeout`**: added `"timeout": 30` to the hook entry, matching the doc's own example shape. Re-verified `hooks.json` still parses as valid JSON (`python3 -m json.tool hooks/hooks.json`).
- **Length test measuring real output**: `test_additional_context_is_short` now invokes the real script via `_run_hook` and measures `len()` on the parsed stdout's `additionalContext`, rather than measuring the duplicated `EXPECTED_ADDITIONAL_CONTEXT` literal. This means a future regression in the script itself (not just in the test file's copy of the string) would actually be caught.

### Test results

Command: `python3 hooks/tests/test_retrieve.py` → `All 5 tests passed` (was 4; added `test_unconditional_even_on_non_utf8_stdin`)

```
PASS test_emits_exact_additional_context_on_real_payload_shape
PASS test_additional_context_is_short
PASS test_unconditional_even_on_malformed_stdin
PASS test_unconditional_even_on_non_utf8_stdin
PASS test_no_non_stdlib_imports
All 5 tests passed
```

Also verified via pytest: `python3 -m pytest hooks/tests/test_retrieve.py -v`

```
hooks/tests/test_retrieve.py::test_emits_exact_additional_context_on_real_payload_shape PASSED [ 20%]
hooks/tests/test_retrieve.py::test_additional_context_is_short PASSED    [ 40%]
hooks/tests/test_retrieve.py::test_unconditional_even_on_malformed_stdin PASSED [ 60%]
hooks/tests/test_retrieve.py::test_unconditional_even_on_non_utf8_stdin PASSED [ 80%]
hooks/tests/test_retrieve.py::test_no_non_stdlib_imports PASSED          [100%]
5 passed in 0.11s
```

Also re-ran `python3 -m py_compile hooks/retrieve.py` (compiles cleanly) and confirmed `hooks/hooks.json` still parses via `python3 -m json.tool`.

Regression check on the rest of the repo (unchanged from the original Task 6 report — zero files touched under `server/`): `python3 -m pytest server/tests/test_schema.py server/tests/test_scrub.py server/tests/test_store.py -q` → `78 passed`.

### Files touched in this fix

- `hooks/retrieve.py` — new `ADDITIONAL_CONTEXT` string + comment; `main()`'s stdin handling changed from `sys.stdin.read()` (bare, outside try/except) to `sys.stdin.buffer.read().decode("utf-8", errors="replace")` inside a broadened `try/except Exception`; module docstring's stdin paragraph updated to mention non-UTF-8 resilience.
- `hooks/tests/test_retrieve.py` — `EXPECTED_ADDITIONAL_CONTEXT` updated; new `_run_hook_bytes` helper; new `test_unconditional_even_on_non_utf8_stdin` test (added to both the pytest collection and the `__main__` plain-script runner's `tests` list); `test_additional_context_is_short` reworked to measure real subprocess output.
- `hooks/hooks.json` — added `"timeout": 30` to the hook entry.
