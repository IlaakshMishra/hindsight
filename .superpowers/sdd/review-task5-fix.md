# Review package: Task 5 fix (path-traversal containment) — no git, file dump


## server/store.py
```
"""Lesson storage: read/write lesson markdown files on disk.

Owns the on-disk `.debug-memory/lessons/<id>.md` file format's I/O side
(rendering a `Lesson` to text and parsing text back into a `Lesson` are
`schema.py`'s job -- this module just decides *where* a lesson lives and
reads/writes bytes there) plus the `<id>.md` filename/slug convention.

Public API (per the Task 4 brief, plus `delete_lesson` added in Task 5 for
the `prune_lesson` MCP tool -- same "this module decides where a lesson
lives and reads/writes bytes there" ownership as the rest of this file,
just the delete side of that instead of the read/write side):
    write_lesson(lesson, lessons_dir) -> Path
    read_lesson(path) -> dict
    list_lessons(lessons_dir) -> list[dict]
    delete_lesson(lesson_id, lessons_dir) -> bool  # raises ValueError on a
                                                     # path-traversal/non-bare
                                                     # lesson_id -- see its
                                                     # own docstring and
                                                     # _resolve_lesson_path

No MCP dependency and no env-var reads. `server/main.py` resolves
`${CLAUDE_PROJECT_DIR}` into a real `lessons_dir` Path (see its own
docstring for how) and passes it in here; this module never reads
`os.environ` itself, matching the pattern `index.py` already set with
`cache_dir`.

Deviation from the brief's example signature worth flagging up front:
the brief sketches `write_lesson(payload, lessons_dir)`. This takes an
already-constructed `schema.Lesson` instead of a raw payload dict --
`server/main.py`'s `save_lesson` is the one that scrubs the raw input and
builds the `Lesson` (including the auto-derived `id`/`tags`, per the
Task 4 brief's tags decision), so by the time this module is involved
there is already a fully-formed, validated `Lesson` to render and write;
building a second, parallel "dict -> Lesson" construction path here would
just duplicate what `Lesson.__init__`/`__post_init__` already do.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from schema import Lesson, parse_lesson

logger = logging.getLogger(__name__)

# Common filler words dropped when building a title-derived slug -- purely
# to keep filenames short and content-bearing (per the brief: "<id>" is a
# "slugified YYYY-MM-DD-short-slug"), not a linguistic/NLP stopword list.
_SLUG_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "is",
        "was", "with", "at", "by", "from", "this", "that",
    }
)

# Caps slug length at this many words so ids stay filename-friendly and
# match the shape of the spec's own example ids (see
# server/tests/fixtures/*.md, e.g. "2026-07-18-fastmcp-pydantic-floor" --
# 3 words; "2026-06-02-react-useeffect-infinite-loop" -- 4 words). Not a
# hard spec requirement, just a "short" judgment call.
_MAX_SLUG_WORDS = 6

_SLUG_WORD_RE = re.compile(r"[a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, ASCII-fold, drop filler words, and hyphen-join `text`
    into a short, filename-safe slug.

    E.g. "FastMCP tool registration crashes with stale pydantic" ->
    "fastmcp-tool-registration-crashes-stale" (5 content words after
    dropping "with"; capped at `_MAX_SLUG_WORDS`).

    Falls back to the un-filtered word list (or the literal string
    "lesson") if a title is made up entirely of filler words or has no
    ASCII alphanumeric characters at all -- `Lesson.title` is required
    non-empty (see `schema.Lesson.__post_init__`) but nothing stops it
    from being e.g. pure punctuation or non-ASCII, and a slug must never
    end up empty.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    all_words = _SLUG_WORD_RE.findall(ascii_text)
    words = [w for w in all_words if w not in _SLUG_STOPWORDS] or all_words or ["lesson"]
    return "-".join(words[:_MAX_SLUG_WORDS])


def make_lesson_id(title: str, created_at: str) -> str:
    """Build the `YYYY-MM-DD-short-slug` id (also the `<id>.md` filename
    stem) from a lesson's title and `created_at` timestamp, matching the
    fixture lessons' shape (server/tests/fixtures/*.md). `created_at` is
    expected to be an ISO-8601 string (`YYYY-MM-DDTHH:MM:SSZ`, what
    `server/main.py` generates); only its leading `YYYY-MM-DD` date
    portion is used.
    """
    date_part = created_at[:10]
    return f"{date_part}-{slugify(title)}"


def write_lesson(lesson: Lesson, lessons_dir: Path | str) -> Path:
    """Render `lesson` (via `Lesson.render()`) and write it to
    `lessons_dir/<id>.md`, creating `lessons_dir` (and any missing parent
    directories) if it doesn't exist yet.

    Id-collision safety: if a file already exists at
    `lessons_dir/<lesson.id>.md` (e.g. two lessons saved the same day
    with a similar-enough title to produce the same slug), a numeric
    suffix (`-2`, `-3`, ...) is appended to the id until a free filename
    is found -- this never silently overwrites a previously saved
    lesson. When the id had to be adjusted, the *written* lesson's own
    frontmatter `id:` field is updated to match (via `dataclasses.replace`,
    which re-runs `Lesson.__post_init__`'s validation harmlessly) so the
    file's own content and its filename never disagree.

    Returns the `Path` actually written to. Callers that need the final
    id should read it back from `path.stem` rather than assume it always
    equals the `lesson.id` passed in, for exactly the collision case
    above.
    """
    lessons_dir = Path(lessons_dir)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    candidate_id = lesson.id
    suffix = 2
    while (lessons_dir / f"{candidate_id}.md").exists():
        candidate_id = f"{lesson.id}-{suffix}"
        suffix += 1
    if candidate_id != lesson.id:
        lesson = replace(lesson, id=candidate_id)

    path = lessons_dir / f"{lesson.id}.md"
    path.write_text(lesson.render(), encoding="utf-8")
    return path


def read_lesson(path: Path | str) -> dict[str, Any]:
    """Read and parse a single lesson `.md` file at `path` (via
    `schema.parse_lesson` -- "the one parser", per Task 3's brief, that
    both `index.build_index` and this function use) into a plain dict of
    every `Lesson` field, plus a `path` key (string) for callers that
    need to locate the file again.
    """
    path = Path(path)
    lesson = parse_lesson(path.read_text(encoding="utf-8"))
    result = asdict(lesson)
    result["path"] = str(path)
    return result


def list_lessons(lessons_dir: Path | str) -> list[dict[str, Any]]:
    """Read every `*.md` file under `lessons_dir` (sorted by filename for
    determinism) and return each as a dict (see `read_lesson`).

    `lessons_dir` not existing yet is not an error -- returns `[]`,
    mirroring `index.build_index`'s identical treatment of a
    not-yet-created lessons directory. A file that fails to parse is
    skipped (logged via `logging.warning`, module logger
    `server.store`) rather than aborting the whole listing -- the same
    per-file error isolation `index.build_index` uses and for the same
    reason: one corrupted `.md` file must not take down `list_lessons`
    for every other valid lesson.
    """
    lessons_dir = Path(lessons_dir)
    if not lessons_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for lesson_path in sorted(lessons_dir.glob("*.md")):
        try:
            results.append(read_lesson(lesson_path))
        except Exception as exc:
            logger.warning(
                "list_lessons: skipping unparseable lesson file %s: %s: %s",
                lesson_path,
                type(exc).__name__,
                exc,
            )
    return results


def _resolve_lesson_path(lesson_id: str, lessons_dir: Path) -> Path:
    """Validate that `lesson_id` is a bare filename component and
    resolve it to `lessons_dir/<lesson_id>.md`. Raises `ValueError` on
    anything else.

    This is the security-relevant choke point closing a Task 5 review
    finding: `Path(lessons_dir) / f"{lesson_id}.md"` alone is NOT safe
    against a caller-supplied `lesson_id`, because pathlib's `/` silently
    *discards the left operand* when the right one is absolute --
    `Path("/tmp/lessons") / "/etc/passwd"` == `Path("/etc/passwd")`, not
    an error and not a path under `/tmp/lessons` -- and relative `..`
    segments inside `lesson_id` (e.g. `"../../../../tmp/evil"`) are
    followed by `Path.exists()`/`.unlink()` without normalization. Since
    `delete_lesson` is reachable directly from `server/main.py`'s
    `prune_lesson` MCP tool with a caller-supplied `id` and zero prior
    validation, either shape let a caller delete an arbitrary
    `.md`-suffixed file anywhere the server process can write, not just
    a file actually under `lessons_dir`.

    Two independent checks, because neither alone is sufficient:

      1. Name-only check: `lesson_id` must be non-empty, must equal
         `Path(lesson_id).name`, and must not be `.` or `..`. The
         equality check alone rules out absolute paths and any embedded
         `/`, but NOT a bare `".."` -- on this pathlib implementation
         `Path("..").name == ".."` (confirmed), i.e. `".."` is its own
         `.name`, so it passes the equality check and needs its own
         explicit rejection alongside `"."`.
      2. Resolved-parent check: after building the candidate path from a
         `lesson_id` that already passed check 1, `.resolve()` it and
         require its parent to be exactly `lessons_dir.resolve()`. This
         is real defense in depth, not redundant with check 1 -- it
         catches anything the string-shape check might miss (e.g. a
         symlink sitting at `lessons_dir/<id>.md` that points outside
         `lessons_dir`) rather than trusting the id's shape alone.

    Only `delete_lesson` calls this today. `write_lesson` never needs
    it: the `Lesson.id` it writes from is built internally by
    `server/main.py`'s `save_lesson` via `make_lesson_id`/`slugify`
    (this module, above), which only ever emits `[a-z0-9]` tokens
    hyphen-joined with a `YYYY-MM-DD` date prefix -- never raw external
    input, and structurally incapable of containing `/` or `..`.
    `read_lesson` never needs it either: every call site (`list_lessons`
    below, and `server/main.py`'s `search_lessons`) passes an already-
    resolved `Path` obtained by globbing `lessons_dir` or reading it back
    out of the index, never a bare id string reconstructed from caller
    input.
    """
    lessons_dir = Path(lessons_dir)
    if not lesson_id or lesson_id in (".", "..") or lesson_id != Path(lesson_id).name:
        raise ValueError(
            f"invalid lesson id {lesson_id!r}: must be a bare filename "
            "component (no path separators, not absolute, not '.' or '..')"
        )

    candidate = lessons_dir / f"{lesson_id}.md"
    if candidate.resolve().parent != lessons_dir.resolve():
        raise ValueError(
            f"invalid lesson id {lesson_id!r}: resolves outside lessons_dir"
        )
    return candidate


def delete_lesson(lesson_id: str, lessons_dir: Path | str) -> bool:
    """Delete `lessons_dir/<lesson_id>.md`, if it exists.

    Returns `True` if a file was removed, `False` if no file matched
    `lesson_id` -- including when `lessons_dir` itself doesn't exist yet
    (mirrors `list_lessons`'s treatment of a not-yet-created lessons
    directory: not an error, just nothing to do). A missing match is a
    normal, expected outcome (pruning an id that's already gone, or was
    never saved) for the caller (`server/main.py`'s `prune_lesson` tool)
    to surface as `{"deleted": false}`, not something this function
    raises on.

    Raises `ValueError` if `lesson_id` is not a bare filename component
    (see `_resolve_lesson_path`) -- e.g. an absolute path, a relative
    path containing `..`, or anything else that would let the
    constructed path escape `lessons_dir`. This is deliberately a raise,
    not a silent `False`: every id this module itself ever produces
    (`make_lesson_id`/`slugify`, above) is already a safe bare filename,
    so a `lesson_id` that fails this check cannot arise from any normal
    internal flow -- it can only arrive via a caller invoking the
    `prune_lesson` MCP tool directly with a hand-crafted malicious id.
    That is a fundamentally different situation from "no lesson has this
    id" (a normal, expected `False`), and collapsing it into `False`
    would mask a malformed/hostile-input bug as an unremarkable no-op.
    """
    lessons_dir = Path(lessons_dir)
    path = _resolve_lesson_path(lesson_id, lessons_dir)
    if not path.exists():
        return False
    path.unlink()
    return True
```

