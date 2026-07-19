# Task 2 report: Lesson schema + secret scrubber

## Files created

- `templates/LESSON_TEMPLATE.md` — the reference document shape: YAML
  frontmatter placeholders for `id`, `title`, `domain` (list),
  `error_signature`, `created_at`, `confidence` (`<confirmed|probable>`),
  followed by the five body sections in order: `## Symptom`,
  `## Approaches that FAILED (do not repeat)`, `## Root cause`, `## Fix`,
  `## Tags for retrieval`.
- `server/schema.py` — `Lesson` dataclass with fields matching the plan's
  Global Constraints schema list exactly: `id`, `title`, `domain: list[str]`,
  `error_signature`, `created_at`, `confidence: Literal["confirmed",
  "probable"]`, plus body-backing fields `symptom`, `failed_approaches:
  list[str]`, `root_cause`, `fix`, `tags: list[str]` (backs the "Tags for
  retrieval" section). `__post_init__` validates `confidence` is one of
  the two allowed values and that `id`/`title`/`domain`/`error_signature`/
  `created_at` are non-empty. `render()` hand-emits the frontmatter+body
  markdown document matching `templates/LESSON_TEMPLATE.md`'s shape.
  `match_text()` builds `title + error_signature + domain + tags` per the
  Global Constraints' match-text rule (deliberately excludes
  symptom/root_cause/fix, which is where raw stack traces would live).
- `server/scrub.py` — `scrub(text: str) -> str` and `scrub_payload(payload)`
  (recursive dict/list variant, offered by the brief as an alternative).
  Redacts, in order: PEM private key blocks, DB connection strings, AWS
  access key IDs, AWS secret access keys, bearer tokens, `sk-`-prefixed
  API keys, and a generic long-high-entropy-token catch-all. Every
  redaction is in-place (`[REDACTED]` marker), never removing the
  surrounding sentence.
- `server/tests/conftest.py` — puts `server/` on `sys.path` so test
  modules can `import schema` / `import scrub` regardless of invocation
  cwd (no package `__init__.py` exists in `server/`, matching Task 1's
  flat-script style for `main.py`).
- `server/tests/test_schema.py` — 12 tests: frontmatter delimiter shape,
  all 6 required frontmatter fields present, correct values, all 5 body
  section headers present and in order, body content round-trips,
  empty-list sections still render (no dropped section), confidence
  enum enforcement, required-field emptiness validation, `match_text()`
  composition, and YAML-special-character escaping in quoted scalars.
- `server/tests/test_scrub.py` — 17 tests: one per secret category (AWS
  access key, AWS secret key, `sk-` key, bearer token, Postgres
  connection string, PEM block, generic high-entropy token), a combined
  multi-secret payload, `scrub_payload` dict/list recursion, and — this
  is where most of the actual engineering happened — a battery of
  false-positive regression tests (stack trace, code snippet, plain
  sentence, long kebab-case branch name, long file path, a 40-char git
  commit SHA, a hex checksum) proving ordinary technical prose survives
  untouched.

## `server/requirements.txt` change

