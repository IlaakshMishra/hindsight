# Task 5 report: `/hindsight` manual skill + list/prune tools

Status: DONE

## Files created

- `skills/hindsight/SKILL.md` — the `/hindsight` skill. Frontmatter is
  just `name`/`description` (confirmed this is the actual shape real
  installed skills use by reading
  `.../superpowers/6.1.1/skills/subagent-driven-development/SKILL.md`,
  `.../systematic-debugging/SKILL.md`, and `.../writing-skills/SKILL.md`
  — all three use only `name` + `description`, nothing else; fields like
  `argument-hint`/`allowed-tools` only showed up in a `commands/*.md`
  slash-command file I also checked, not in any `SKILL.md`, so I did not
  add them here). Body gives Claude instructions (not code) for each of
  the four subcommands — `save`, `search <query>`, `list`, `prune <id>`
  — including the exact `save_lesson` field names/types to walk the user
  through, the exact result shape `search_lessons` returns, and a
  confirm-before-delete step for `prune`. References the MCP tools by
  their Claude-Code-facing names (`mcp__hindsight__search_lessons` etc.,
  the standard `mcp__<server>__<tool>` pattern, server name `hindsight`
  from `.mcp.json`).

## Files edited

- `server/store.py` — added `delete_lesson(lesson_id: str, lessons_dir:
  Path | str) -> bool`. Deletes `lessons_dir/<lesson_id>.md` if present,
  returns `True`; returns `False` (not an error) if no matching file
  exists, including when `lessons_dir` itself doesn't exist yet (mirrors
  `list_lessons`'s existing treatment of a missing directory). Updated
  the module docstring's public-API list to include it.
- `server/main.py` — added the `prune_lesson(id: str) -> dict[str, Any]`
  `@mcp.tool()`. Resolves `lessons_dir`/`cache_dir` via the existing
  `_lessons_dir()`/`_cache_dir()` helpers (no new path-resolution code),
  calls `store.delete_lesson(id, lessons_dir)`, and — only if a file was
  actually deleted — rebuilds the index via `index.build_index(lessons_dir,
  cache_dir)` (same call `save_lesson` already makes). Returns
  `{"deleted": True/False}`. Also updated the module docstring to
  mention the 4th tool and Task 5's addition. `search_lessons`/
  `save_lesson`/`list_lessons` were not otherwise touched.

## Judgment calls

1. **Where `delete_lesson` lives:** the brief said "add `prune_lesson` to
   `server/main.py` / `store.py`" (ambiguous between the two). I put the
   actual file-deletion in `store.py` (as `delete_lesson`) and the
   MCP-tool orchestration (delete + conditional index rebuild) in
   `main.py`'s `prune_lesson`, mirroring the existing `write_lesson`
   (store) / `save_lesson` (main, orchestrates store + index) split.
   `store.py`'s own docstring already frames its job as "decides *where*
   a lesson lives and reads/writes bytes there" — deleting those bytes
   fits that same ownership.
2. **Rebuild-on-not-found:** the brief's prose reads "deletes the `.md`
   file matching that id, then rebuilds the index." I read that as
   describing the successful-delete path, not literally "always rebuild
   even when nothing was deleted" — I skip the rebuild when `deleted`
   is `False` since nothing on disk changed, so the existing index is
   already consistent. This is also safe against the case where the
   index has a stale entry for a file that's already gone by other means:
   `search_lessons` already skips index entries whose file went missing
   (its own docstring/tests cover this), so there's no correctness gap,
   just an avoided no-op rebuild. Documented this reasoning inline in
   `prune_lesson`'s docstring.
3. **No `plugin.json` changes:** checked several other installed
   plugins' manifests (`superpowers`, `gatecheck`, `caveman`) — none
   declare a `skills` field; `skills/*/SKILL.md` is auto-discovered by
   directory convention. Left `.claude-plugin/plugin.json` untouched.
4. **Confirm-before-delete is skill-level, not tool-level:** `prune_lesson`
   itself does not prompt for confirmation (it's a programmatic MCP tool,
   same as the other three) — the confirmation step lives in the
   `/hindsight prune` skill instructions instead, per the brief's own
   wording ("confirms, then calls prune_lesson").

## Tests

`uv run --no-project --with-requirements server/requirements.txt pytest server/tests/` — 96 passed (89 prior + 7 new: 4 in `test_store.py` for `delete_lesson` — deletes existing file, leaves other files alone, returns `False` for no match, returns `False` on a missing `lessons_dir`; 3 in `test_main.py` for `prune_lesson` — save → confirm searchable → prune → file gone and no longer returned by `search_lessons` for a previously-matching query; prune of a never-saved id returns `{"deleted": False}` without erroring; pruning one of two saved lessons leaves the other listed/intact).

