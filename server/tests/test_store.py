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
