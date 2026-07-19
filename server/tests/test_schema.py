"""Tests for server/schema.py: Lesson dataclass + render().

Round-trips a lesson through render() and asserts every required
frontmatter field and body section is present and correctly formatted,
per Task 2's brief.
"""

from __future__ import annotations

import re

import pytest
import yaml
from schema import (
    BODY_SECTION_HEADERS,
    CONFIDENCE_VALUES,
    REQUIRED_FRONTMATTER_FIELDS,
    Lesson,
    parse_lesson,
)


def make_lesson(**overrides) -> Lesson:
    defaults = dict(
        id="2026-07-18-fastmcp-pydantic-floor",
        title="FastMCP tool registration crashes with stale pydantic",
        domain=["python", "mcp", "fastmcp"],
        error_signature="PydanticUserError: A non-annotated attribute was detected",
        created_at="2026-07-18T12:00:00Z",
        confidence="confirmed",
        symptom="Server crashes at import time when registering any tool "
        "with a bare return type annotation.",
        failed_approaches=[
            "Upgrading only the `mcp` package without checking pydantic's floor",
            "Adding explicit Pydantic BaseModel wrappers to every tool return type",
        ],
        root_cause="Global python3's pydantic (2.9.2) predates the floor "
        "mcp==1.27.0 requires (>=2.11.0); create_model() with a bare "
        "annotation is rejected by the old version.",
        fix="Run the server via `uv run --with-requirements "
        "server/requirements.txt server/main.py` so a compliant pydantic "
        "is resolved in an ephemeral environment.",
        tags=["pydantic", "fastmcp", "dependency-conflict"],
    )
    defaults.update(overrides)
    return Lesson(**defaults)


def test_render_contains_frontmatter_delimiters():
    doc = make_lesson().render()
    assert doc.startswith("---\n")
    # Exactly two `---` delimiter lines: open and close of frontmatter.
    lines = doc.split("\n")
    delimiter_lines = [i for i, line in enumerate(lines) if line == "---"]
    assert len(delimiter_lines) == 2


def test_render_frontmatter_block_has_all_required_fields():
    doc = make_lesson().render()
    lines = doc.split("\n")
    delimiter_idx = [i for i, line in enumerate(lines) if line == "---"]
    frontmatter_lines = lines[delimiter_idx[0] + 1 : delimiter_idx[1]]
    frontmatter_text = "\n".join(frontmatter_lines)

    for required_field in REQUIRED_FRONTMATTER_FIELDS:
        # Each required key appears as a top-level `key:` line.
        assert re.search(
            rf"^{re.escape(required_field)}:", frontmatter_text, re.MULTILINE
        ), f"missing frontmatter field {required_field!r} in:\n{frontmatter_text}"


def test_render_frontmatter_values_are_correct():
    lesson = make_lesson()
    doc = lesson.render()

    assert f'id: "{lesson.id}"' in doc
    assert f'title: "{lesson.title}"' in doc
    assert f'error_signature: "{lesson.error_signature}"' in doc
    assert f'created_at: "{lesson.created_at}"' in doc
    assert f"confidence: {lesson.confidence}" in doc
    for d in lesson.domain:
        assert f'- "{d}"' in doc


def test_render_body_sections_present_and_in_order():
    doc = make_lesson().render()
    positions = [doc.index(header) for header in BODY_SECTION_HEADERS]
    # All headers present...
    assert all(p >= 0 for p in positions)
    # ...and in the exact order specified by Global Constraints.
    assert positions == sorted(positions)


def test_render_body_content_present():
    lesson = make_lesson()
    doc = lesson.render()

    assert lesson.symptom in doc
    assert lesson.root_cause in doc
    assert lesson.fix in doc
    for approach in lesson.failed_approaches:
        assert f"- {approach}" in doc
    for tag in lesson.tags:
        assert f"- {tag}" in doc


def test_render_handles_empty_optional_lists_without_dropping_sections():
    lesson = make_lesson(failed_approaches=[], tags=[])
    doc = lesson.render()
    for header in BODY_SECTION_HEADERS:
        assert header in doc
    # Sections still render something (not blank / missing) even with no items.
    assert "_(none recorded)_" in doc