Also ran `claude plugin validate .` — passes with the same pre-existing
"no author information" warning Task 1's report already noted (unrelated
to this task).

## Concerns

None blocking. One thing worth a human glance later (not fixed here,
out of this task's scope): `prune_lesson`'s `id` parameter shadows the
Python builtin `id()` within the function body — this exactly matches
the brief's literal required signature (`prune_lesson(id: str)`) and the
codebase's own existing convention of using `id` as a field/param name
(`schema.Lesson.id`, `Lesson(id=...)` throughout), so I kept it verbatim
rather than deviating from the specified signature.

## Fix: path-traversal containment check

A reviewer found and confirmed by direct reproduction a real path-
traversal bug in `delete_lesson`/`prune_lesson`: `Path(lessons_dir) /
f"{lesson_id}.md"` (the only path construction in `delete_lesson`) used
the caller-supplied `lesson_id` with zero validation. Two independent
exploit shapes:

1. **Absolute-path id.** Pathlib's `/` operator discards the left
   operand entirely when the right one is absolute:
   `Path("/tmp/some/lessons") / "/etc/passwd.md"` evaluates to
   `Path("/etc/passwd.md")`, not an error and not a path under
   `lessons_dir`. So `prune_lesson(id="/etc/passwd")` would attempt to
   delete `/etc/passwd.md` outright (would only fail for lack of
   permissions/the literal file not existing, not because the code
   stopped it).
2. **Relative traversal id.** An id like `"../../../../tmp/evil"`
   produces `lessons_dir/../../../../tmp/evil.md`, which
   `Path.exists()`/`.unlink()` follow without normalization, escaping
   `lessons_dir` via the `..` segments.

Either shape let a caller of the `prune_lesson` MCP tool delete an
arbitrary `.md`-suffixed file anywhere the server process can write —
not confined to a saved lesson, and not confined to `lessons_dir` at
all.

### What changed

- **`server/store.py`**: added a private helper `_resolve_lesson_path(lesson_id, lessons_dir) -> Path`
  that every caller-supplied-id-to-path construction must now go
  through, with two independent checks:
  1. *Name-only check*: `lesson_id` must be non-empty, must equal
     `Path(lesson_id).name`, and must not be `"."` or `".."`. The
     equality check alone rules out absolute paths and any embedded
     `/`, but **not** a bare `".."` — verified directly on this
     environment's pathlib that `Path("..").name == ".."` (i.e. `".."`
     is its own `.name`, so the equality check alone lets it through);
     it needed its own explicit rejection alongside `"."`.
  2. *Resolved-parent check* (defense in depth): after building the
     candidate path from an id that already passed check 1, `.resolve()`
     it and require its parent to equal `lessons_dir.resolve()` exactly.
     This is not redundant with check 1 — it catches things the
     string-shape check can't see, e.g. a symlink sitting at
     `lessons_dir/<id>.md` that points outside `lessons_dir` (added a
     dedicated regression test for exactly this,
     `test_delete_lesson_rejects_symlink_escaping_lessons_dir`).

  Either check failing raises `ValueError` with a message naming the
  offending id and which check it failed.

  `delete_lesson` now calls `_resolve_lesson_path` before touching the
  filesystem at all; its `path.exists()` / `path.unlink()` logic is
  otherwise unchanged. Updated both `delete_lesson`'s own docstring and
  the module's top-of-file public-API listing to describe the new
  `ValueError` behavior.

- **`server/main.py`**: no code change to `prune_lesson` — the
  `ValueError` from `store.delete_lesson` is deliberately left
  uncaught. Confirmed (by reading `mcp.server.lowlevel.server`'s
  `_make_error_result`/exception handling directly in the installed
  package, not assumed) that FastMCP's tool dispatch already converts
  an uncaught exception raised inside a `@mcp.tool()` function into a
  `CallToolResult(isError=True, ...)` returned to the caller, rather
  than crashing the server process — so letting `ValueError` propagate
  is sufficient to surface it as a proper tool error with no extra
  try/except needed. Did update `prune_lesson`'s docstring to document
  this behavior and the reasoning (see next section).

### Checked for the same bug class elsewhere — none found

