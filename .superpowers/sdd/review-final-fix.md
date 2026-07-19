# Review package: final whole-plugin review fixes (C1/I1/I2/I4/M1) — no git, file dump


## server/main.py
```
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
```

## server/index.py
```
"""Local embedding index for lesson similarity search.

Wraps `fastembed`'s local (no-network-at-query-time, no-API-key) ONNX
embedding model to build and query a similarity index over saved
debugging lessons, per the plan's Global Constraints:

    Local embeddings: fastembed, model BAAI/bge-small-en-v1.5 (384-dim).
    Pin this exact model string everywhere it's referenced so every
    teammate's index is byte-compatible.

    Index cache: ${CLAUDE_PLUGIN_DATA} (rebuildable from the markdown
    lessons at any time — never treat it as source of truth).

    search_lessons(query, k=3) -> ..., empty list if nothing clears the
    similarity threshold (never return a weak match dressed as strong).

This module takes `cache_dir: Path` as a plain parameter rather than
reading `${CLAUDE_PLUGIN_DATA}` itself — resolving that env var into a
real path is Task 4's MCP-wiring job (this task has no MCP dependency and
does not touch server/main.py).

Index format: a single JSON file (`index.json`) under `cache_dir`
containing `{model, dim, records: [{id, path, vector}, ...], skipped:
[{path, error}, ...]}`. Every field in a record is either present in, or
trivially recomputed from, the lesson `.md` files themselves (`id` and
`vector` come from parsing + embedding a lesson's `match_text()`; `path`
is just the file's location) — nothing lives only in the index.
`skipped` lists any `.md` file under `lessons_dir` that failed to read or
parse during the most recent `build_index` call (see `build_index`'s
docstring) — empty in the common case where every lesson file parses
cleanly. `build_index` always does a full rebuild by re-reading every
`.md` file in `lessons_dir` from scratch, so a corrupted or deleted
`index.json` is always fully recoverable by
calling `build_index` again; the cache is never treated as authoritative.

No MCP dependency. Pure logic (network access is needed only once, on
first use, for fastembed to download and locally cache the ONNX model
weights — after that, embedding is fully local). `server/main.py` is not
touched by this module or by this task.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding

from schema import parse_lesson

logger = logging.getLogger(__name__)

# Pinned exact model string — must match everywhere it's referenced
# (Global Constraints) so every teammate's index is byte-compatible.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

INDEX_FILENAME = "index.json"

# Default cosine-similarity floor for search(). Empirically calibrated
# (see server/tests/test_index.py and the Task 3 report) against
# bge-small-en-v1.5's actual score distribution on this plugin's fixture
# lessons: a query closely matching a lesson's title/error_signature/tags
# scores ~0.80-0.91 against that lesson; genuinely unrelated queries
# (different domain entirely) top out around ~0.42-0.45 against every
# lesson; queries that only loosely share a domain word without matching
# the actual incident sit in a ~0.53-0.62 middle band. 0.55 sits with
# real margin above the unrelated ceiling (never returns a weak match
# dressed as strong) and well below genuine matches, while also
# filtering out shallow same-domain-word-only noise. The plan explicitly
# flags this as "tuned empirically in Task 8's matching tests" — this is
# a documented, evidence-based starting point, not a final calibration.
DEFAULT_THRESHOLD = 0.55

# Lazily constructed and cached at module scope: loading the ONNX model
# (and, on first-ever use on a machine, downloading its weights) is
# expensive enough that every embed() call must not repeat it.
_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    """Embed a single string into the model's 384-dim vector space.

    Returns a plain `list[float]` (not a numpy array) so callers/tests
    don't need a numpy dependency and the vector round-trips cleanly
    through JSON.
    """
    model = _get_model()
    (vector,) = model.embed([text])
    return [float(x) for x in vector]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_index(lessons_dir: Path, cache_dir: Path) -> Path:
    """Read every lesson markdown file under `lessons_dir`, embed each
    lesson's `match_text()` (title + error_signature + domain + retrieval
    tags — never raw stack traces, per Global Constraints and
    `Lesson.match_text()`), and write a flat vector file to `cache_dir`.

    Always a full rebuild from scratch (reads every `.md` file fresh;
    does not attempt to diff against a prior index), matching "Index
    format must be fully rebuildable from the markdown lessons alone —
    never treat the cache as authoritative." `lessons_dir` not existing
    yet is not an error — it just means an empty index (no lessons saved
    yet).

    A lesson file that fails to read or parse (malformed frontmatter,
    missing body section, invalid YAML, a future bug in `parse_lesson`,
    etc.) is skipped rather than aborting the entire build: one corrupt
    `.md` file must never disable search over every other, valid lesson.
    Each skip is logged (`logging.warning`, module logger `server.index`)
    and also collected into a `"skipped": [{"path", "error"}, ...]` list
    written alongside `"records"` in `index.json`, so a caller can inspect
    what was skipped and why without needing a separate return value —
    `build_index` still returns just the index path, keeping its existing
    call signature/return type for current callers (this module's own
    `search()`, this task's tests, and Task 4's planned usage). The catch
    is intentionally broad (`Exception`, not just `ValueError`): malformed
    YAML syntax raises `yaml.YAMLError` (a different hierarchy than the
    `ValueError` `parse_lesson` raises for structurally-valid-YAML-but-
    semantically-incomplete lessons), and an interrupted write or manual
    edit can produce input that fails in other ways too (e.g. a
    non-UTF-8-decodable file raising `UnicodeDecodeError` from
    `read_text`) — all of those are "this one file is bad," not "the
    whole index build should abort." Only the per-file read+parse step is
    covered by this catch; `embed()` failures (an infra/model problem,
    not a data-quality problem) are still allowed to propagate.

    Returns the path to the written index file.
    """
    lessons_dir = Path(lessons_dir)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if lessons_dir.exists():
        for lesson_path in sorted(lessons_dir.glob("*.md")):
            try:
                text = lesson_path.read_text(encoding="utf-8")
                lesson = parse_lesson(text)
            except Exception as exc:
                logger.warning(
                    "build_index: skipping unparseable lesson file %s: %s: %s",
                    lesson_path,
                    type(exc).__name__,
                    exc,
                )
                skipped.append(
                    {
                        "path": str(lesson_path),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            vector = embed(lesson.match_text())
            records.append(
                {
                    "id": lesson.id,
                    "path": str(lesson_path),
                    "vector": vector,
                }
            )

    index_path = cache_dir / INDEX_FILENAME
    payload = json.dumps(
        {
            "model": MODEL_NAME,
            "dim": EMBEDDING_DIM,
            "records": records,
            "skipped": skipped,
        }
    )

    # Atomic write (final whole-project review, Finding I2): write to a
    # temp file in the SAME directory as index_path, then os.replace() it
    # over the real path. A plain `index_path.write_text(...)` truncates
    # the destination file in place before writing the new bytes, so a
    # concurrent `search()` call (a second MCP tool invocation, or this
    # same rebuild racing a stray leftover process) could observe a
    # file that's been truncated but not yet fully rewritten -- `json.
    # loads()` on that half-written content raises `json.JSONDecodeError`
    # and crashes the search tool call outright. `tempfile.mkstemp(dir=...)`
    # creates the temp file in the same directory as `index_path` (not the
    # platform tempdir) so `os.replace()` is a same-filesystem rename --
    # atomic on POSIX, and the only portable way to guarantee a reader
    # never observes a partial file: it either sees the old complete
    # index.json or the new complete one, never a half-written mix of the
    # two.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{INDEX_FILENAME}.", suffix=".tmp", dir=str(cache_dir)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
        os.replace(tmp_name, index_path)
    except BaseException:
        # Best-effort cleanup of the temp file if anything above failed
        # before the rename -- must not mask the original exception, and
        # must not itself raise if the temp file is already gone.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return index_path


