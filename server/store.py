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