def test_confidence_must_be_confirmed_or_probable():
    assert CONFIDENCE_VALUES == ("confirmed", "probable")
    with pytest.raises(ValueError):
        make_lesson(confidence="maybe")


def test_confidence_probable_is_accepted():
    doc = make_lesson(confidence="probable").render()
    assert "confidence: probable" in doc


def test_domain_must_be_non_empty():
    with pytest.raises(ValueError):
        make_lesson(domain=[])


def test_required_scalar_fields_cannot_be_empty():
    with pytest.raises(ValueError):
        make_lesson(id="")
    with pytest.raises(ValueError):
        make_lesson(title="")
    with pytest.raises(ValueError):
        make_lesson(error_signature="")
    with pytest.raises(ValueError):
        make_lesson(created_at="")


def test_match_text_built_from_title_error_signature_domain_tags():
    lesson = make_lesson()
    match_text = lesson.match_text()

    assert lesson.title in match_text
    assert lesson.error_signature in match_text
    for d in lesson.domain:
        assert d in match_text
    for tag in lesson.tags:
        assert tag in match_text

    # Never raw stack traces / body prose in the match text.
    assert lesson.symptom not in match_text
    assert lesson.root_cause not in match_text
    assert lesson.fix not in match_text


def test_frontmatter_scalar_with_special_characters_is_safely_quoted():
    lesson = make_lesson(
        title='Error: "unexpected" token near foo: bar',
        error_signature="KeyError: 'config:timeout'",
    )
    doc = lesson.render()
    # Should not produce unescaped raw quotes inside the quoted scalar
    # that would break YAML parsing (naive check: escaped quotes present).
    assert '\\"unexpected\\"' in doc
    assert "KeyError: 'config:timeout'" in doc


def _parse_frontmatter(doc: str) -> dict:
    """Extract the YAML frontmatter block from a rendered document and
    parse it with a real YAML parser (PyYAML), for round-trip tests.
    """
    lines = doc.split("\n")
    delimiter_idx = [i for i, line in enumerate(lines) if line == "---"]
    frontmatter_text = "\n".join(lines[delimiter_idx[0] + 1 : delimiter_idx[1]])
    return yaml.safe_load(frontmatter_text)


def test_title_with_embedded_newline_round_trips_through_yaml_safe_load():
    # Regression test: a raw (unescaped) newline inside a hand-emitted
    # YAML double-quoted scalar is folded to a space by YAML's
    # line-folding rule on load, silently changing the string. render()
    # must escape embedded newlines so yaml.safe_load() recovers the
    # exact original title, not a mangled version.
    title = "Line one\nLine two"
    lesson = make_lesson(title=title)
    doc = lesson.render()
    parsed = _parse_frontmatter(doc)
    assert parsed["title"] == title


def test_error_signature_with_embedded_newline_round_trips_through_yaml_safe_load():
    error_signature = "Traceback:\n  File x.py, line 1\nValueError: boom"
    lesson = make_lesson(error_signature=error_signature)
    doc = lesson.render()
    parsed = _parse_frontmatter(doc)
    assert parsed["error_signature"] == error_signature


def test_title_with_carriage_return_and_tab_round_trips_through_yaml_safe_load():
    # Carriage returns are folded exactly like newlines by YAML; tabs
    # aren't folded but should still be escaped/preserved exactly.
    title = "col1\tcol2\r\nnext row"
    lesson = make_lesson(title=title)
    doc = lesson.render()
    parsed = _parse_frontmatter(doc)
    assert parsed["title"] == title


def test_domain_item_with_embedded_newline_round_trips_through_yaml_safe_load():
    # domain is rendered via _yaml_list -> _yaml_quote for each item;
    # confirm the same escaping applies to list scalars, not just the
    # top-level id/title/error_signature/created_at scalars.
    lesson = make_lesson(domain=["python", "line1\nline2"])
    doc = lesson.render()
    parsed = _parse_frontmatter(doc)
    assert parsed["domain"] == ["python", "line1\nline2"]