## server/main.py
```
#!/usr/bin/env python3
"""Hindsight MCP server.

Exposes the `hindsight` tool surface (`search_lessons`, `save_lesson`,
`list_lessons`, `prune_lesson`) over stdio using the official MCP Python
SDK's FastMCP helper.

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


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## server/tests/test_store.py
```
"""Tests for server/store.py: lesson file I/O (write/read/list) plus the
`<id>.md` filename/slug convention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import store
from schema import Lesson


def _make_lesson(**overrides) -> Lesson:
    fields = dict(
        id="2026-01-01-placeholder",
        title="A test lesson",
        domain=["python"],
        error_signature="ValueError: boom",
        created_at="2026-01-01T00:00:00Z",
        confidence="confirmed",
        symptom="Something broke.",
        failed_approaches=["Tried X"],
        root_cause="Y was the cause.",
        fix="Did Z.",
        tags=["python", "valueerror"],
    )
    fields.update(overrides)
    return Lesson(**fields)


# --- slugify / make_lesson_id -----------------------------------------------


def test_slugify_lowercases_and_hyphenates():
    slug = store.slugify("FastMCP Tool Registration Crashes")
    assert slug == slug.lower()
    assert " " not in slug
    assert slug.startswith("fastmcp-tool-registration-crashes")


def test_slugify_drops_common_filler_words():
    slug = store.slugify("Server crashes with stale pydantic version")
    words = slug.split("-")
    assert "with" not in words


def test_slugify_caps_word_count():
    slug = store.slugify("one two three four five six seven eight nine")
    assert len(slug.split("-")) <= store._MAX_SLUG_WORDS


def test_slugify_never_returns_empty_string():
    assert store.slugify("!!!") != ""
    assert store.slugify("the of and") != ""


def test_make_lesson_id_uses_date_portion_of_created_at_and_slug_of_title():
    lesson_id = store.make_lesson_id(
        "React useEffect infinite loop", "2026-06-02T09:30:00Z"
    )
    assert lesson_id.startswith("2026-06-02-")
    assert "react" in lesson_id
    assert "useeffect" in lesson_id


# --- write_lesson ------------------------------------------------------------


def test_write_lesson_creates_lessons_dir_and_file(tmp_path: Path):
    lessons_dir = tmp_path / "does-not-exist-yet" / "lessons"
    lesson = _make_lesson()

    path = store.write_lesson(lesson, lessons_dir)

    assert path == lessons_dir / f"{lesson.id}.md"
    assert path.read_text(encoding="utf-8") == lesson.render()


def test_write_lesson_avoids_overwriting_on_id_collision(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    first = _make_lesson(id="2026-01-01-dup", symptom="first lesson content")
    second = _make_lesson(id="2026-01-01-dup", symptom="second lesson content")

    first_path = store.write_lesson(first, lessons_dir)
    second_path = store.write_lesson(second, lessons_dir)

    assert first_path != second_path
    assert first_path.read_text(encoding="utf-8") == first.render()

    # The second lesson's own frontmatter id was adjusted to match its
    # actual (disambiguated) filename -- content and filename never
    # disagree, and the first lesson's file was never overwritten.
    second_contents = second_path.read_text(encoding="utf-8")
    assert "second lesson content" in second_contents
    assert second_path.stem != "2026-01-01-dup"
    assert second_path.stem in second_contents


def test_write_lesson_third_collision_gets_next_free_suffix(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    for i in range(3):
        path = store.write_lesson(
            _make_lesson(id="2026-01-01-dup", symptom=f"lesson {i}"), lessons_dir
        )
        assert path.exists()
    ids = sorted(p.stem for p in lessons_dir.glob("*.md"))
    assert ids == ["2026-01-01-dup", "2026-01-01-dup-2", "2026-01-01-dup-3"]


# --- read_lesson / list_lessons ----------------------------------------------


def test_read_lesson_round_trips_write_lesson(tmp_path: Path):
    lesson = _make_lesson()
    path = store.write_lesson(lesson, tmp_path / "lessons")

    result = store.read_lesson(path)

    assert result["id"] == lesson.id
    assert result["title"] == lesson.title
    assert result["domain"] == lesson.domain
    assert result["fix"] == lesson.fix
    assert result["path"] == str(path)


def test_list_lessons_on_missing_dir_returns_empty_list(tmp_path: Path):
    assert store.list_lessons(tmp_path / "nope") == []


def test_list_lessons_returns_every_saved_lesson_sorted(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    store.write_lesson(_make_lesson(id="2026-01-02-second", title="Second"), lessons_dir)
    store.write_lesson(_make_lesson(id="2026-01-01-first", title="First"), lessons_dir)

    listing = store.list_lessons(lessons_dir)

    assert [entry["id"] for entry in listing] == [
        "2026-01-01-first",
        "2026-01-02-second",
    ]


def test_list_lessons_skips_malformed_file_and_returns_the_rest(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    store.write_lesson(_make_lesson(id="2026-01-01-ok", title="OK lesson"), lessons_dir)
    (lessons_dir / "2026-01-02-broken.md").write_text(
        '---\nid: "unterminated\ntitle: "oops"\n---\n\n## Symptom\n\nx\n',
        encoding="utf-8",
    )

    listing = store.list_lessons(lessons_dir)

    assert len(listing) == 1
    assert listing[0]["id"] == "2026-01-01-ok"


# --- delete_lesson ------------------------------------------------------------


def test_delete_lesson_removes_existing_file_and_returns_true(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    path = store.write_lesson(_make_lesson(id="2026-01-01-to-delete"), lessons_dir)
    assert path.exists()

    result = store.delete_lesson("2026-01-01-to-delete", lessons_dir)

    assert result is True
    assert not path.exists()


def test_delete_lesson_leaves_other_files_alone(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    keep_path = store.write_lesson(_make_lesson(id="2026-01-01-keep"), lessons_dir)
    store.write_lesson(_make_lesson(id="2026-01-01-remove"), lessons_dir)

    result = store.delete_lesson("2026-01-01-remove", lessons_dir)

    assert result is True
    assert keep_path.exists()
    assert [p.stem for p in lessons_dir.glob("*.md")] == ["2026-01-01-keep"]


def test_delete_lesson_returns_false_when_no_matching_file(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    store.write_lesson(_make_lesson(id="2026-01-01-unrelated"), lessons_dir)

    result = store.delete_lesson("2026-01-01-does-not-exist", lessons_dir)

    assert result is False
    assert (lessons_dir / "2026-01-01-unrelated.md").exists()


def test_delete_lesson_returns_false_on_missing_lessons_dir(tmp_path: Path):
    result = store.delete_lesson("anything", tmp_path / "does-not-exist")
    assert result is False


# --- delete_lesson: path-traversal rejection (security regression, Task 5 review) ---
#
# `Path(lessons_dir) / f"{lesson_id}.md"` alone is not safe against a
# caller-supplied `lesson_id`: pathlib's `/` discards the left operand
# entirely when the right one is absolute, and `..` segments are followed
# by `.exists()`/`.unlink()` without normalization. Each test below plants
# a real "victim" file *outside* `lessons_dir`, in a scratch location, and
# asserts it survives the call untouched -- not just that the call fails.


def test_delete_lesson_rejects_absolute_path_id_and_leaves_victim_file_alone(
    tmp_path: Path,
):
    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        store.delete_lesson(str(victim), lessons_dir)

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_delete_lesson_rejects_relative_traversal_id_and_leaves_victim_file_alone(
    tmp_path: Path,
):
    # lessons_dir nested a few levels down so "../../../../..." from it
    # can plausibly reach the scratch marker file placed at tmp_path.
    lessons_dir = tmp_path / "project" / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True)
    victim = tmp_path / "some-marker-file.md"
    victim.write_text("do not delete me")

    traversal_id = "../../../../some-marker-file"
    with pytest.raises(ValueError):
        store.delete_lesson(traversal_id, lessons_dir)

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_delete_lesson_rejects_id_with_embedded_slash_and_leaves_victim_file_alone(
    tmp_path: Path,
):
    lessons_dir = tmp_path / "lessons"
    subdir = lessons_dir / "subdir"
    subdir.mkdir(parents=True)
    victim = subdir / "thing.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        store.delete_lesson("subdir/thing", lessons_dir)

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_delete_lesson_rejects_bare_dot_dot_id(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()

    with pytest.raises(ValueError):
        store.delete_lesson("..", lessons_dir)


def test_delete_lesson_rejects_bare_dot_id(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()

    with pytest.raises(ValueError):
        store.delete_lesson(".", lessons_dir)


def test_delete_lesson_rejects_empty_id(tmp_path: Path):
    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()

    with pytest.raises(ValueError):
        store.delete_lesson("", lessons_dir)


def test_delete_lesson_rejects_symlink_escaping_lessons_dir(tmp_path: Path):
    # Exercises the second (resolved-parent) defense-in-depth layer
    # specifically: "escape" is itself a perfectly well-formed bare id
    # (no slashes, not "." or ".."), so it passes the name-only check.
    # Only the resolve()-and-compare-parent check catches this.
    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    victim = tmp_path / "victim-outside.md"
    victim.write_text("do not delete me")
    (lessons_dir / "escape.md").symlink_to(victim)

    with pytest.raises(ValueError):
        store.delete_lesson("escape", lessons_dir)

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_delete_lesson_well_formed_id_still_works_after_traversal_fix(tmp_path: Path):
    # Regression guard: the traversal fix must not break the normal,
    # legitimate case -- a plain well-formed id still deletes exactly its
    # own file and returns True.
    lessons_dir = tmp_path / "lessons"
    path = store.write_lesson(_make_lesson(id="2026-01-01-well-formed"), lessons_dir)
    assert path.exists()

    result = store.delete_lesson("2026-01-01-well-formed", lessons_dir)

    assert result is True
    assert not path.exists()
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

import subprocess
from pathlib import Path

import pytest

import main

FAKE_AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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
```