Added `pytest==8.3.4` (wasn't present before) with a header comment
documenting the exact `uv run --no-project --with-requirements
server/requirements.txt pytest server/tests/` invocation.

## `.gitignore` change

Added `.pytest_cache/` (repo already had `__pycache__/` and `*.pyc` from
Task 1). No git commands were run — this is a plain text-file edit, and
no git repo exists here per the environment constraint. All generated
`__pycache__`/`.pytest_cache` artifacts from test runs were deleted from
disk before finishing (not left in the tree).

## `server/main.py`: untouched

Per the brief, I did not open this task's diff against `main.py` at all.
Verified at the end: `find . -newer server/main.py` shows `main.py`
itself never appears in the "touched" list, and a fresh `import main`
still succeeds with the same three tools registered
(`search_lessons`, `save_lesson`, `list_lessons`) as Task 1 left it.

## Design notes / judgment calls

1. **Dataclass, not pydantic, for `Lesson`.** The brief allowed either.
   I chose `dataclass` (stdlib only) so `schema.py` has zero third-party
   dependencies — consistent with "no MCP dependency" and lets
   `server/tests/` for this module run without needing anything beyond
   `pytest` in `requirements.txt`. `__post_init__` gives the same
   validation guarantee (reject invalid `confidence`, reject empty
   required fields) pydantic would, just hand-rolled.

2. **Frontmatter is hand-emitted YAML, not built via a `yaml.safe_dump`
   library call.** The frontmatter block is flat and small (6 known
   keys, 2 of which are lists-of-scalars), so I emit it deterministically
   with a small `_yaml_quote`/`_yaml_list` helper rather than adding a
   PyYAML dependency this module otherwise wouldn't need. Scalars are
   double-quoted with backslash/quote escaping (valid YAML for arbitrary
   string content — verified with a dedicated test using a title
   containing embedded quotes and colons). `confidence` is emitted
   unquoted (`confidence: probable`) since it's a plain enum-like scalar,
   matching typical YAML style. This is a real, if minor, coupling risk:
   if a later task parses these files with a full YAML parser instead of
   assuming this exact emission format, that parser needs to actually be
   a YAML parser (which will handle this fine, since it's valid YAML) —
   just flagging that no round-trip *parser* was built in this task, only
   the emitter (`render()`), matching what the brief asked for.

3. **`tags` field name, not `retrieval_tags`.** Global Constraints list
   the body section as `## Tags for retrieval` but don't name a specific
   payload field for it (Task 1's `save_lesson` stub signature —
   `title, domain, error_signature, symptom, failed_approaches,
   root_cause, fix, confidence` — has no tags parameter at all). I added
   a `tags: list[str] = field(default_factory=list)` to `Lesson` (optional,
   defaults to empty, renders `_(none recorded)_` if empty) since the
   schema needs *some* field to back that mandatory body section and
   `match_text()`'s "retrieval tags" component. Naming and wiring
   `tags` into `save_lesson`'s actual input shape is Task 4's problem
   (may derive tags from `domain`, add a new MCP parameter, or something
   else) — not decided here, deliberately, since that's server/main.py
   territory this task doesn't touch.

4. **Secret-scrubbing heuristics, and one bug I caught and fixed before
   finishing.** For the "long (>=32-char) high-entropy token" category, I
   initially implemented a straightforward Shannon-entropy-over-3.5-bits/
   char check requiring both a digit and a letter in the token. Testing
   that against realistic debugging prose (a git commit SHA reference —
   `"introduced in commit 9fceb02d...61d6 on main"`) showed it was a real
   false positive: pure lowercase hex strings (git SHAs, MD5/SHA
   checksums, Docker image IDs) have entropy close to hex's own
   theoretical max (log2(16) = 4 bits/char) *by construction*, not because
   they're secrets, and they're extremely common in exactly the kind of
   ordinary technical prose this scrubber must leave alone. Fixed by
   excluding tokens composed entirely of the hex alphabet
   (`0-9a-fA-F`) from the generic high-entropy catch-all — real
   API-style secrets almost always mix in letters outside `a-f`/`A-F`,
   uppercase+lowercase together, or symbols (`+ـ_=-`), so this exclusion
   costs essentially no true-positive coverage while removing a
   real false-positive class. Added regression tests
   (`test_git_commit_sha_is_not_flagged`, `test_sha256_checksum_is_not_flagged`)
   to lock this in. This is a heuristic, not a proof — a sufficiently
   short/adversarial pure-hex secret (unlikely in practice, since AWS/API
   keys aren't hex-only) would slip through the generic catch-all, though
   AWS keys specifically are still caught by their own dedicated regex
   regardless.
   - The generic token-candidate regex (`[A-Za-z0-9+_=\-]{32,}`)
     deliberately **excludes `/`**, unlike a strict base64 alphabet would
     include. Reason: including `/` made ordinary Unix file paths (which
     are exactly the kind of "ordinary technical prose" the tests must
     protect) collapse into single long "tokens" that would then need
     entropy-filtering to survive — safer and simpler to exclude `/` from
     the candidate charset entirely, accepting that a base64 secret
     containing `/` won't be caught by the *generic* catch-all (AWS
     secret keys, which do use `/`, are still caught by their own
     dedicated context-aware regex, not the generic one).
   - AWS secret access keys (40 base64-alphabet characters, no
     distinguishing prefix) are matched only when preceded by a
     recognizable variable-name context (`aws_secret_access_key`,
     `aws_secret_key`, or `secret_access_key`, case-insensitive) — a bare
     40-character base64 blob with zero context is too ambiguous to
     redact confidently (mirrors how real secret scanners like
     truffleHog/gitleaks handle this key type). AWS access key IDs
     (`AKIA`/`ASIA` + 16 chars) have no such ambiguity and are matched
     unconditionally.
   - DB connection strings and PEM blocks are redacted as a whole
     (entire matched URI / entire BEGIN..END block replaced by a single
     `[REDACTED]`), not just the credential sub-part — simpler, and the
     brief's phrasing ("DB connection strings (`postgres://user:pass@...`
     etc)", "`-----BEGIN...PRIVATE KEY-----` blocks") treats each as one
     redactable unit.

5. **No `server/tests/__init__.py`.** Chose a `conftest.py`-based
   `sys.path` insertion instead of turning `server/` into a proper
   Python package, to stay consistent with `server/main.py` being a flat
   script (not part of a package) — introducing `server/__init__.py` now
   would be an unrequested structural change outside this task's scope.

## Test results

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/
============================= test session starts ==============================
collected 29 items

server/tests/test_schema.py ............                                 [ 41%]
server/tests/test_scrub.py .................                             [100%]

============================== 29 passed in 0.02s ==============================
```

29/29 passed (12 in `test_schema.py`, 17 in `test_scrub.py`). Also
verified separately: `python3 -m py_compile` on all five new/edited `.py`
files (clean), and that `server/main.py` still imports successfully with
its original 3 tools intact after this task's changes (confirming it was
never touched).

## Status

DONE. No blockers. One real bug (git-SHA/checksum false positive in the
high-entropy scrubber) was found during my own testing and fixed before
finishing, not left for review to catch — documented above in judgment
call 4 along with the regression tests that pin the fix. All other
judgment calls (dataclass vs pydantic, hand-emitted YAML, `tags` field
naming, redaction granularity) are reversible in later tasks if new
information from the still-missing original spec doc surfaces (same gap
Task 1 hit and documented; still not present in the repo as of this
task).

## Fix: hex-secret gap + YAML newline escaping

Reviewer found two Important issues via direct execution against the
Task 2 code, both confirmed before fixing (per
`superpowers:receiving-code-review`: verify, don't blind-implement).
Both were real; no pushback needed.

### Finding 1: pure-hex exclusion blind spot for hex-encoded secrets (`server/scrub.py`)

**Confirmed first.** The original `_looks_like_secret()` excluded *any*
token composed entirely of `0-9a-fA-F` from the entropy catch-all,
unconditionally — so `api_key: 5f4dcc3b5aa765d61d8327deb882cf995f4dcc3b`
passed through completely unredacted, since the value happens to be
40 hex chars (a canonical SHA-1/git-SHA length) regardless of the
`api_key:` label right in front of it.

**Design considered and rejected first:** narrowing the exclusion to
"canonical digest length + no label in front, checked via a lookback
window inside the generic high-entropy catch-all's substitution
callback." Prototyped this (context-lookback approach, `_looks_like_secret(token, prefix)`)
and hit two real bugs during testing, not just theoretical concerns:

1. The generic catch-all's candidate regex (`_TOKEN_CANDIDATE_RE`)
   includes `=` in its character class (needed for base64 padding), so
   `SECRET_KEY=<hex>` with no space around `=` gets swallowed as *one*
   combined candidate token — my context-lookback fix correctly flagged
   it as a secret, but redaction replaced the whole
   `SECRET_KEY=<hex>` span, dropping the `SECRET_KEY=` label from the
   output and violating the module's own "redaction is always in place,
   only the offending token" invariant (stated in the module docstring).
2. Building the correct regression fixture for "bare git SHA" exposed a
   **pre-existing typo** in the original test suite: the `test_git_commit_sha_is_not_flagged`
   fixture (`server/tests/test_scrub.py`) was 39 hex characters, not the
   40 its own comment claimed — it happened to pass before only because
   the *old* code exempted all-hex tokens of *any* length. Fixed the
   fixture to a real 40-char SHA-1 (the well-known git "empty tree"
   constant, `4b825dc642cb6eb9a060e54bf8d69288fbee4904`) so the test
   actually exercises the canonical-length case it claims to.

**Final design (implemented):** a dedicated regex, `_LABELED_HEX_SECRET_RE`,
mirroring how `_AWS_SECRET_KEY_RE` already works — match `identifier(:|=)value`
where `identifier` is a plain `[A-Za-z][A-Za-z0-9_]*` and `value` is hex at
one of the three canonical digest lengths (32/40/64), then in the
substitution callback check (case-insensitively, substring match) whether
`identifier` contains `secret`/`key`/`token`/`password`/`credential` — if
so, redact just the value (preserving label, separator, and any
surrounding quote via a backreferenced group); if not, leave untouched.
This runs *before* the generic catch-all, in the same "specific,
low-false-positive patterns" section as the other dedicated regexes, so:

- It naturally avoids the `=`-merging bug (the label is a separate
  capture group, never absorbed into "the redacted span").
- `_looks_like_secret()`'s hex handling could stay simple: pure-hex
  tokens at canonical lengths (32/40/64) are unconditionally exempted
  from the entropy check (same as before), but the exemption is now
  provably safe because any *labeled* hex secret at those lengths was
  already redacted upstream by `_LABELED_HEX_SECRET_RE` — anything
  reaching the generic catch-all as canonical-length pure hex is, by
  construction, unlabeled. Hex at *non-canonical* lengths (e.g. 33-63,
  != {32,40,64}) now falls through to the plain entropy check instead of
  getting a blanket pass — narrowing the original exclusion, per the
  finding's second suggested approach, so a real hex secret that
  happens to land on an odd length isn't given a free pass either.

Trade-off, called out in code comments: `_LABEL_KEYWORDS`/
`_HEX_SECRET_LABEL_KEYWORDS` substring-matches identifiers (so
`api_key`, `SECRET_KEY`, `aws_secret_access_key` all count as labeled,
not just an exact fixed list) — an unrelated identifier that merely
*contains* one of these words (e.g. `monkey:`) would also trigger
redaction of an adjacent canonical-length hex value. For a secret
scrubber, over-redacting on an ambiguous label is the accepted failure
direction (verified: does not affect any real test case; only matters
for a contrived identifier that both contains a keyword substring *and*
happens to be immediately followed by exactly 32/40/64 hex characters).

New/updated tests in `server/tests/test_scrub.py`:
- `test_labeled_hex_secret_api_key_32_chars_is_redacted`
- `test_labeled_hex_secret_api_key_40_chars_is_redacted` (the exact
  shape from the reported finding)
- `test_labeled_hex_secret_secret_key_64_chars_is_redacted`
- `test_labeled_hex_secret_token_is_redacted`
- `test_labeled_hex_secret_survives_surrounding_quotes`
- `test_bare_hex_value_with_no_label_is_still_not_flagged` (regression
  guard: closing the gap must not become "redact all canonical-length
  hex")
- `test_git_commit_sha_is_not_flagged` — fixture corrected from a
  39-char to a real 40-char SHA-1 (see bug #2 above); assertion
  behavior unchanged, still must not be redacted.

### Finding 2: hand-emitted YAML corrupts embedded newlines (`server/schema.py`)

**Confirmed first**, and while probing I found the actual blast radius
was larger than the finding stated. Using `yaml.safe_load` (available
transitively via `mcp`'s own deps in this project's `uv`-managed
environment — confirmed with
`uv run --no-project --with-requirements server/requirements.txt python3 -c "import yaml"`,
so no `requirements.txt` change was needed or made) against small
double-quoted-scalar probes:

- A raw (unescaped) `\n` or `\r` inside a double-quoted YAML scalar
  parses successfully but gets folded to a single space by YAML's
  line-folding rule — the reported bug.
- NEL (U+0085) — a YAML-spec line-break character, same class as
  `\n`/`\r` — has the *same* folding bug, unescaped.
- Any *other* raw C0 control character (tested `\x01`) doesn't fold —
  it makes PyYAML **refuse to parse the document at all**
  (`ReaderError: unacceptable character #x0001`). So a title containing,
  say, a stray `\x07` from copy-pasted terminal output wouldn't just
  corrupt silently — it would make the whole frontmatter block
  unparseable by any real YAML consumer, a strictly worse failure mode
  than the reported one.
- Raw tab parses and round-trips fine as-is (not a line-break
  character), and DEL (0x7F) and Unicode LS/PS (U+2028/U+2029) were also
  checked — LS/PS round-trip fine unescaped, DEL does not.

**Fix:** `_yaml_quote()` now escapes, per character: backslash and `"`
(as before), `\n`/`\r`/`\t`/`\0` via their short named YAML escapes, and
every other C0 control character (0x00-0x1F) plus DEL (0x7F) plus NEL
(U+0085) via a `\xHH` hex escape. Verified against a battery of
hand-picked strings (newline, CR, tab, NUL, DEL, NEL, backslash+quote
mix, all controls at once, LS/PS) round-tripping byte-for-byte through
`yaml.safe_load()` before writing the real fix.

Docstring on `_yaml_quote()` rewritten: no longer claims "valid YAML for
any string content" (the actual overclaim was in this docstring, not at
the ~107-117 line range cited in the finding — that range is `render()`'s
own short docstring, which never made this claim; fixed the one that
did). It now states precisely what's escaped and why (naming the
line-folding failure mode for `\n`/`\r`/NEL and the hard-parse-failure
mode for other control chars), and says the round-trip guarantee is
"verified... to round-trip byte-for-byte through PyYAML's
`yaml.safe_load` for arbitrary `str` input" rather than asserting
general YAML validity as an abstract property.

