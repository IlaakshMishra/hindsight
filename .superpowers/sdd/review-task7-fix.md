# Review package: Task 7 fix (marker cleanup via MCP tool) — no git, file dump


## server/main.py
```
#!/usr/bin/env python3
"""Hindsight MCP server.

Exposes the `hindsight` tool surface (`search_lessons`, `save_lesson`,
`list_lessons`, `prune_lesson`, `clear_capture_marker`) over stdio using
the official MCP Python SDK's FastMCP helper.

Task 4 status: real behavior, replacing Task 1's stubs. Wires Task 2's
`schema.py`/`scrub.py` and Task 3's `index.py` together via `store.py`:
  - `save_lesson` scrubs every free-text field (`scrub.py`) before
    anything touches disk, builds a `Lesson` (`schema.py` -- with an
    auto-derived `id` and retrieval `tags`, see `_derive_tags` below),
    writes it to `.debug-memory/lessons/<id>.md` (`store.py`), rebuilds
    the local similarity index (`index.py`), best-effort `git add`s the
    new file, and returns `{id, path, wrote, warnings?}`.
  - `search_lessons` embeds `query` against the cached index and expands
    each hit back into the full lesson content the tool contract
    promises.
  - `list_lessons` reads every saved lesson from disk via `store.py`.

Task 5 adds `prune_lesson`: deletes a saved lesson's `.md` file by id
(`store.delete_lesson`) and rebuilds the index so a pruned lesson stops
being searchable immediately.

Task 7 review fix adds `clear_capture_marker`: deletes the per-session
capture marker `hooks/mark_error.py` writes at
`${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`. Originally
`agents/lesson-distiller.md` deleted this itself via the `Bash` tool
(`rm -f "${CLAUDE_PLUGIN_DATA}/..."`), but `${CLAUDE_PLUGIN_DATA}` is
only exported to hook processes and MCP/LSP server subprocesses, not to
a `Bash`-tool invocation made during a normal agent turn (confirmed
against `https://code.claude.com/docs/en/plugins-reference.md`; see also
the filed report of the identical failure mode for the sibling
`CLAUDE_PROJECT_DIR` variable, anthropics/claude-code#33815) -- so the
variable expanded to empty, the `rm -f` silently no-op'd on a
nonexistent path, and the marker was never actually deleted. This MCP
tool moves the deletion into the server process itself, which reads
`CLAUDE_PLUGIN_DATA` successfully today (see `_cache_dir` below, already
relied on by every other tool in this file).

Runtime paths (never hardcoded, never resolved by hand into `.mcp.json`
-- that file keeps `${CLAUDE_PLUGIN_ROOT}` as a literal, Claude-Code-
substituted token, unrelated to the two variables this module reads):
  - Lessons live at `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`.
  - The index cache lives at `${CLAUDE_PLUGIN_DATA}`.
  Confirmed against the official Claude Code docs
  (https://code.claude.com/docs/en/mcp.md, "Add a local stdio server"
  and "Environment variables" sections, fetched during this task):
  "Claude Code sets `CLAUDE_PROJECT_DIR` in the spawned server's
  environment... Read it from inside your server process... e.g.
  `os.environ["CLAUDE_PROJECT_DIR"]` in Python", and "All three [`
  CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PROJECT_DIR`] are
  exported as environment variables to hook processes and to MCP and LSP
  server subprocesses." So this is a real process-environment variable
  Claude Code injects at launch -- not something the generic, host-
  agnostic `mcp` Python SDK itself parses, expands, or has any notion of
  -- read directly via `os.environ.get(...)`, exactly the fallback path
  the Task 4 brief anticipated if the SDK didn't auto-expand it.
  Neither variable is set when this module is imported/run outside a
  real Claude Code session (e.g. `pytest`, manual local testing) -- see
  `_lessons_dir`/`_cache_dir` below for the documented fallback used in
  that case.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

import index
import scrub
import store
from schema import Lesson, parse_lesson

logger = logging.getLogger(__name__)

mcp = FastMCP("hindsight")


# --- Runtime path resolution ------------------------------------------------


def _lessons_dir() -> Path:
    """Resolve `.debug-memory/lessons/` under `${CLAUDE_PROJECT_DIR}`
    (see module docstring for how that env var gets into this process).

    Falls back to the current working directory when `CLAUDE_PROJECT_DIR`
    is unset, which only happens outside a real Claude Code session
    (standalone scripts, `pytest` without an explicit override). This is
    a documented fallback for that situation, not a guess at real
    runtime behavior -- Claude Code always sets the variable for a real
    MCP stdio server subprocess per the docs cited above. Tests in this
    repo don't rely on the fallback; they set `CLAUDE_PROJECT_DIR`
    explicitly via `monkeypatch.setenv` so each test is isolated to its
    own `tmp_path`. Creates the directory if it doesn't exist yet (a
    freshly cloned consuming repo has no `.debug-memory/` until the
    first lesson is saved).
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    base = Path(project_dir) if project_dir else Path.cwd()
    lessons_dir = base / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    return lessons_dir


def _cache_dir() -> Path:
    """Resolve the index cache directory from `${CLAUDE_PLUGIN_DATA}`
    (real deployments: `~/.claude/plugins/data/<plugin-id>/`, per the
    Claude Code docs), same runtime-resolution approach as
    `_lessons_dir` (see its docstring for the env-var-injection details).

    Falls back to a `.debug-memory/.index-cache` directory under the
    resolved project dir when `CLAUDE_PLUGIN_DATA` is unset (same
    standalone/test scenario as `_lessons_dir`'s fallback) so those runs
    still get a stable, writable cache location without a real plugin
    install. Tests override via `monkeypatch.setenv` rather than relying
    on this.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        cache_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        cache_dir = base / ".debug-memory" / ".index-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# --- capture marker resolution (Task 7 review fix) --------------------------

# `hooks/mark_error.py` / `hooks/capture.py` sanitize a session_id to this
# charset before using it in a marker filename (unsafe chars -> `_`).
# Duplicated here (a third copy) rather than imported, for the exact same
# reason those two hook scripts duplicate it between themselves rather
# than sharing a module: hooks are separate, dependency-free `python3`
# subprocesses (see `hooks/mark_error.py`'s module docstring), unrelated
# to this server process's own import graph -- there's no shared module
# either side could import from without inventing a new coupling for
# ~1 line of logic. Kept byte-for-byte identical to both hook scripts'
# copies so a given real `session_id` always resolves to the same marker
# path on the write side (`mark_error.py`), the read side (`capture.py`),
# and this delete side.
_SESSION_ID_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_session_id(session_id: str) -> str:
    """Replace every character outside `[A-Za-z0-9_-]` with `_`, exactly
    matching `hooks/mark_error.py`'s `_marker_path` sanitization (see
    that function and this module's own note above).
    """
    return _SESSION_ID_SAFE_CHARS_RE.sub("_", session_id)


def _resolve_marker_path(session_id: str, plugin_data_dir: Path) -> Path:
    """Validate `session_id` and resolve it to
    `plugin_data_dir/session-<sanitized session_id>.marker`.

    Mirrors `store.py`'s `_resolve_lesson_path` (see that function's
    docstring for the full path-containment reasoning this adapts),
    adjusted for this directory/filename pattern instead of
    `lessons_dir`/`<id>.md`:

      1. Name-only check, on the RAW `session_id` (before sanitizing):
         must be non-empty, must equal `Path(session_id).name`, and must
         not be `.` or `..`. This rejects a `session_id` shaped like
         `/etc/passwd` or `../../etc/evil` outright -- `ValueError`, the
         same way `prune_lesson`'s `id` validation rejects an analogous
         hostile `id` -- rather than silently sanitizing a path
         separator into something that happens to land somewhere
         unintended. A real Claude Code `session_id` is always a plain
         UUID-shaped string (same reasoning `_resolve_lesson_path`
         itself gives for why every internally-produced id already
         passes this check: a shape that fails it cannot arise from any
         normal internal flow, only a hand-crafted/adversarial value).
         Characters that aren't path separators (spaces, colons, other
         punctuation, non-ASCII, ...) pass this check fine -- they're
         exactly what step 2's sanitization exists to handle, and doing
         so here still produces the identical marker filename
         `hooks/mark_error.py` writes for that same "weird but not
         traversal-shaped" `session_id`.
      2. Resolved-parent check: after sanitizing and building the
         candidate path, its resolved parent must be exactly
         `plugin_data_dir.resolve()` -- real defense in depth (e.g. a
         symlink planted at the marker's path), not redundant with step
         1, matching `_resolve_lesson_path`'s own two-check structure.
    """
    if (
        not session_id
        or session_id in (".", "..")
        or session_id != Path(session_id).name
    ):
        raise ValueError(
            f"invalid session_id {session_id!r}: must be a bare filename "
            "component (no path separators, not absolute, not '.' or '..')"
        )

    plugin_data_dir = Path(plugin_data_dir)
    safe_id = _sanitize_session_id(session_id)
    candidate = plugin_data_dir / f"session-{safe_id}.marker"
    if candidate.resolve().parent != plugin_data_dir.resolve():
        raise ValueError(
            f"invalid session_id {session_id!r}: resolves outside the "
            "plugin data directory"
        )
    return candidate


# --- git add (best-effort, never blocks the tool call) ----------------------


def _maybe_git_add(file_path: Path, project_dir: Path) -> None:
    """Stage `file_path` with `git add` iff `project_dir` (the consuming
    repo's root -- i.e. the directory `.debug-memory/` lives directly
    under, NOT `lessons_dir` itself, which is two levels deeper) has a
    `.git` entry. `Path.exists()` covers both a normal repo (`.git` is a
    directory) and a worktree/submodule checkout (`.git` is a file).

    Per Global Constraints ("stage with git if a repo exists, never
    auto-commit") and the Task 4 brief ("never error the tool call
    because git is absent"): this function never raises. No `.git`, git
    missing from `PATH`, or any other failure from the `git add`
    invocation itself are all silently swallowed (logged at most) --
    staging a file for the user's next manual commit is a courtesy on
    top of a successful save, not a required part of one. This never
    runs `git commit` -- only `git add`.

    This repository itself has no `.git` (confirmed:
    `Path(__file__).resolve().parents[1] / ".git"` does not exist here),
    so calling this against this repo's own tree is a real, verified
    no-op, not just a theoretical one.
    """
    if not (project_dir / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "-C", str(project_dir), "add", "--", str(file_path)],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except Exception:
        logger.warning(
            "save_lesson: git add failed or git is unavailable; continuing "
            "without staging (this never fails the save itself)",
            exc_info=True,
        )


# --- tag auto-derivation -----------------------------------------------------
#
# Task 4 brief's tags decision: `save_lesson` intentionally has no `tags`
# parameter (matches the original spec's tool contract, which never listed
# one). `schema.Lesson.tags` still backs the mandatory "## Tags for
# retrieval" body section (and therefore `Lesson.match_text()`, which
# `index.py` embeds for search), so it's populated here from the other
# fields instead of a human-curated input.

_TAG_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_TAG_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "is",
        "was", "with", "at", "by", "from", "this", "that", "it", "as",
    }
)


