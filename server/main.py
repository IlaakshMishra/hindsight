#!/usr/bin/env python3
"""Hindsight MCP server.

Exposes the `hindsight` tool surface (`search_lessons`, `save_lesson`,
`list_lessons`, `prune_lesson`, `clear_capture_marker`, `reindex_lessons`)
over stdio using the official MCP Python SDK's FastMCP helper.

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

Task 8 adds `reindex_lessons`: an unconditional full rebuild of the local
similarity index (`index.build_index`), for the "teammate committed new
lesson files, this machine's cache is stale" case `search_lessons`'s own
on-demand build doesn't cover (see `reindex_lessons`'s own docstring).

Runtime paths (never hardcoded, never resolved by hand into `.mcp.json`
-- that file keeps `${CLAUDE_PLUGIN_ROOT}` as a literal, Claude-Code-
substituted token, unrelated to the two variables this module reads):
  - Lessons live at `${CLAUDE_PROJECT_DIR}/.debug-memory/lessons/`.
  - The index cache (and, since the final whole-project review's Finding
    C1 fix below, per-session capture markers too) lives at
    `${CLAUDE_PLUGIN_DATA}/<project slug>/` -- NOT directly at
    `${CLAUDE_PLUGIN_DATA}` itself. See `_cache_dir`/`_project_slug`
    below for why: `${CLAUDE_PLUGIN_DATA}` is one directory per plugin
    PER MACHINE (confirmed against the real on-disk layout, `~/.claude/
    plugins/data/<plugin-id>/`), shared across every project on that
    machine that has this plugin installed -- unlike
    `${CLAUDE_PROJECT_DIR}`, which is already one directory per project.
    Before this fix, two different repos on one machine shared a single
    `index.json`, so saving a lesson in one project could make
    `search_lessons` in a completely unrelated project return that
    project's lessons (with `path`s pointing into the wrong repo).
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

import hashlib
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


# Fallback leaf directory name used by `_cache_dir` below when
# `${CLAUDE_PLUGIN_DATA}` is unset (standalone/test scenario -- see
# `_cache_dir`'s own docstring). Kept as a module-level constant, and its
# literal value (not this constant itself, since hooks are standalone
# scripts that don't import from `server/` -- see the module docstring's
# "Task 7 review fix" section and `hooks/mark_error.py`'s own docstring
# for why) duplicated byte-for-byte in `hooks/mark_error.py` and
# `hooks/capture.py`'s own `_plugin_data_dir` fallback branch. Before the
# final whole-project review's Finding I4 fix, this leaf was named
# `.index-cache` here but `.plugin-data` in both hook scripts -- two
# different names for what, in the fallback case, must be the exact same
# directory (a marker `hooks/mark_error.py` writes has to be findable by
# this module's `clear_capture_marker`) -- so a marker written by a hook
# running with `CLAUDE_PLUGIN_DATA` unset was never actually found by
# `clear_capture_marker` running in the same fallback mode. One name, used
# everywhere, closes that gap.
_FALLBACK_CACHE_LEAF = ".hindsight-cache"

# Matches `_SESSION_ID_SAFE_CHARS_RE` below in character class (both are
# "safe bare filename component" charsets) but kept as its own regex
# object since it partitions a *project directory path* rather than a
# *session id* -- different domain, even though the substitution rule is
# identical. `hooks/mark_error.py`/`hooks/capture.py` reuse their own
# existing `_SAFE_CHARS_RE` for this same purpose instead of adding a
# second regex, since in those files there's already exactly one such
# regex in scope; this file already has a second one
# (`_SESSION_ID_SAFE_CHARS_RE`) for an unrelated reason (see that
# constant's own comment), so a distinctly-named one here avoids any
# confusion about which one a given call site means.
_PROJECT_SLUG_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _project_slug() -> str:
    """Derive a stable, filesystem-safe slug for the current consuming
    project, used by `_cache_dir` below to partition the shared
    `${CLAUDE_PLUGIN_DATA}` directory per-project (final whole-project
    review, Finding C1).

    `${CLAUDE_PLUGIN_DATA}` resolves to one directory per plugin PER
    MACHINE (confirmed against the real on-disk layout: `~/.claude/
    plugins/data/<plugin-id>/`) -- shared across EVERY project on that
    machine that has this plugin installed, unlike `${CLAUDE_PROJECT_DIR}`
    which is already one directory per project. Before this fix,
    `_cache_dir()` returned `${CLAUDE_PLUGIN_DATA}` directly with no
    per-project component, so `index.json` lived at a single fixed path
    shared by every project: a developer working in two different repos
    on the same machine got ONE shared index. Saving a lesson in project
    A would rebuild that shared `index.json` from project A's lessons;
    switching to project B and calling `search_lessons` would return
    project A's lessons (with `path`s pointing into project A's repo) --
    silently wrong, not an error -- because `search_lessons`'s own
    on-demand build only fires when `index.json` is entirely *missing*,
    and it wasn't.

    Slug shape: `"<sanitized-basename>-<12 hex chars of
    sha256(project_dir)>"`. The basename half is purely for human
    readability when browsing `${CLAUDE_PLUGIN_DATA}` by hand (e.g.
    `~/.claude/plugins/data/hindsight/my-api-a1b2c3d4e5f6/`) -- it is NOT
    relied on for uniqueness, since two different directories can share a
    basename (`~/work/api` and `~/personal/api` both end in `api`). The
    hash half is what actually guarantees two different project
    directories never collide on one cache directory: it's a pure string
    digest of the raw `${CLAUDE_PROJECT_DIR}` value (or the `Path.cwd()`
    fallback used when that env var is unset, matching `_lessons_dir`'s
    own fallback) -- no filesystem I/O, no symlink resolution, so this is
    cheap and cannot itself fail. 12 hex chars (48 bits) is comfortably
    enough entropy that an accidental collision between a real
    developer's local repos is a non-concern.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    key = project_dir if project_dir else str(Path.cwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    basename = Path(key).name or "root"
    safe_basename = _PROJECT_SLUG_SAFE_CHARS_RE.sub("_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _cache_dir() -> Path:
    """Resolve this project's index cache (and per-session capture
    marker) directory: `${CLAUDE_PLUGIN_DATA}/<project slug>/` (real
    deployments: `~/.claude/plugins/data/<plugin-id>/<project slug>/`,
    per the Claude Code docs), same runtime-resolution approach as
    `_lessons_dir` (see its docstring for the env-var-injection details).

    The `<project slug>` component (`_project_slug` above) is the
    Finding C1 fix: without it, every project on the machine would share
    one `${CLAUDE_PLUGIN_DATA}` directory and therefore one `index.json`
    -- see `_project_slug`'s own docstring for the full failure mode this
    closes.

    Falls back to a `.debug-memory/<_FALLBACK_CACHE_LEAF>` directory
    under the resolved project dir when `CLAUDE_PLUGIN_DATA` is unset
    (same standalone/test scenario as `_lessons_dir`'s fallback) so those
    runs still get a stable, writable cache location without a real
    plugin install. This fallback path is already nested under
    `${CLAUDE_PROJECT_DIR}` (or `cwd`), i.e. already per-project on its
    own -- so no `_project_slug()` partitioning is applied here; adding
    it would just be redundant double-nesting. Tests override via
    `monkeypatch.setenv` rather than relying on this.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        cache_dir = Path(plugin_data) / _project_slug()
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        cache_dir = base / ".debug-memory" / _FALLBACK_CACHE_LEAF
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
    at `${CLAUDE_PLUGIN_DATA}/<project slug>/session-<session_id>.marker`
    (Task 7 review fix; the `<project slug>` component was added by the
    final whole-project review's Finding C1 fix -- see `_project_slug`),
    if it exists.

    Called by `agents/lesson-distiller.md` after a successful
    `save_lesson`, so a later `Stop` event in the same session doesn't
    re-emit `hooks/capture.py`'s capture nudge for an incident that's
    already been saved. Moved here from a `Bash`-tool `rm -f` in the
    distiller agent itself because `${CLAUDE_PLUGIN_DATA}` is not
    reliably present in a `Bash`-tool subprocess's environment (see this
    module's own docstring for the full story); this server process
    reads it successfully today via `_cache_dir`, which resolves to the
    exact same per-project subdirectory under `CLAUDE_PLUGIN_DATA` that
    `hooks/mark_error.py` writes the marker into: both this module and
    both hook scripts compute the identical project slug from
    `CLAUDE_PROJECT_DIR` via independently duplicated but byte-identical
    `_project_slug()` helpers (confirmed by reading all three
    implementations side by side before writing this update -- this
    claim was false before the Finding C1/I4 fixes, when markers lived
    directly under the unpartitioned `${CLAUDE_PLUGIN_DATA}` root; it is
    accurate now that all three agree on the same partitioning).

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


@mcp.tool()
def reindex_lessons() -> dict[str, Any]:
    """Full rebuild of the local similarity index from every lesson file
    currently on disk (Task 8's `hindsight reindex` command).

    Thin wrapper around `index.build_index(_lessons_dir(), _cache_dir())`
    -- the exact same full-rebuild-from-markdown call `save_lesson` and
    `prune_lesson` already make as a side effect of every write/delete
    (see their own docstrings) -- just invokable directly, on demand,
    with no write/delete attached. Useful after a `git pull` brings in
    teammates' newly-committed lesson files: this machine's local index
    cache (`${CLAUDE_PLUGIN_DATA}`, machine-local, never git-committed --
    see this module's own docstring) doesn't know about those files yet,
    and `search_lessons`'s own on-demand build (see its docstring) only
    triggers when `index.json` is entirely *missing*, not when it's
    merely stale -- so a manual reindex is still the only way to pick up
    new lessons on a machine that already has *some* index cached.

    Deliberately runs inside this MCP server process rather than as a
    `Bash`-tool-invoked script, for the same reason `clear_capture_marker`
    above was moved into this server instead of a `Bash`-tool `rm -f`:
    `${CLAUDE_PROJECT_DIR}`/`${CLAUDE_PLUGIN_DATA}` are only reliably
    exported to a hook process or an MCP/LSP server subprocess, not to a
    `Bash`-tool invocation made during a normal agent turn (see this
    module's own docstring, and the Task 7 review fix, which hit exactly
    this bug for marker deletion). A reindex invoked via `Bash` could
    silently rebuild an index at the wrong path -- one `search_lessons`
    never reads from -- while still printing a plausible-looking "N
    lessons indexed" success message. Calling `index.build_index` from
    here instead guarantees this always rebuilds the exact same index
    every other tool in this file reads from and writes to.
    `skills/hindsight/SKILL.md`'s `/hindsight reindex` subcommand calls
    this tool for that reason. `server/reindex.py` (Task 8) is a
    separate, lower-level standalone CLI entry point for reindexing
    outside a live Claude Code session (CI, a maintainer's own terminal)
    -- see that script's module docstring for why it does NOT back
    `/hindsight reindex` itself.

    Returns `{"indexed": <N>, "skipped": [...], "lessons_dir": <str>,
    "index_path": <str>}`. `indexed` is the number of lesson files that
    parsed and were embedded into the rebuilt index. `skipped` mirrors
    `save_lesson`'s own `skipped`-surfacing: a list of `{path, error}` for
    any lesson file that failed to parse during this rebuild (`[]` in the
    common case where every lesson file parses cleanly).
    """
    lessons_dir = _lessons_dir()
    cache_dir = _cache_dir()

    index_path = index.build_index(lessons_dir, cache_dir)
    index_data = json.loads(index_path.read_text(encoding="utf-8"))

    return {
        "indexed": len(index_data.get("records", [])),
        "skipped": index_data.get("skipped", []),
        "lessons_dir": str(lessons_dir),
        "index_path": str(index_path),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