New tests in `server/tests/test_schema.py` (added `import yaml` and a
`_parse_frontmatter()` helper that slices the `---`-delimited block out
of `render()`'s output and runs it through `yaml.safe_load`):
- `test_title_with_embedded_newline_round_trips_through_yaml_safe_load`
- `test_error_signature_with_embedded_newline_round_trips_through_yaml_safe_load`
- `test_title_with_carriage_return_and_tab_round_trips_through_yaml_safe_load`
- `test_domain_item_with_embedded_newline_round_trips_through_yaml_safe_load`
  (confirms the same escaping applies to list-of-scalar fields via
  `_yaml_list`, not just top-level scalars)

### Minor items

- **Connection-string scheme coverage** — fixed (quick). Added
  `test_mysql_connection_string_is_redacted` and
  `test_mongodb_srv_connection_string_is_redacted` to
  `server/tests/test_scrub.py` alongside the existing Postgres test.
- **AWS secret-key redaction dropping surrounding quotes** — fixed
  (quick, and the exact same backreferenced-quote-group technique was
  already being built for `_LABELED_HEX_SECRET_RE`, so applying it to
  `_AWS_SECRET_KEY_RE` too was near-zero incremental cost). Added
  `test_aws_secret_key_surrounding_quotes_are_preserved`.

### Test results

```
$ uv run --no-project --with-requirements server/requirements.txt pytest server/tests/
============================= test session starts ==============================
collected 42 items

server/tests/test_schema.py ................                            [ 38%]
server/tests/test_scrub.py ..........................                   [100%]

============================== 42 passed in 0.03s ==============================
```

42/42 passed (16 in `test_schema.py`, up from 12; 26 in `test_scrub.py`,
up from 17). Net +13 tests over the pre-fix 29 (4 new schema tests, 9
new scrub tests: 6 labeled-hex-secret cases + 2 connection-string scheme
cases + 1 AWS-quote-preservation case; the git-SHA fixture fix was a
correction to an existing test, not a new one).

Also re-verified after the fix: `python3 -m py_compile` on both edited
`.py` files and both edited test files (clean); `server/main.py`
untouched (`find server -name "*.py" -newer server/main.py` does not
list it) and still imports successfully with its original tools
(`search_lessons`, `save_lesson`, `list_lessons`) intact; all
`__pycache__`/`.pytest_cache` artifacts removed from disk before
finishing.

### Status

DONE. Both Important findings fixed and confirmed via re-run tests, not
just asserted. No blockers. No `server/main.py` changes. No git commands
run (per environment constraint — no repo here).