- `store.write_lesson`: writes to `lessons_dir/<lesson.id>.md`, but
  `lesson.id` is never raw external input — `server/main.py`'s
  `save_lesson` builds it via `store.make_lesson_id`/`slugify`, which
  only ever emits `[a-z0-9]` tokens hyphen-joined with a `YYYY-MM-DD`
  date prefix (regex `_SLUG_WORD_RE = re.compile(r"[a-z0-9]+")`) —
  structurally incapable of containing `/`, `\`, or `..`. Not
  applicable; left unchanged.
- `store.read_lesson`: takes a `Path` object, not a bare id string.
  Every call site passes an already-resolved `Path` — `list_lessons`
  (globs `lessons_dir` itself) and `server/main.py`'s `search_lessons`
  (reads `hit["path"]` back out of the locally-built index, not
  reconstructed from caller input). Not applicable.
- `store.list_lessons`: globs `lessons_dir`, takes no id input at all.
  Not applicable.
- `server/main.py`'s other three tools: `search_lessons(query, k)` only
  uses `query` for embedding, never for path construction;
  `save_lesson(...)` never accepts an `id` parameter (auto-derived, see
  above); `list_lessons()` takes no parameters. None build a path from
  unvalidated external input.
- `server/index.py`: grepped for any `lesson_id`/path-join-from-string
  pattern — none found. It only ever globs `lessons_dir` or reads back
  paths it wrote into its own index.

So the vulnerability was fully confined to the one call path the
reviewer flagged (`prune_lesson` → `store.delete_lesson`), and the fix
closes it at its single choke point (`_resolve_lesson_path`) rather than
needing to be duplicated anywhere else.

### Raise vs. `False` — decision and justification

Chose to **raise `ValueError`** on an invalid/malicious id rather than
return `False`. Reasoning:

- Every `lesson_id` this codebase itself ever generates
  (`store.make_lesson_id` → `slugify`) is already, by construction, a
  safe bare filename component — confirmed above, not assumed. So a
  `lesson_id` that fails validation cannot arise from any normal
  internal flow (there is no code path where `save_lesson`'s own output
  later gets fed back into `delete_lesson` in a malformed shape).
- That means a validation failure can only happen because a caller
  invoked the `prune_lesson` MCP tool directly with a hand-crafted id —
  i.e., it is evidence of a malformed-or-hostile call, not a legitimate
  "no such lesson" outcome.
- Returning `False` for this case would make it indistinguishable from
  the ordinary, expected "pruning an id that's already gone" outcome
  (which legitimately returns `False` today and still does). Collapsing
  a security-relevant rejection into that same silent, unremarkable
  `False` would mask exactly the kind of input a caller (or whoever's
  driving the MCP client) most needs visibility into.
- Raising surfaces as a clear MCP tool error (`isError: true`,
  confirmed via `mcp.server.lowlevel.server`, see above) rather than a
  crash or a silently-wrong success-shaped response — the right
  trade-off given this is a hostile-input path, not a routine one.

### New tests

`server/tests/test_store.py` (8 new, under a new "path-traversal
rejection" section, each planting a real victim file outside
`lessons_dir` in a scratch location and asserting it's untouched after
the call, not just that the call raises):
- `test_delete_lesson_rejects_absolute_path_id_and_leaves_victim_file_alone`
- `test_delete_lesson_rejects_relative_traversal_id_and_leaves_victim_file_alone`
- `test_delete_lesson_rejects_id_with_embedded_slash_and_leaves_victim_file_alone`
- `test_delete_lesson_rejects_bare_dot_dot_id`
- `test_delete_lesson_rejects_bare_dot_id`
- `test_delete_lesson_rejects_empty_id`
- `test_delete_lesson_rejects_symlink_escaping_lessons_dir` (exercises
  the resolved-parent defense-in-depth layer specifically, using a
  well-formed bare id that only the second check catches)
- `test_delete_lesson_well_formed_id_still_works_after_traversal_fix`
  (regression guard: normal, legitimate deletes are unaffected)

`server/tests/test_main.py` (3 new, under a new "path-traversal
rejection" section, same victim-file-survives pattern, exercised through
the actual `prune_lesson` MCP tool function rather than `store`
directly):
- `test_prune_lesson_rejects_absolute_path_id_and_leaves_victim_file_alone`
- `test_prune_lesson_rejects_relative_traversal_id_and_leaves_victim_file_alone`
- `test_prune_lesson_rejects_id_with_embedded_slash`

All pre-existing `delete_lesson`/`prune_lesson` tests (the 7 from the
original Task 5 pass) were left unchanged and still pass unmodified.

### Full test run

Command: `uv run --no-project --with-requirements server/requirements.txt pytest server/tests/ -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-8.3.4, pluggy-1.6.0
collected 107 items

... (all 107 tests, including every test_store.py / test_main.py test
    listed above) ...

============================= 107 passed in 0.59s ==============================
```

**107 passed, 0 failed** — 96 prior + 11 new (8 in `test_store.py`, 3 in
`test_main.py`). No regressions; every pre-existing test still passes
unmodified.