def _derive_tags(domain: list[str], error_signature: str, title: str) -> list[str]:
    """Auto-derive `Lesson.tags` from `domain + error_signature + title`
    keywords: dedupe, lowercase, individual tokens (not one joined blob
    string -- `Lesson.tags` is a `list[str]`, one bullet per tag in the
    rendered body, and `Lesson.match_text()` already whitespace-joins
    them for embedding, so no extra joining belongs here).
    """
    seen: set[str] = set()
    tags: list[str] = []
    for source in (*domain, error_signature, title):
        for token in _TAG_TOKEN_RE.findall(source or ""):
            token = token.lower()
            if len(token) < 2 or token in _TAG_STOPWORDS or token in seen:
                continue
            seen.add(token)
            tags.append(token)
    return tags


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- MCP tools ---------------------------------------------------------------


@mcp.tool()
def search_lessons(query: str, k: int = 3) -> list[dict[str, Any]]:
    """Search saved debugging lessons for ones relevant to `query`.

    Embeds `query` against the local similarity index (`index.py`, cache
    at `${CLAUDE_PLUGIN_DATA}`) and expands each hit that clears the
    similarity threshold back into the full lesson content, per Global
    Constraints' output shape: `{id, title, score, failed_approaches,
    root_cause, fix, path}`. Returns `[]` if nothing clears the
    threshold -- never a weak match dressed as strong (that guarantee
    lives in `index.search` itself; this function doesn't loosen it).

    On-demand index build (post-Task-4-review fix): if `index.json`
    doesn't exist yet in `${CLAUDE_PLUGIN_DATA}` -- e.g. a repo freshly
    cloned/pulled from a teammate who already committed lessons under
    `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`, searched on this
    machine before this machine's own `save_lesson` ever ran -- this
    builds the index once from whatever lesson files already exist
    before searching, rather than silently returning `[]` (which would
    be indistinguishable from "no relevant lessons exist"). `index.
    build_index` is idempotent and purely derived from the markdown
    files, so this is safe and cheap. Only triggered when the cache file
    is genuinely *missing*; an existing-but-stale index is left alone
    here (out of scope for this fix) -- that's what the save-triggered
    rebuild in `save_lesson` and a future manual reindex command (Task
    8) are for. Any lesson file skipped by this on-demand build (parse
    failure) is logged, not raised: `search_lessons` returns a
    `list[dict]`, not a single dict, so there's no natural top-level
    slot to attach a `warnings` field the way `save_lesson` does (see
    that function's own `warnings` handling) -- logging keeps this path
    from silently swallowing the problem without changing this
    function's return shape.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    index_path = cache_dir / index.INDEX_FILENAME
    if not index_path.exists():
        built_path = index.build_index(lessons_dir, cache_dir)
        skipped = json.loads(built_path.read_text(encoding="utf-8")).get("skipped", [])
        for entry in skipped:
            logger.warning(
                "search_lessons: on-demand index build skipped a lesson "
                "file and excluded it from search: %s: %s",
                entry["path"],
                entry["error"],
            )

    hits = index.search(query, cache_dir, k=k)

    results: list[dict[str, Any]] = []
    for hit in hits:
        lesson_path = Path(hit["path"])
        try:
            lesson = parse_lesson(lesson_path.read_text(encoding="utf-8"))
        except Exception as exc:
            # The index references a file that went missing or became
            # malformed since the index was last built (manual edit/
            # delete outside this server, or a stale cache). Skip it
            # rather than fail the whole search -- the same per-file
            # error isolation index.build_index itself documents and
            # uses (broad `Exception`, not just ValueError/OSError:
            # malformed YAML raises yaml.YAMLError, a different
            # hierarchy than parse_lesson's own ValueError).
            logger.warning(
                "search_lessons: skipping stale/unreadable index entry %s: %s: %s",
                lesson_path,
                type(exc).__name__,
                exc,
            )
            continue
        results.append(
            {
                "id": hit["id"],
                "title": lesson.title,
                "score": hit["score"],
                "failed_approaches": lesson.failed_approaches,
                "root_cause": lesson.root_cause,
                "fix": lesson.fix,
                "path": hit["path"],
            }
        )
    return results


@mcp.tool()
def save_lesson(
    title: str,
    domain: list[str],
    error_signature: str,
    symptom: str,
    failed_approaches: list[str],
    root_cause: str,
    fix: str,
    confidence: Literal["confirmed", "probable"] = "probable",
) -> dict[str, Any]:
    """Save a debugging lesson learned during this session.

    Pipeline: scrub every free-text field (`scrub.py`) -> build a
    `Lesson` (`schema.py`; auto-derives `id` and retrieval `tags` -- see
    `_derive_tags`, no `tags` parameter on this tool by design, see that
    function's docstring) -> write it to
    `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/<id>.md` (`store.py`) ->
    rebuild the local similarity index (`index.py`) -> best-effort
    `git add` the new file (`_maybe_git_add`) -> return `{id, path,
    wrote: true}`.

    If the index rebuild's most recent run skipped any lesson file
    because it failed to parse (`index.json`'s `skipped` list --
    `index.py`, added after the Task 3 review so one corrupt file can't
    silently take down search over every other lesson), that is
    surfaced here as a `warnings` field on this call's own return value
    rather than swallowed: a systemic `parse_lesson` bug would otherwise
    look like a clean, successful save while quietly excluding every
    lesson (including past ones, not just this one) from search.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    scrubbed = scrub.scrub_payload(
        {
            "title": title,
            "domain": domain,
            "error_signature": error_signature,
            "symptom": symptom,
            "failed_approaches": failed_approaches,
            "root_cause": root_cause,
            "fix": fix,
        }
    )

    created_at = _utc_now_iso()
    lesson = Lesson(
        id=store.make_lesson_id(scrubbed["title"], created_at),
        title=scrubbed["title"],
        domain=scrubbed["domain"],
        error_signature=scrubbed["error_signature"],
        created_at=created_at,
        confidence=confidence,
        symptom=scrubbed["symptom"],
        failed_approaches=scrubbed["failed_approaches"],
        root_cause=scrubbed["root_cause"],
        fix=scrubbed["fix"],
        tags=_derive_tags(scrubbed["domain"], scrubbed["error_signature"], scrubbed["title"]),
    )

    path = store.write_lesson(lesson, lessons_dir)
    saved_id = path.stem  # store.write_lesson may have adjusted the id on a collision

    index_path = index.build_index(lessons_dir, cache_dir)
    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    skipped = index_data.get("skipped", [])

    _maybe_git_add(path, lessons_dir.parent.parent)

    result: dict[str, Any] = {"id": saved_id, "path": str(path), "wrote": True}
    if skipped:
        result["warnings"] = [
            f"lesson file failed to index and was excluded from search: "
            f"{entry['path']}: {entry['error']}"
            for entry in skipped
        ]
    return result


@mcp.tool()
def list_lessons() -> list[dict[str, Any]]:
    """List all saved debugging lessons."""
    return store.list_lessons(_lessons_dir())


@mcp.tool()
def prune_lesson(id: str) -> dict[str, Any]:
    """Delete a saved debugging lesson by id (Task 5).

    Deletes `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/<id>.md`
    (`store.delete_lesson`) and, if a file was actually removed, rebuilds
    the local similarity index (`index.build_index` -- same call pattern
    `save_lesson` already uses) so the pruned lesson stops being
    returned by `search_lessons` immediately, not just on the next
    unrelated rebuild.

    Returns `{"deleted": true}` if a file was removed, `{"deleted":
    false}` if no file matched `id` -- pruning an id that's already gone
    (or was never saved) is a normal outcome, not an error. The index
    rebuild is skipped in that case: nothing on disk changed, so the
    existing index (or lack of one) is already consistent with reality.
    A stale index entry left behind by some *other* means (e.g. a lesson
    file deleted by hand outside this tool) still degrades gracefully --
    `search_lessons` already skips index entries whose file has gone
    missing (see its own docstring) -- so this isn't a correctness gap,
    just an avoided no-op rebuild.

    Path-traversal note (post-Task-5-review fix): `id` is caller-
    supplied and, before this fix, was concatenated straight into a
    filesystem path with no validation -- `id="/etc/passwd"` or
    `id="../../../../some/file"` could delete an arbitrary `.md`-
    suffixed file anywhere this process can write, not just a saved
    lesson. `store.delete_lesson` now rejects any `id` that isn't a bare
    filename component by raising `ValueError`, which is intentionally
    *not* caught here -- FastMCP's tool dispatch turns an uncaught
    exception into an `isError: true` tool result for the caller, which
    is the right outcome for what is, in practice, only ever a hand-
    crafted malicious/malformed `id` (every id this server itself
    generates, via `store.make_lesson_id`, is already a safe bare
    filename -- see `store.delete_lesson`'s own docstring for the full
    reasoning). Letting it surface as a clear tool error beats
    collapsing it into `{"deleted": false}`, which would look identical
    to the ordinary "no such lesson" case.
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    deleted = store.delete_lesson(id, lessons_dir)
    if deleted:
        index.build_index(lessons_dir, cache_dir)

    return {"deleted": deleted}


@mcp.tool()
def clear_capture_marker(session_id: str) -> dict[str, Any]:
    """Delete the per-session capture marker `hooks/mark_error.py` wrote
    at `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (Task 7 review
    fix), if it exists.

    Called by `agents/lesson-distiller.md` after a successful
    `save_lesson`, so a later `Stop` event in the same session doesn't
    re-emit `hooks/capture.py`'s capture nudge for an incident that's
    already been saved. Moved here from a `Bash`-tool `rm -f` in the
    distiller agent itself because `${CLAUDE_PLUGIN_DATA}` is not
    reliably present in a `Bash`-tool subprocess's environment (see this
    module's own docstring for the full story); this server process
    reads it successfully today via `_cache_dir`, which resolves to the
    exact same directory `hooks/mark_error.py` writes the marker into
    (both read the same `CLAUDE_PLUGIN_DATA` env var with no
    subdirectory appended -- confirmed by reading both implementations
    side by side before writing this tool).

    Returns `{"cleared": True}` if a marker file was found and deleted,
    `{"cleared": False}` if no marker existed for this `session_id` --
    mirrors `prune_lesson`'s "not found is not an error" pattern above:
    a session that never hit a tool failure (so `mark_error.py` never
    ran) has no marker to clear, which is a normal, expected outcome,
    not a failure of this tool.

    Raises `ValueError` on a `session_id` shaped like a path-traversal
    attempt (see `_resolve_marker_path`) -- deliberately uncaught, same
    as `prune_lesson`'s `id` validation above: FastMCP turns this into
    an `isError: true` tool result, which is the right outcome for what
    is, in practice, only ever a hand-crafted/malicious `session_id`.
    """
    plugin_data_dir = _cache_dir()
    marker_path = _resolve_marker_path(session_id, plugin_data_dir)

    if not marker_path.exists():
        return {"cleared": False}
    marker_path.unlink()
    return {"cleared": True}


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## agents/lesson-distiller.md
```
---
name: lesson-distiller
description: >
  Structures a resolved debugging incident into a saved hindsight lesson
  and clears the session's capture marker. Dispatch with subagent_type:
  lesson-distiller only after the Stop hook's capture nudge has fired
  AND the error that caused the earlier tool failure has actually been
  resolved this session -- not worth dispatching otherwise. The dispatch
  prompt must include: a concise incident summary (error signature,
  symptom, approaches that were actually tried and failed, root cause,
  fix, and whether the fix was verified to actually work) and the
  session's session_id (the same session_id the Stop hook payload
  carried).