def search(
    query: str,
    cache_dir: Path,
    k: int = 3,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Embed `query`, cosine-similarity it against the cached vectors in
    `cache_dir`, and return the top-`k` records that clear `threshold`,
    sorted descending by score.

    Returns `[]` if the index doesn't exist yet, is empty, or nothing
    clears `threshold` — never a weak match dressed as strong (Global
    Constraints).

    Model/dim guard (final whole-project review, Finding M1): if the
    loaded `index.json`'s `model`/`dim` fields don't match this module's
    pinned `MODEL_NAME`/`EMBEDDING_DIM`, the index is treated as stale or
    foreign rather than compared against directly. Without this check, a
    future change to the pinned model string (different dimensionality)
    would silently feed mismatched-length vectors into `_cosine_
    similarity`'s `zip(a, b)`, which truncates to the shorter vector
    instead of raising — producing a meaningless similarity score, not an
    error. This same guard is defense in depth for Finding C1's per-
    project cache partitioning fix (`server/main.py`'s `_project_slug`):
    if some other bug or manual filesystem operation ever lets one
    project's `index.json` end up read by another project (or by a
    machine running a different pinned model version), this check catches
    the mismatch rather than silently comparing vectors that were never
    meant to be compared. On a mismatch, this deletes the stale/foreign
    `index.json` and returns `[]` for this call -- rather than extending
    this function's signature to also take `lessons_dir` and rebuild
    inline, which would give `search()` a second responsibility (index
    *building*, not just *searching*) it doesn't otherwise have. Deleting
    the file means the caller's own on-demand-build-if-missing logic
    (`server/main.py`'s `search_lessons`, see its own docstring) will see
    a missing `index.json` on its very next call and rebuild it from the
    markdown lessons automatically — self-healing without widening this
    function's contract.

    Each returned dict is `{id, path, score}`; callers that need the full
    lesson content (title, failed_approaches, root_cause, fix, ...) parse
    the file at `path` via `schema.parse_lesson` — Task 4's `search_lessons`
    tool wiring does that to build the final `{id, title, score,
    failed_approaches, root_cause, fix, path}` shape from Global
    Constraints; this module only owns similarity ranking.
    """
    cache_dir = Path(cache_dir)
    index_path = cache_dir / INDEX_FILENAME
    if not index_path.exists():
        return []

    data = json.loads(index_path.read_text(encoding="utf-8"))

    if data.get("model") != MODEL_NAME or data.get("dim") != EMBEDDING_DIM:
        logger.warning(
            "search: index at %s was built with model=%r dim=%r (pinned "
            "model is %r, dim=%r) -- treating as stale/foreign, deleting "
            "it, and returning no results this call. The next "
            "search_lessons call will see index.json missing and trigger "
            "its own on-demand rebuild rather than comparing "
            "mismatched-dimension vectors.",
            index_path,
            data.get("model"),
            data.get("dim"),
            MODEL_NAME,
            EMBEDDING_DIM,
        )
        try:
            index_path.unlink()
        except OSError:
            pass
        return []

    records = data.get("records", [])
    if not records:
        return []

    query_vector = embed(query)
    scored = [
        {
            "id": record["id"],
            "path": record["path"],
            "score": _cosine_similarity(query_vector, record["vector"]),
        }
        for record in records
    ]
    scored = [r for r in scored if r["score"] >= threshold]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]
```

## server/reindex.py
```
#!/usr/bin/env python3
"""Standalone CLI: full rebuild of the hindsight local similarity index.

Usage (`uv`, not bare `python3` -- this imports `index.py`, which needs
`fastembed`, and `main.py`, which needs `mcp`; see `server/requirements.txt`
and this repo's own `.mcp.json`, which launches the MCP server the exact
same way):

    uv run --no-project --with-requirements server/requirements.txt \\
        server/reindex.py [--lessons-dir DIR] [--cache-dir DIR]

Always a FULL rebuild -- `index.build_index` re-reads every `*.md` file
under `lessons_dir` from scratch every time it's called (see that
function's own docstring); this script never attempts an incremental
update. Prints how many lessons were indexed and, if any lesson files
failed to parse, which ones and why (`skipped`, same shape
`save_lesson`'s own `warnings` surfaces).

Path resolution: `--lessons-dir`/`--cache-dir` are optional. Omitted,
they fall back to `main.py`'s own `_lessons_dir()`/`_cache_dir()` -- the
exact same `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA`-then-cwd resolution
every MCP tool in this server already uses (imported from `main.py`
rather than re-implemented a third time here, matching this codebase's
existing "one parser"/"one sanitizer" preference -- see e.g.
`schema.parse_lesson`'s and `main._sanitize_session_id`'s own docstrings
for the same reasoning applied elsewhere). A run from inside a real
Claude Code project directory with those two env vars actually exported
(or set by hand) resolves the same `lessons_dir`/`cache_dir` the MCP
server itself reads from and writes to.

IMPORTANT -- this is NOT what `/hindsight reindex` calls. `${CLAUDE_
PLUGIN_DATA}` (and `${CLAUDE_PROJECT_DIR}`) are only reliably exported as
real environment variables to a hook process or an MCP/LSP server
subprocess -- NOT to a `Bash`-tool invocation made during a normal agent
turn (see `main.py`'s own module docstring, and the Task 7 review fix for
`clear_capture_marker`, which hit exactly this failure mode: a `Bash`
`rm -f "${CLAUDE_PLUGIN_DATA}/..."` silently no-op'd because the shell
never saw the variable, and the fix was to move that logic into the MCP
server process instead). Running *this* script via the `Bash` tool from
inside a live session would hit the identical problem -- `_lessons_dir()`/
`_cache_dir()`'s env-var reads would silently fail and fall back to
cwd-relative directories that do NOT match the real, Claude-Code-managed
plugin data directory the running MCP server actually reads its index
cache from. It would look like it worked (a plausible "N lessons
indexed" message) while rebuilding an index nobody ever searches.

`skills/hindsight/SKILL.md`'s `/hindsight reindex` subcommand therefore
calls the `reindex_lessons` MCP tool (`server/main.py`) instead, which
runs inside the MCP server process and always resolves the real env vars
correctly -- see that tool's own docstring for the full reasoning. This
script exists for everything else a full rebuild is useful for outside
that specific in-session context: CI, a maintainer's own terminal with
`CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` exported by hand, or pointed at
an explicit `--lessons-dir`/`--cache-dir` pair (e.g. for local testing
against a scratch fixtures directory, independent of any real plugin
install).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import index
from main import _cache_dir, _lessons_dir


def reindex(lessons_dir: Path, cache_dir: Path) -> dict:
    """Rebuild the index at `cache_dir` from every lesson `.md` file
    under `lessons_dir`, and return a summary dict: `{"indexed": <N>,
    "skipped": [...], "lessons_dir": <str>, "index_path": <str>}` -- the
    exact same shape `server/main.py`'s `reindex_lessons` MCP tool
    returns (this function IS that tool's implementation, extracted so
    both the CLI below and, in principle, a test can call it directly
    without going through `argparse`).
    """
    index_path = index.build_index(lessons_dir, cache_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "indexed": len(data.get("records", [])),
        "skipped": data.get("skipped", []),
        "lessons_dir": str(lessons_dir),
        "index_path": str(index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Full rebuild of the hindsight local similarity index from "
            "every lesson .md file on disk."
        )
    )
    parser.add_argument(
        "--lessons-dir",
        type=Path,
        default=None,
        help=(
            "Directory of lesson .md files to index. Defaults to the same "
            "CLAUDE_PROJECT_DIR-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/lessons under the current "
            "working directory if CLAUDE_PROJECT_DIR is unset)."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write index.json to. Defaults to the same "
            "CLAUDE_PLUGIN_DATA-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/.hindsight-cache if unset, or "
            "${CLAUDE_PLUGIN_DATA}/<project slug>/ if set -- see "
            "this script's module docstring for why that default will NOT "
            "match a real installed plugin's actual cache directory unless "
            "CLAUDE_PLUGIN_DATA is exported."
        ),
    )
    args = parser.parse_args()

    lessons_dir = args.lessons_dir if args.lessons_dir is not None else _lessons_dir()
    cache_dir = args.cache_dir if args.cache_dir is not None else _cache_dir()

    result = reindex(lessons_dir, cache_dir)

    print(f"Reindexed {result['indexed']} lesson(s) from {result['lessons_dir']}")
    if result["skipped"]:
        print(f"Skipped {len(result['skipped'])} file(s) that failed to parse:")
        for entry in result["skipped"]:
            print(f"  - {entry['path']}: {entry['error']}")
    print(f"Index written to {result['index_path']}")
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
`${CLAUDE_PLUGIN_DATA}/<project slug>/session-<session_id>.marker` so
`hooks/capture.py` (the `Stop` hook, also Task 7) can tell, at session
end, whether *this* session ever hit a tool failure worth possibly
turning into a lesson. Content doesn't matter, only existence, per the
brief -- the file is created empty (`Path.touch`).

The `<project slug>` path component (final whole-project review, Finding
C1) was added because `${CLAUDE_PLUGIN_DATA}` is one directory per plugin
PER MACHINE, not per project -- shared across every repo on this machine
that has this plugin installed. Marker filenames were never actually at
risk of colliding across projects (session ids are globally unique), but
`server/main.py`'s `_cache_dir()` -- which resolves the very same
`${CLAUDE_PLUGIN_DATA}` directory this script writes markers into -- had
exactly this per-project-leakage bug for `index.json` (see that module's
`_project_slug` docstring for the full story). Co-locating markers under
the same per-project subdirectory as the index cache keeps one consistent
partitioning scheme instead of a mix of per-project and machine-global
files sitting side by side in `${CLAUDE_PLUGIN_DATA}`.

Never blocks or fails the tool-failure event over this: any problem
reading stdin, parsing the payload, a missing/malformed `session_id`, or
a filesystem error while creating the marker's parent directory or the
file itself is swallowed, and this exits 0 either way. The brief calls
out explicitly that a missing `${CLAUDE_PLUGIN_DATA}` directory (e.g. a
freshly installed plugin, first failure of the session) "must not fail
or block" this hook -- `_plugin_data_dir` below creates it
(`mkdir(parents=True, exist_ok=True)`) rather than assuming it exists.

Env var resolution (`${CLAUDE_PLUGIN_DATA}`, marker file location):
duplicates the tiny amount of logic `server/main.py`'s `_cache_dir()`/
`_project_slug()` use (`os.environ.get("CLAUDE_PLUGIN_DATA")`,
`hashlib.sha256`-derived project slug, then
`.mkdir(parents=True, exist_ok=True)`; see those functions' own
docstrings for the full env-var-injection and per-project-partitioning
story) rather than importing from `server/` -- hooks are separate Python
processes from the MCP server (different concern, different process
lifecycle; importing across that boundary for ~15 lines of logic would
just be a coupling liability for no real benefit). This is also
intentionally NOT factored into a new shared helper module under
`hooks/` and imported by both this file and `hooks/capture.py`: every
hook script in this plugin is a fully standalone, dependency-free
`python3` script (the precedent Task 6's `retrieve.py` set, verified by
its own `test_no_non_stdlib_imports` test), so this duplicates the same
helper a second time (byte-for-byte identical to `capture.py`'s copy)
rather than introducing an intra-`hooks/` import dependency between two
scripts that are otherwise independently invoked, independently
timed-out, and independently tested.

The fallback used when `CLAUDE_PLUGIN_DATA` is unset (standalone/test
use, same rationale as `_cache_dir()`'s own documented fallback) is
`${CLAUDE_PROJECT_DIR or cwd}/.debug-memory/.hindsight-cache` -- the
SAME leaf directory name `server/main.py`'s `_cache_dir()` fallback uses
(`_FALLBACK_CACHE_LEAF`). Before the final whole-project review's Finding
I4 fix, this fallback used a different leaf name (`.plugin-data`) than
`_cache_dir()`'s own fallback (`.index-cache`) -- two different
directories for what, in the fallback case, must be the exact same
directory: a marker this script wrote was never actually found by
`server/main.py`'s `clear_capture_marker` when both ran with
`CLAUDE_PLUGIN_DATA` unset (a standalone/test-only scenario -- a real
plugin install always has `CLAUDE_PLUGIN_DATA` set, so this gap never
affected a real install, only standalone runs without it). One name, used
by every one of the three files that needs it, closes that gap. No
`_project_slug()` partitioning is applied to THIS fallback path -- it's
already nested under `${CLAUDE_PROJECT_DIR}` (or `cwd`), i.e. already
per-project on its own, so adding a slug subdirectory on top would just
be redundant double-nesting (matches `_cache_dir()`'s own fallback
reasoning).

In a real plugin install, both marker files and the index cache land
under the very same real `${CLAUDE_PLUGIN_DATA}/<project slug>/`
directory -- see the module docstring's "Job" section above for why the
`<project slug>` component exists. Tests in this repo don't rely on the
fallback; they set `CLAUDE_PLUGIN_DATA` (and, since the Finding C1 fix,
`CLAUDE_PROJECT_DIR`, so the computed project slug is deterministic)
explicitly per-subprocess so each test is isolated to its own tmp
directory.

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

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Must match server/main.py's _FALLBACK_CACHE_LEAF byte-for-byte (Finding
# I4) -- see the module docstring's "Env var resolution" section.
_FALLBACK_CACHE_LEAF = ".hindsight-cache"


def _project_slug() -> str:
    """Byte-for-byte duplicate of `server/main.py`'s `_project_slug()`
    (see that function's docstring for the full C1-fix reasoning) --
    duplicated rather than imported for the same "hooks are standalone
    dependency-free scripts" reason every other helper in this file is
    duplicated (see module docstring). Must stay identical to
    `server/main.py`'s copy and to `hooks/capture.py`'s copy: all three
    partition `${CLAUDE_PLUGIN_DATA}` by this same slug, and a mismatch
    would silently reintroduce Finding C1's cross-project leakage for
    marker files specifically.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    key = project_dir if project_dir else str(Path.cwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    basename = Path(key).name or "root"
    safe_basename = _SAFE_CHARS_RE.sub("_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _plugin_data_dir() -> Path:
    """Resolve this project's `${CLAUDE_PLUGIN_DATA}/<project slug>/`
    directory (see module docstring), creating it if it doesn't exist
    yet.
    """
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data) / _project_slug()
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / _FALLBACK_CACHE_LEAF
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
marked by touching
`${CLAUDE_PLUGIN_DATA}/<project slug>/session-<session_id>.marker`. The
`<project slug>` component (final whole-project review, Finding C1) is
explained in `hooks/mark_error.py`'s own module docstring -- this script
must compute the identical slug or it will never find a marker that
script wrote.

  - No marker for this `session_id` (including when `session_id` is
    itself missing or unparseable from a malformed payload): exit 0,
    print nothing. A session that never hit a tool failure -- the common
    case, true for every `Stop` in a clean session -- must produce zero
    stdout; this is the "no-op" behavior `hooks/tests/
    test_mark_and_capture.py` checks for.
  - Marker exists: print the `hookSpecificOutput` nudge below (with this
    session's `session_id` interpolated into it -- see Finding I1 below)
    and exit 0.

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
this raw text to the user instead of Claude acting on it. The bulk of
this string is taken verbatim from the Task 7 brief (itself already
corrected to factual phrasing after Task 6's review, per that brief's own
note) -- not paraphrased or reworded, EXCEPT for one addition made by the
final whole-project review's Finding I1 fix (see below): the text now
also states this session's `session_id` value literally, in backticks.

Finding I1 / session_id interpolation: `agents/lesson-distiller.md`
expects to be dispatched WITH a `session_id`, so it can call
`clear_capture_marker(session_id)` after a successful save (see that
agent file and `server/main.py`'s `clear_capture_marker` for why that
matters -- without it, this same nudge re-fires on every subsequent
`Stop` in the session even after the lesson is actually captured). But
nothing before this fix ever handed Claude that value: this script reads
`session_id` from the `Stop` payload to decide whether to nudge at all,
but the nudge text itself was a FIXED string that never included it, and
Claude Code does not automatically surface a hook's raw JSON input
fields into the model's context -- only what a hook actually prints in
`additionalContext` is visible. So the dispatching Claude turn had no
reliable way to know the real `session_id` to hand to the distiller,
`clear_capture_marker` would fail to find/clear the marker, and the nudge
would re-fire every subsequent `Stop` for the rest of the session -- the
exact bug Task 7 already fixed once (an earlier version tried deleting
the marker via a `Bash`-tool `rm -f` that couldn't see
`${CLAUDE_PLUGIN_DATA}`), reappearing via this different gap. The fix:
`_build_additional_context` below interpolates the real, UNSANITIZED
`session_id` (see that function's own docstring for why it's the raw
value, not the sanitized `safe_id` used for the marker filename)
directly into the printed text, so it is now literally present in what
Claude sees and can copy into the distiller's dispatch prompt.

Env var resolution / sanitization: an intentional byte-for-byte
duplicate of `hooks/mark_error.py`'s `_project_slug`/`_plugin_data_dir`/
`_marker_path` (see that file's module docstring for the full reasoning
on why this is duplicated -- both from `server/`, and between these two
hook scripts, rather than shared via a new intra-`hooks/` helper module).
Kept identical to `mark_error.py`'s copy so a given real `session_id`
always resolves to the same marker path on both the write side
(`mark_error.py`) and this read side.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")

# Must match server/main.py's _FALLBACK_CACHE_LEAF and
# hooks/mark_error.py's copy byte-for-byte (Finding I4) -- see the module
# docstring's "Env var resolution" section.
_FALLBACK_CACHE_LEAF = ".hindsight-cache"

# Template for the Stop-hook nudge (final whole-project review, Finding
# I1). The non-`{session_id}` portions are taken verbatim from the Task 7
# brief (see module docstring) -- do not reword them incidentally.
# `hooks/tests/test_mark_and_capture.py` builds the same expected string
# per-session_id and asserts it exactly, so this and that test's copy
# must stay in sync.
ADDITIONAL_CONTEXT_TEMPLATE = (
    "This session hit a tool failure earlier. If it's now resolved, the "
    "lesson-distiller agent (subagent_type: lesson-distiller) can turn "
    "it into a saved lesson from this session's session_id, `{session_id}`, "
    "and a concise summary — error signature, symptom, failed approaches, "
    "root cause, fix — with secrets/tokens/customer data excluded. Not "
    "worth dispatching if the error wasn't actually resolved this "
    "session."
)


def _build_additional_context(session_id: str) -> str:
    """Fill `ADDITIONAL_CONTEXT_TEMPLATE` with this session's real,
    UNSANITIZED `session_id` (not the filesystem-safe `safe_id` used for
    the marker filename -- the text is not a path, so the raw value is
    fine here, and the distiller agent needs the real id to pass back to
    `clear_capture_marker`, not a lossy sanitized copy of it).
    """
    return ADDITIONAL_CONTEXT_TEMPLATE.format(session_id=session_id)


def _project_slug() -> str:
    """Byte-for-byte duplicate of `server/main.py`'s and
    `hooks/mark_error.py`'s `_project_slug()` (see either's docstring for
    the full C1-fix reasoning). Must stay identical across all three
    copies -- see `hooks/mark_error.py`'s copy for why.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    key = project_dir if project_dir else str(Path.cwd())
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    basename = Path(key).name or "root"
    safe_basename = _SAFE_CHARS_RE.sub("_", basename)[:40] or "project"
    return f"{safe_basename}-{digest}"


def _plugin_data_dir() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        data_dir = Path(plugin_data) / _project_slug()
    else:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base = Path(project_dir) if project_dir else Path.cwd()
        data_dir = base / ".debug-memory" / _FALLBACK_CACHE_LEAF
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
            "additionalContext": _build_additional_context(session_id),
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
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
  session's session_id -- read it directly from the capture nudge's own
  text (hooks/capture.py's additionalContext literally states it as
  "...this session's session_id, `<the actual id>`..."), NOT from the
  Stop hook's raw JSON payload, which is never surfaced into the model's
  context on its own (only what a hook prints in additionalContext is
  visible).
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