# --- parse_lesson(): round-trip tests (Task 3) ------------------------------
#
# Task 3's brief: "Round-trip test: parse_lesson(lesson.render()) ==
# lesson for a handful of fixture lessons including one with the
# escaped-character edge cases Task 2's fix handled (embedded newline in
# title, etc)."


def test_parse_lesson_round_trips_a_typical_lesson():
    lesson = make_lesson()
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_probable_confidence_and_multiple_domains():
    lesson = make_lesson(
        confidence="probable",
        domain=["go", "kubernetes", "networking"],
        tags=["timeout", "grpc"],
    )
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_empty_failed_approaches_and_tags():
    # render() emits the "_(none recorded)_" sentinel for these when
    # empty; parse_lesson must invert that back to [], not [""] or
    # ["_(none recorded)_"].
    lesson = make_lesson(failed_approaches=[], tags=[])
    parsed = parse_lesson(lesson.render())
    assert parsed == lesson
    assert parsed.failed_approaches == []
    assert parsed.tags == []


def test_parse_lesson_round_trips_single_item_lists():
    lesson = make_lesson(failed_approaches=["Only one thing was tried"], tags=["single-tag"])
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_embedded_newline_in_title():
    # The exact escaped-character edge case Task 2's fix handled: a raw
    # newline inside a hand-emitted YAML double-quoted scalar is folded
    # to a space by YAML's line-folding rule unless _yaml_quote() escapes
    # it as a literal "\n" -- parse_lesson (via yaml.safe_load) must
    # recover the original multi-line title exactly.
    lesson = make_lesson(title="Line one\nLine two")
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_embedded_cr_tab_and_quotes():
    lesson = make_lesson(
        title="col1\tcol2\r\nnext row",
        error_signature='KeyError: "config:timeout" near \\escaped\\ text',
    )
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_domain_item_with_embedded_newline():
    lesson = make_lesson(domain=["python", "line1\nline2"])
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_control_characters_in_error_signature():
    # NUL, DEL, and a generic C0 control char (\x01) -- the other branch
    # of _yaml_quote()'s escaping (the \xHH fallback) that the plain
    # named-escape cases above don't exercise.
    lesson = make_lesson(error_signature="boom\x00here\x7fand\x01there")
    assert parse_lesson(lesson.render()) == lesson


def test_parse_lesson_round_trips_root_cause_containing_header_like_substring():
    # Regression test (Task 3 review fix): _parse_body_sections must
    # anchor header matching to a full line (^header$), not do a plain
    # substring search. A body section's free text that merely *contains*
    # another section's exact header string as part of a sentence (not on
    # its own line) must not be mistaken for the real header -- a naive
    # `str.find()` substring search silently truncates root_cause at the
    # "## Fix" occurrence here and bleeds the rest into `fix`, with no
    # exception raised.
    lesson = make_lesson(
        root_cause='The runbook references the "## Fix" section below '
        "when triaging this alert, but the actual root cause is a stale "
        "cache entry that was never invalidated after the schema change.",
    )
    doc = lesson.render()
    parsed = parse_lesson(doc)
    assert parsed == lesson
    assert parsed.root_cause == lesson.root_cause
    assert parsed.fix == lesson.fix


def test_parse_lesson_round_trips_symptom_containing_header_like_substring():
    # Same regression, different header/section: a symptom that mentions
    # "## Root cause" mid-sentence must not truncate the Symptom section.
    lesson = make_lesson(
        symptom="Users report a crash; see the \"## Root cause\" write-up "
        "for the on-call engineer's full timeline of the incident.",
    )
    doc = lesson.render()
    parsed = parse_lesson(doc)
    assert parsed == lesson
    assert parsed.symptom == lesson.symptom


def test_parse_lesson_raises_on_missing_frontmatter():
    with pytest.raises(ValueError):
        parse_lesson("## Symptom\n\nno frontmatter block here\n")


def test_parse_lesson_raises_on_missing_body_section():
    lesson = make_lesson()
    doc = lesson.render()
    truncated = doc.split("## Fix")[0]  # drop Fix and Tags sections
    with pytest.raises(ValueError):
        parse_lesson(truncated)