tools: Read, mcp__hindsight__save_lesson, mcp__hindsight__clear_capture_marker
model: inherit
---

You are the hindsight lesson-distiller. You are dispatched once, after a
tool failure earlier in a session has been resolved, with a concise
incident summary and a `session_id` in your prompt. Your job: turn that
summary into one saved lesson via the `hindsight` MCP server's
`save_lesson` tool, then clear the session's capture marker so the next
`Stop` in this session doesn't re-nudge for the same incident. Nothing
else. You do not investigate the codebase, you do not re-run the failing
command, and you do not fix anything -- by the time you're dispatched,
the fix already happened; you're only recording it.

## 1. Decide whether there's anything to save

If the incident summary you were given doesn't actually describe a
*resolved* error (the failure is described as still happening, or the
summary is too vague to tell), do not call `save_lesson`. Say so plainly
in your final response instead -- explain what's missing or unclear --
and stop. A half-true lesson saved to the shared store is worse than no
lesson: someone else will trust it later.

## 2. Structure the incident into `save_lesson`'s exact input shape

`save_lesson` takes these fields (same contract the `/hindsight save`
skill uses for the manual path -- see `skills/hindsight/SKILL.md` if you
want the fuller field-by-field description):

- `title` (str, required) -- short human-readable summary.
- `domain` (list[str], required) -- e.g. `["react", "javascript"]`.
- `error_signature` (str, required) -- the distinguishing error
  message/code.
- `symptom` (str, required) -- what was observed, in prose.
- `failed_approaches` (list[str], required) -- things that were tried
  and did NOT fix it. May be `[]` if the summary says nothing was tried
  first, or doesn't mention any -- see the fabrication rule below.
- `root_cause` (str, required) -- the actual underlying cause.
- `fix` (str, required) -- what actually fixed it.
- `confidence` (`"confirmed"` or `"probable"`, defaults to
  `"probable"`) -- use `"confirmed"` ONLY if the incident summary says
  the fix was actually verified working (tests passed, the error
  stopped recurring, etc.). If verification isn't mentioned or is
  ambiguous, leave it as `"probable"`. When in doubt, `"probable"`.

Derive every field's *content* only from what the incident summary
actually says. Don't pad a thin summary with plausible-sounding detail
to make the lesson feel more complete.

### Never fabricate

Never invent a `failed_approaches` entry that the summary doesn't
actually describe as having been tried. An empty list is a correct,
honest answer when nothing was tried first (or the summary doesn't say)
-- it is never a reason to make something up. The same rule applies to
every other field: if the summary doesn't give you enough to respon-
sibly fill a required field, say so in your final response (per step 1)
rather than guessing.

### Never include secrets, tokens, or customer data

The `hindsight` MCP server's `save_lesson` runs everything through a
server-side scrubber (`server/scrub.py`) before writing to disk, but
that is a safety net, not your first line of defense. Before calling
`save_lesson`, look over every field you're about to send for anything
that looks like a secret, API key, access token, password, connection
string with embedded credentials, or customer-identifying data (real
names, emails, account IDs, etc. that belong to an end user rather than
to the codebase itself). Redact or omit it -- replace with something
like `<redacted>` or drop the surrounding detail -- rather than passing
it through. You're dispatched unattended, so there's no one to ask
first; when in doubt, leave it out rather than include it.

## 3. Call `save_lesson`

Call `mcp__hindsight__save_lesson` with the fields you built. On
success it returns `{id, path, wrote: true, warnings?}`. If it returns a
`warnings` field, that means some *other* previously-saved lesson failed
to index and is currently unsearchable -- mention it in your final
response; it's unrelated to whether *this* save succeeded but is worth
surfacing.

If the call fails (tool error), report the failure plainly in your final
response and stop -- do not attempt the marker deletion below, since
nothing was actually captured.

## 4. Clear the session's capture marker

Only after a successful `save_lesson` call: call
`mcp__hindsight__clear_capture_marker` with the `session_id` you were
given in your dispatch prompt. This is what stops a later `Stop` in the
same session from re-emitting the capture nudge for an incident that's
now already saved.

(Earlier versions of this agent deleted the marker themselves via the
`Bash` tool. That didn't reliably work: `${CLAUDE_PLUGIN_DATA}` is only
exported to hook processes and MCP/LSP server subprocesses, not to a
`Bash`-tool invocation made during a normal agent turn, so the variable
expanded to empty and the `rm -f` silently no-op'd. `clear_capture_marker`
runs inside the `hindsight` MCP server instead, which does reliably see
`${CLAUDE_PLUGIN_DATA}` -- so this tool call, not a shell command, is now
the only way this agent clears the marker.)

The tool returns `{"cleared": true}` if a marker existed and was
deleted, `{"cleared": false}` if none existed for this `session_id` --
neither is an error. If the call itself fails (tool error), don't treat
that as a hard failure of your overall task -- the lesson is already
saved by this point, which is the part that matters. Just note in your
final response that marker cleanup didn't happen, so whoever's watching
knows a `Stop` event later in this same session may nudge about this
incident again even though it's already captured (harmless redundancy,
not a correctness problem -- the same marker is what lets an
*unresolved* session's later `Stop` still trigger capture once it IS
resolved, so this hook family is intentionally biased toward a spurious
extra nudge over a silently dropped one).

## 5. Final response

Report plainly: whether a lesson was saved (and its `id`/`path` if so),
whether the marker was cleared, and anything you declined to do and why
(step 1's resolved-error check, step 2's fabrication guard, or a
`save_lesson` failure). Keep it short -- this is a background capture
step, not a report the user needs to read closely.
```

## hooks/capture.py
```
#!/usr/bin/env python3
"""hindsight `Stop` hook: nudge to capture a resolved-error lesson (Task 7).

Registered in `hooks/hooks.json` against `Stop` (fires once at the end
of a turn in which Claude stops responding). Claude Code spawns this
script once per `Stop` event with that event's JSON payload on stdin.

Payload shape / `session_id` field (per the Task 7 brief's instruction
to verify rather than assume): fetched
`https://code.claude.com/docs/en/hooks.md` directly during this task.
Its "Common input fields" section documents `session_id` ("Current
session identifier") as one of the fields every hook event receives,
`Stop` included -- not something guessed by analogy with
`PostToolUseFailure` alone. The same section separately notes that
`Stop` (and `SubagentStop`) additionally carry a `last_assistant_message`
field that other events don't; this hook doesn't use that field or any
other beyond `session_id`.

Job: check whether *this session* ever hit a tool failure that
`hooks/mark_error.py` (the `PostToolUseFailure` hook, also Task 7)
marked by touching `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`.

  - No marker for this `session_id` (including when `session_id` is
    itself missing or unparseable from a malformed payload): exit 0,
    print nothing. A session that never hit a tool failure -- the common
    case, true for every `Stop` in a clean session -- must produce zero
    stdout; this is the "no-op" behavior `hooks/tests/
    test_mark_and_capture.py` checks for.
  - Marker exists: print the fixed `hookSpecificOutput` nudge below and
    exit 0.

This hook never deletes the marker file. Deletion only happens after a
real save, from `agents/lesson-distiller.md` calling the `hindsight` MCP
server's `clear_capture_marker` tool (`server/main.py`; see that file
and `agents/lesson-distiller.md` for the full reasoning -- an earlier
version deleted the marker via the `Bash` tool directly, which turned
out not to reliably see `${CLAUDE_PLUGIN_DATA}` in that subprocess's
environment) -- so an unresolved session's *next* `Stop` (if the
session continues) can still trigger this same nudge once the error IS
actually resolved. Deleting here, on the mere act of nudging, would
break that: the nudge would fire at most once per session regardless of
whether anything was ever actually captured.

The nudge text below is phrased factually/descriptively, not
imperatively, matching `retrieve.py`'s own phrasing rationale (see that
file's docstring for the full argument): an imperative "dispatch the
agent... exclude secrets..." risks tripping Claude's own
prompt-injection defenses on its *own* hook output, which would surface
this raw text to the user instead of Claude acting on it. This exact
string is taken verbatim from the Task 7 brief (itself already corrected
to factual phrasing after Task 6's review, per that brief's own note) --
it is not paraphrased or reworded here.

Env var resolution / sanitization: an intentional byte-for-byte
duplicate of `hooks/mark_error.py`'s `_plugin_data_dir`/`_marker_path`
(see that file's module docstring for the full reasoning on why this is
duplicated -- both from `server/`, and between these two hook scripts,
rather than shared via a new intra-`hooks/` helper module). Kept
identical to `mark_error.py`'s copy so a given real `session_id` always
resolves to the same marker path on both the write side (`mark_error.py`)
and this read side.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Verbatim from the Task 7 brief -- do not reword. If this ever needs to
# change, it must be a deliberate, reviewed edit, not incidental drift;
# hooks/tests/test_mark_and_capture.py asserts this exact string.
ADDITIONAL_CONTEXT = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from a concise summary — error signature, "
    "symptom, failed approaches, root cause, fix, with secrets/tokens/"
    "customer data excluded. Not worth dispatching if the error wasn't "
    "actually resolved this session."
)


def _plugin_data_dir() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / ".plugin-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _marker_path(session_id: str) -> Path:
    safe_id = _SAFE_CHARS_RE.sub("_", session_id)
    return _plugin_data_dir() / f"session-{safe_id}.marker"


def main() -> int:
    # Same stdin-resilience pattern as retrieve.py/mark_error.py: raw
    # bytes decoded with errors="replace" so genuinely non-UTF-8 stdin
    # can't raise before this script even tries to parse JSON.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id.strip():
        # No usable session_id -- can't know which marker to check, so
        # this degrades to the same "nothing to capture" no-op as a
        # genuinely marker-less session, rather than raising.
        return 0

    try:
        marker_exists = _marker_path(session_id).exists()
    except Exception:
        # Filesystem trouble reading CLAUDE_PLUGIN_DATA -> treat as
        # no-op rather than crash; there is nothing safe to report if
        # this hook can't even check whether a marker exists.
        marker_exists = False

    if not marker_exists:
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": ADDITIONAL_CONTEXT,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## hooks/mark_error.py
```
#!/usr/bin/env python3
"""hindsight `PostToolUseFailure` hook: per-session error marker (Task 7).

Registered in `hooks/hooks.json` as a *second* command alongside
`retrieve.py`, under the same `PostToolUseFailure` matcher group (see
that file's own module docstring for the confirmed payload shape --
unchanged by this script, so there's no need to re-fetch or re-confirm
it here). Claude Code spawns this script once per genuine tool failure,
alongside (not instead of) `retrieve.py`. Per the live hooks docs
("Hook execution" -- fetched during this task): "All matching hooks run
in parallel," and when several hooks emit `additionalContext` for the
same event, Claude receives all of them concatenated. This script
deliberately emits *no* `hookSpecificOutput` at all (see `main` below),
so it can never add to, conflict with, or otherwise change what
`retrieve.py`'s Task-6-approved nudge already puts in front of Claude --
this file is purely additive housekeeping, not a second nudge.

Job: touch an empty marker file at
`${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` so `hooks/capture.py`
(the `Stop` hook, also Task 7) can tell, at session end, whether *this*
session ever hit a tool failure worth possibly turning into a lesson.
Content doesn't matter, only existence, per the brief -- the file is
created empty (`Path.touch`).

Never blocks or fails the tool-failure event over this: any problem
reading stdin, parsing the payload, a missing/malformed `session_id`, or
a filesystem error while creating the marker's parent directory or the
file itself is swallowed, and this exits 0 either way. The brief calls
out explicitly that a missing `${CLAUDE_PLUGIN_DATA}` directory (e.g. a
freshly installed plugin, first failure of the session) "must not fail
or block" this hook -- `_plugin_data_dir` below creates it
(`mkdir(parents=True, exist_ok=True)`) rather than assuming it exists.

Env var resolution (`${CLAUDE_PLUGIN_DATA}`, marker file location):
duplicates the tiny amount of logic `server/main.py`'s `_cache_dir()`
uses (`os.environ.get("CLAUDE_PLUGIN_DATA")`, then
`.mkdir(parents=True, exist_ok=True)`; see that function's own
docstring for the full env-var-injection story) rather than importing
from `server/` -- hooks are separate Python processes from the MCP
server (different concern, different process lifecycle; importing
across that boundary for ~10 lines of logic would just be a coupling
liability for no real benefit). This is also intentionally NOT factored
into a new shared helper module under `hooks/` and imported by both this
file and `hooks/capture.py`: every hook script in this plugin is a
fully standalone, dependency-free `python3` script (the precedent Task
6's `retrieve.py` set, verified by its own `test_no_non_stdlib_imports`
test), so this duplicates the same ~10-line helper a second time
(byte-for-byte identical to `capture.py`'s copy) rather than introducing
an intra-`hooks/` import dependency between two scripts that are
otherwise independently invoked, independently timed-out, and
independently tested.

The fallback used when `CLAUDE_PLUGIN_DATA` is unset (standalone/test
use, same rationale as `_cache_dir()`'s own documented fallback) is
`${CLAUDE_PROJECT_DIR or cwd}/.debug-memory/.plugin-data` -- a different
leaf directory name than `_cache_dir()`'s own `.index-cache` fallback,
since marker files aren't the search index cache. In a real plugin
install both marker files and the index cache land under the very same
real `${CLAUDE_PLUGIN_DATA}` directory regardless, per the brief's
literal path `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (no
subdirectory). Tests in this repo don't rely on the fallback; they set
`CLAUDE_PLUGIN_DATA` explicitly per-subprocess so each test is isolated
to its own tmp directory.

`session_id` is sanitized to a safe filename component
(`[A-Za-z0-9_-]` only; anything else is replaced with `_`) before being
used in a path -- defense in depth against a malformed/hostile payload
turning a filesystem-path-shaped field into a path-traversal write (same
precedent as `server/main.py`'s `prune_lesson` id validation, though
here it degrades to a differently-named marker file rather than raising,
since silently degrading beats crashing a step that must never block the
tool-failure event). `hooks/capture.py` applies the *identical*
sanitization so a given real `session_id` always maps to the same marker
path on both the write side (here) and its read side.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _plugin_data_dir() -> Path:
    """Resolve `${CLAUDE_PLUGIN_DATA}` (see module docstring), creating
    it if it doesn't exist yet.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data)
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / ".plugin-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _marker_path(session_id: str) -> Path:
    safe_id = _SAFE_CHARS_RE.sub("_", session_id)
    return _plugin_data_dir() / f"session-{safe_id}.marker"


def main() -> int:
    # Same stdin-resilience pattern as retrieve.py: raw bytes decoded
    # with errors="replace" so genuinely non-UTF-8 stdin can't raise
    # before this script even gets a chance to try parsing JSON.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not isinstance(session_id, str) or not session_id.strip():
        # No usable session_id -- nothing to mark, but this must not be
        # treated as an error (a garbled/unexpected payload shape is not
        # this hook's problem to raise about).
        return 0

    try:
        _marker_path(session_id).touch(exist_ok=True)
    except Exception:
        # Marker-writing is best-effort housekeeping; a filesystem
        # problem here must never fail the PostToolUseFailure event.
        pass

    # Deliberately no stdout output at all -- see module docstring.
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## server/tests/test_main.py
```
"""Integration tests for server/main.py: the real search_lessons /
save_lesson / list_lessons MCP tool implementations, wired to schema.py +
scrub.py + index.py + store.py (Task 4).

Calls the tool functions directly (`main.save_lesson(...)`,
`main.search_lessons(...)`, `main.list_lessons()`), not through the MCP
stdio transport. This is safe: `FastMCP.tool()`'s decorator (confirmed by
reading `mcp.server.fastmcp.FastMCP.tool`'s source before relying on
this) registers the function as a side effect and then `return fn`s the
*original*, unwrapped function -- so `main.save_lesson` etc. remain
ordinary, directly-callable Python functions after decoration, exactly
like `server/tests/test_index.py` calls straight into `index.py`'s
functions without spinning up any transport.

Every test uses the `isolated_project` fixture, which monkeypatches
`CLAUDE_PROJECT_DIR` / `CLAUDE_PLUGIN_DATA` to a fresh `tmp_path` --
tests never touch this repo's own filesystem, never depend on run order,
and (since no test creates a `.git` under its tmp_path project dir,
mirroring this actual repo having none) exercise `save_lesson`'s
best-effort git-add as a real, verified no-op throughout -- see
`test_git_add_is_a_safe_no_op_when_no_git_repo_exists` for the explicit
check.

Uses the real fastembed model (no mocking), consistent with
server/tests/test_index.py's own approach.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import main

FAKE_AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# `hooks/mark_error.py` -- the real script that writes the marker file
# `clear_capture_marker` deletes -- lives outside `server/`. Invoked as a
# real subprocess (not imported) in
# `test_clear_capture_marker_matches_mark_error_pys_sanitization` below,
# the same way `hooks/tests/test_mark_and_capture.py` itself invokes it,
# so that test confirms the two independent sanitization copies
# (`hooks/mark_error.py`'s and `main._sanitize_session_id`'s) actually
# agree on a real marker filename rather than just asserting two
# hand-copied regexes match each other.
MARK_ERROR_PY = Path(__file__).resolve().parents[2] / "hooks" / "mark_error.py"


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_dir = tmp_path / "consuming-repo"
    project_dir.mkdir()
    cache_dir = tmp_path / "plugin-data"
    cache_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(cache_dir))
    return project_dir, cache_dir


def _payload(**overrides) -> dict:
    payload = dict(
        title="React useEffect infinite render loop",
        domain=["react", "javascript"],
        error_signature="Warning: Maximum update depth exceeded",
        symptom="Component re-renders in an infinite loop right after mount.",
        failed_approaches=["Removing the dependency array entirely"],
        root_cause="useEffect's state setter was called unconditionally on every render.",
        fix="Added a guard condition before calling the state setter.",
        confidence="confirmed",
    )
    payload.update(overrides)
    return payload


# --- save_lesson: scrubbing + shape -----------------------------------------


def test_save_lesson_writes_a_scrubbed_md_file_and_returns_expected_shape(
    isolated_project,
):
    project_dir, _ = isolated_project
    payload = _payload(
        symptom=f"Leaked key found in CI logs: AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}",
    )

    result = main.save_lesson(**payload)

    assert result["wrote"] is True
    assert result["id"]
    assert result["path"]
    assert "warnings" not in result

    written_path = Path(result["path"])
    assert written_path.exists()
    assert written_path.parent == project_dir / ".debug-memory" / "lessons"

    contents = written_path.read_text(encoding="utf-8")
    assert FAKE_AWS_ACCESS_KEY not in contents
    assert "[REDACTED]" in contents


def test_save_lesson_derives_tags_from_domain_error_and_title(isolated_project):
    result = main.save_lesson(
        **_payload(
            title="Kubernetes pod crashloop",
            domain=["kubernetes", "infra"],
            error_signature="CrashLoopBackOff",
        )
    )

    contents = Path(result["path"]).read_text(encoding="utf-8").lower()
    assert "## tags for retrieval" in contents
    for expected_tag in ("kubernetes", "infra", "crashloopbackoff"):
        assert expected_tag in contents


# --- Required brief integration test: save x3 (one with a leaked AWS key), --
# --- then search_lessons finds the matching one, and the leaked key never --
# --- appears in any written .md file. ---------------------------------------


def test_save_lesson_three_times_then_search_finds_the_right_one_and_secret_never_written(
    isolated_project,
):
    project_dir, _ = isolated_project

    main.save_lesson(
        **_payload(
            title="React useEffect infinite render loop",
            domain=["react", "javascript"],
            error_signature="Warning: Maximum update depth exceeded",
            symptom="Component re-renders in an infinite loop right after mount.",
            failed_approaches=["Removing the dependency array entirely"],
            root_cause="useEffect's state setter was called unconditionally on every render.",
            fix="Added a guard condition before calling the state setter.",
        )
    )
    main.save_lesson(
        **_payload(
            title="Docker build killed with out of memory error",
            domain=["docker", "ci"],
            error_signature="Killed (exit code 137)",
            symptom=(
                "Build container dies mid-build. Leaked credential in build "
                f"log: AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}"
            ),
            failed_approaches=["Increasing the build timeout"],
            root_cause="The build step's memory usage exceeded the container's cgroup limit.",
            fix="Raised the Docker daemon's memory limit and reduced parallel build jobs.",
        )
    )
    main.save_lesson(
        **_payload(
            title="Postgres connection pool exhausted",
            domain=["postgres", "database"],
            error_signature="FATAL: remaining connection slots are reserved",
            symptom="API requests start timing out under moderate load.",
            failed_approaches=["Restarting the app servers"],
            root_cause="Each worker process opened its own unpooled database connection.",
            fix="Introduced pgbouncer as a shared connection pooler.",
        )
    )

    results = main.search_lessons(
        "useEffect causing an infinite re-render loop in a React component", k=3
    )

    assert results, "expected at least one match"
    assert results[0]["title"] == "React useEffect infinite render loop"
    for key in ("id", "title", "score", "failed_approaches", "root_cause", "fix", "path"):
        assert key in results[0]
    assert results[0]["failed_approaches"] == ["Removing the dependency array entirely"]

    # The fake AWS key from lesson #2's symptom must never survive to disk,
    # in ANY saved lesson file (read every file back and grep for it).
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    md_files = list(lessons_dir.glob("*.md"))
    assert len(md_files) == 3
    for md_file in md_files:
        assert FAKE_AWS_ACCESS_KEY not in md_file.read_text(encoding="utf-8")


# --- search_lessons ----------------------------------------------------------


def test_search_lessons_returns_empty_list_when_nothing_saved(isolated_project):
    assert main.search_lessons("anything at all") == []


def test_search_lessons_builds_index_on_demand_when_cache_is_missing(
    isolated_project,
):
    """Regression test for the Task 4 review finding: search_lessons must
    not silently return [] on a fresh clone/pull where lesson .md files
    already exist on disk (as if committed by a teammate and shared via
    git -- .debug-memory/lessons/ is git-committed) but this machine has
    no local index.json cache yet (cache_dir under CLAUDE_PLUGIN_DATA is
    machine-local and never git-committed). A silent [] here would be
    indistinguishable from "no relevant lessons exist."

    Writes a known fixture lesson .md file directly into lessons_dir --
    bypassing save_lesson entirely -- so this actually exercises "these
    were already committed by a teammate," not just "save_lesson
    happened to build the index as a side effect already" (which a test
    that called save_lesson first would not catch).
    """
    project_dir, cache_dir = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    fixture = FIXTURES_DIR / "2026-06-02-react-useeffect-infinite-loop.md"
    (lessons_dir / fixture.name).write_text(
        fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Precondition: genuinely the "fresh clone" state -- a lesson file is
    # already on disk, but no index cache exists yet.
    assert not (cache_dir / "index.json").exists()

    results = main.search_lessons(
        "useEffect causing an infinite re-render loop in a React component"
    )

    assert results, (
        "expected the pre-existing (not save_lesson-created) lesson to be "
        "found via an on-demand index build"
    )
    assert results[0]["id"] == "2026-06-02-react-useeffect-infinite-loop"
    assert (
        results[0]["title"]
        == "React useEffect infinite loop from missing dependency array"
    )
    for key in ("id", "title", "score", "failed_approaches", "root_cause", "fix", "path"):
        assert key in results[0]

    # The on-demand build must have actually written a usable cache (not
    # just returned a result some other way).
    assert (cache_dir / "index.json").exists()


# --- list_lessons -------------------------------------------------------------


def test_list_lessons_returns_all_saved_lessons(isolated_project):
    main.save_lesson(**_payload(title="Lesson A"))
    main.save_lesson(
        **_payload(title="Lesson B", error_signature="A totally different error")
    )

    listing = main.list_lessons()

    assert len(listing) == 2
    assert {entry["title"] for entry in listing} == {"Lesson A", "Lesson B"}


def test_list_lessons_on_fresh_project_returns_empty_list(isolated_project):
    assert main.list_lessons() == []


# --- git add: safe no-op when absent, attempted when present ----------------


def test_git_add_is_a_safe_no_op_when_no_git_repo_exists(isolated_project):
    project_dir, _ = isolated_project
    assert not (project_dir / ".git").exists()

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True  # never errors just because git/.git is absent


def test_git_add_is_attempted_when_git_repo_exists(
    isolated_project, monkeypatch: pytest.MonkeyPatch
):
    project_dir, _ = isolated_project
    (project_dir / ".git").mkdir()  # simulate a git repo -- no real git invoked below

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True
    assert len(calls) == 1
    assert calls[0][:4] == ["git", "-C", str(project_dir), "add"]
    assert result["path"] in calls[0]


def test_git_add_failure_never_fails_the_save(
    isolated_project, monkeypatch: pytest.MonkeyPatch
):
    project_dir, _ = isolated_project
    (project_dir / ".git").mkdir()

    def raising_run(cmd, **kwargs):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(main.subprocess, "run", raising_run)

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True


# --- skipped-lessons surfacing (Task 3 review note) --------------------------


def test_save_lesson_surfaces_warnings_when_index_build_skips_a_file(isolated_project):
    project_dir, _ = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    # A pre-existing malformed lesson file that will fail to parse when
    # save_lesson rebuilds the index as part of this call.
    (lessons_dir / "2020-01-01-malformed.md").write_text(
        '---\nid: "unterminated\ntitle: "oops"\n---\n\n## Symptom\n\nx\n',
        encoding="utf-8",
    )

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True
    assert "warnings" in result
    assert len(result["warnings"]) == 1
    assert "2020-01-01-malformed.md" in result["warnings"][0]


def test_save_lesson_has_no_warnings_key_when_nothing_skipped(isolated_project):
    result = main.save_lesson(**_payload())
    assert "warnings" not in result


# --- prune_lesson (Task 5) ----------------------------------------------------


def test_prune_lesson_deletes_file_and_removes_it_from_search(isolated_project):
    project_dir, _ = isolated_project
    saved = main.save_lesson(**_payload())
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lesson_path = lessons_dir / f"{saved['id']}.md"
    assert lesson_path.exists()

    query = "useEffect causing an infinite re-render loop in a React component"

    # Sanity check: the lesson is actually searchable before pruning, so
    # the post-prune assertion below is a real regression check and not
    # trivially true because the query never matched anything.
    pre_results = main.search_lessons(query)
    assert any(hit["id"] == saved["id"] for hit in pre_results)

    result = main.prune_lesson(saved["id"])

    assert result == {"deleted": True}
    assert not lesson_path.exists()

    post_results = main.search_lessons(query)
    assert all(hit["id"] != saved["id"] for hit in post_results)


def test_prune_lesson_returns_false_for_nonexistent_id_and_does_not_error(
    isolated_project,
):
    result = main.prune_lesson("2020-01-01-never-saved")
    assert result == {"deleted": False}


def test_prune_lesson_leaves_other_saved_lessons_searchable(isolated_project):
    keep = main.save_lesson(**_payload(title="Lesson to keep"))
    remove = main.save_lesson(
        **_payload(
            title="Lesson to remove",
            error_signature="A totally different, unrelated error signature",
        )
    )

    result = main.prune_lesson(remove["id"])

    assert result == {"deleted": True}
    listing = main.list_lessons()
    assert [entry["id"] for entry in listing] == [keep["id"]]


# --- prune_lesson: path-traversal rejection (security regression, Task 5 review) ---
#
# Before the fix, `id` was concatenated straight into a filesystem path
# with no validation, so `prune_lesson(id="/etc/passwd")` or a relative
# `..` id could delete an arbitrary `.md`-suffixed file anywhere the
# server process can write. Each test plants a real "victim" file
# outside the project's `lessons_dir` and asserts it survives untouched.


def test_prune_lesson_rejects_absolute_path_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    victim = project_dir / "victim.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson(str(victim))

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_prune_lesson_rejects_relative_traversal_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    # lessons_dir is project_dir/.debug-memory/lessons -- two levels deep.
    victim = project_dir / "some-marker-file.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson("../../some-marker-file")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_prune_lesson_rejects_id_with_embedded_slash(isolated_project):
    project_dir, _ = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    subdir = lessons_dir / "subdir"
    subdir.mkdir(parents=True)
    victim = subdir / "thing.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson("subdir/thing")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


# --- clear_capture_marker (Task 7 review fix) --------------------------------
#
# Moves marker deletion out of agents/lesson-distiller.md's Bash `rm -f`
# (which silently no-op'd: ${CLAUDE_PLUGIN_DATA} isn't reliably exported
# to a Bash-tool subprocess) into this MCP tool, which reuses _cache_dir
# -- already confirmed to read CLAUDE_PLUGIN_DATA successfully by every
# other tool above.


def test_clear_capture_marker_deletes_an_existing_marker(isolated_project):
    _, cache_dir = isolated_project
    marker = cache_dir / "session-abc-123.marker"
    marker.touch()

    result = main.clear_capture_marker("abc-123")

    assert result == {"cleared": True}
    assert not marker.exists()


def test_clear_capture_marker_is_a_no_op_on_a_missing_marker(isolated_project):
    _, cache_dir = isolated_project
    assert list(cache_dir.glob("*.marker")) == []

    result = main.clear_capture_marker("never-marked-session")

    assert result == {"cleared": False}
    assert list(cache_dir.glob("*.marker")) == []


def test_clear_capture_marker_leaves_other_sessions_markers_alone(isolated_project):
    _, cache_dir = isolated_project
    other_marker = cache_dir / "session-someone-else.marker"
    other_marker.touch()
    my_marker = cache_dir / "session-my-session.marker"
    my_marker.touch()

    result = main.clear_capture_marker("my-session")

    assert result == {"cleared": True}
    assert not my_marker.exists()
    assert other_marker.exists()


# --- clear_capture_marker: path-traversal rejection (mirrors prune_lesson) ---
#
# Same shape of regression coverage as prune_lesson's own path-traversal
# tests above: a hostile session_id must be rejected with ValueError
# before it ever gets a chance to build a path outside the plugin data
# directory, and any victim file placed where the traversal would have
# landed must survive untouched.


def test_clear_capture_marker_rejects_relative_traversal_session_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, cache_dir = isolated_project
    # cache_dir is a direct child of tmp_path (one level deep, unlike
    # lessons_dir which is two levels under project_dir) -- so "one level
    # up" from cache_dir is tmp_path itself, where isolated_project
    # placed both project_dir and cache_dir as siblings.
    victim = cache_dir.parent / "victim.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker("../victim")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_absolute_path_session_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    victim = project_dir / "victim.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker(str(victim))

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_session_id_with_embedded_slash(isolated_project):
    _, cache_dir = isolated_project
    subdir = cache_dir / "subdir"
    subdir.mkdir()
    victim = subdir / "thing.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker("subdir/thing")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_dot_dot_session_id(isolated_project):
    with pytest.raises(ValueError):
        main.clear_capture_marker("..")


def test_clear_capture_marker_rejects_empty_session_id(isolated_project):
    with pytest.raises(ValueError):
        main.clear_capture_marker("")


# --- clear_capture_marker: sanitization must match hooks/mark_error.py -------


def test_clear_capture_marker_matches_mark_error_pys_sanitization(isolated_project):
    """A session_id containing characters mark_error.py sanitizes (but
    with no path separator, so it isn't the path-traversal-shaped case
    _resolve_marker_path rejects outright -- see that function's
    docstring for why those two cases are handled differently) must
    resolve to the exact same marker filename on both the write side
    (the real hooks/mark_error.py script, run as a subprocess here,
    matching how hooks/tests/test_mark_and_capture.py itself invokes it)
    and this tool's delete side.
    """
    _, cache_dir = isolated_project
    session_id = "session: weird chars! ☃"

    payload = {
        "session_id": session_id,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {},
        "tool_use_id": "toolu_01ABC123",
        "error": "boom",
    }
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_DATA"] = str(cache_dir)
    env.pop("CLAUDE_PROJECT_DIR", None)

    mark_result = subprocess.run(
        [sys.executable, str(MARK_ERROR_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert mark_result.returncode == 0, f"stderr: {mark_result.stderr!r}"

    markers_before = list(cache_dir.glob("*.marker"))
    assert len(markers_before) == 1, (
        f"expected exactly one marker written by mark_error.py, got {markers_before}"
    )

    result = main.clear_capture_marker(session_id)

    assert result == {"cleared": True}
    assert not markers_before[0].exists()
    assert list(cache_dir.glob("*.marker")) == []
```
