"""Lesson schema: the data model for a saved debugging lesson.

Defines the `Lesson` dataclass and its `render()` method, which produces
a markdown document with YAML frontmatter matching the shape of
`templates/LESSON_TEMPLATE.md` at the repo root.

Field list matches the plan's Global Constraints verbatim:

    Lesson schema: YAML frontmatter (`id`, `title`, `domain[]`,
    `error_signature`, `created_at`, `confidence: confirmed|probable`) +
    markdown body sections `## Symptom`, `## Approaches that FAILED (do
    not repeat)`, `## Root cause`, `## Fix`, `## Tags for retrieval`.
    Match text built from `title` + `error_signature` + `domain` +
    retrieval tags — never raw stack traces with file paths/line
    numbers.

No MCP dependency. Pure logic, unit-testable standalone (see
server/tests/test_schema.py). `server/main.py` is not touched by this
module or by this task.

Also defines `parse_lesson()`, the inverse of `Lesson.render()` (added in
Task 3, gap found after Task 2 landed — Task 3's `index.build_index` and
Task 4's `store.read_lesson` both need to turn a saved lesson `.md` file
back into a `Lesson`). `parse_lesson()` uses PyYAML (`yaml.safe_load`) to
parse the frontmatter block, even though `render()` above hand-emits it:
emission is a small, fully-controlled, deterministic shape (six known
scalar/list-of-scalar keys) so hand-rolling it avoided a dependency this
module otherwise wouldn't need; *parsing* has to handle arbitrary
double-quoted-scalar YAML escaping correctly (the exact
backslash/quote/newline/control-char rules `_yaml_quote()` documents
above) and reimplementing a YAML unescaper by hand would just be a worse,
untested copy of what PyYAML already does correctly — so parsing takes
the dependency PyYAML gives for free instead. (PyYAML was already an
indirect dependency of this project's `mcp` package and used directly by
this module's own tests since Task 2; Task 3 adds it as a direct,
explicitly pinned dependency in `server/requirements.txt` since
production code — not just tests — now imports it.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import yaml

CONFIDENCE_VALUES = ("confirmed", "probable")

# Frontmatter keys, in the exact order they are emitted by render().
REQUIRED_FRONTMATTER_FIELDS = (
    "id",
    "title",
    "domain",
    "error_signature",
    "created_at",
    "confidence",
)

# Body section headers, in the exact order they are emitted by render().
BODY_SECTION_HEADERS = (
    "## Symptom",
    "## Approaches that FAILED (do not repeat)",
    "## Root cause",
    "## Fix",
    "## Tags for retrieval",
)


# Characters with a short, named YAML double-quoted-scalar escape.
# Newline/carriage-return matter most: a *raw* (unescaped) "\n" or "\r"
# inside a double-quoted scalar is not rejected by YAML — it parses, but
# the YAML line-folding rule silently collapses it (and any surrounding
# line breaks) to a single space, changing the string's content on
# round-trip through a real parser. Escaping them as the two-character
# sequences below keeps them literal.
_YAML_NAMED_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\0": "\\0",
}

# NEL (U+0085) is, per the YAML spec, a line-break character just like
# \n/\r — a raw NEL folds to a space exactly like a raw \n does, so it
# needs the same treatment. It has no short named escape, so it goes
# through the `\xHH` fallback below alongside the other C0 controls.
_YAML_NEL = "\x85"


def _yaml_quote(value: str) -> str:
    """Double-quote a scalar for safe inclusion in hand-emitted YAML.

    Lesson text (titles, error signatures) is free-form and may contain
    any character a user's title or error message can contain: colons,
    `#`, quotes, embedded newlines, or other control characters. This
    escapes, in a double-quoted scalar, everything that isn't safe to
    emit literally: backslashes and double quotes (so the quoting itself
    stays well-formed), newline/carriage-return/NEL (which YAML's
    line-folding rule would otherwise silently collapse to a space on
    reload — see `_YAML_NAMED_ESCAPES`/`_YAML_NEL`), and every other C0
    control character plus DEL (0x00-0x1F, 0x7F) via `\\xHH`, since a raw
    control character other than tab is rejected outright by a
    spec-compliant YAML parser. Verified (see
    server/tests/test_schema.py) to round-trip byte-for-byte through
    PyYAML's `yaml.safe_load` for arbitrary `str` input, including
    embedded newlines/CR/tabs/NUL/DEL/NEL. Frontmatter here is flat (six
    scalar/list-of-scalar fields) so hand-emitting it deterministically
    avoids taking a PyYAML dependency this module otherwise wouldn't need
    (PyYAML is only used by tests, to verify against a real parser).
    """
    chars = []
    for ch in value:
        if ch in _YAML_NAMED_ESCAPES:
            chars.append(_YAML_NAMED_ESCAPES[ch])
        elif ch == _YAML_NEL or ord(ch) < 0x20 or ord(ch) == 0x7F:
            chars.append(f"\\x{ord(ch):02x}")
        else:
            chars.append(ch)
    return f'"{"".join(chars)}"'


def _yaml_list(items: list[str]) -> str:
    if not items:
        return " []"
    return "\n" + "\n".join(f"  - {_yaml_quote(item)}" for item in items)


@dataclass
class Lesson:
    """A single debugging lesson.

    Frontmatter fields: id, title, domain, error_signature, created_at,
    confidence.
    Body fields: symptom, failed_approaches, root_cause, fix, tags (the
    "Tags for retrieval" section).
    """

    id: str
    title: str
    domain: list[str]
    error_signature: str
    created_at: str
    confidence: Literal["confirmed", "probable"]
    symptom: str
    failed_approaches: list[str]
    root_cause: str
    fix: str
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_VALUES:
            raise ValueError(
                f"confidence must be one of {CONFIDENCE_VALUES!r}, "
                f"got {self.confidence!r}"
            )
        if not self.id:
            raise ValueError("id is required")
        if not self.title:
            raise ValueError("title is required")
        if not self.domain:
            raise ValueError("domain must be a non-empty list")
        if not self.error_signature:
            raise ValueError("error_signature is required")
        if not self.created_at:
            raise ValueError("created_at is required")

    def render(self) -> str:
        """Render this lesson as a markdown document with YAML
        frontmatter, matching the shape of templates/LESSON_TEMPLATE.md.
        """
        frontmatter = (
            "---\n"
            f"id: {_yaml_quote(self.id)}\n"
            f"title: {_yaml_quote(self.title)}\n"
            f"domain:{_yaml_list(self.domain)}\n"
            f"error_signature: {_yaml_quote(self.error_signature)}\n"
            f"created_at: {_yaml_quote(self.created_at)}\n"
            f"confidence: {self.confidence}\n"
            "---\n"
        )

        failed_approaches_block = (
            "\n".join(f"- {item}" for item in self.failed_approaches)
            if self.failed_approaches
            else "_(none recorded)_"
        )
        tags_block = (
            "\n".join(f"- {item}" for item in self.tags)
            if self.tags
            else "_(none recorded)_"
        )

        body = (
            "\n"
            "## Symptom\n\n"
            f"{self.symptom}\n\n"
            "## Approaches that FAILED (do not repeat)\n\n"
            f"{failed_approaches_block}\n\n"
            "## Root cause\n\n"
            f"{self.root_cause}\n\n"
            "## Fix\n\n"
            f"{self.fix}\n\n"
            "## Tags for retrieval\n\n"
            f"{tags_block}\n"
        )

        return frontmatter + body

    def match_text(self) -> str:
        """Text used for embedding/similarity search (Task 3), per
        Global Constraints: "Match text built from title +
        error_signature + domain + retrieval tags — never raw stack
        traces with file paths/line numbers."
        """
        parts = [self.title, self.error_signature, *self.domain, *self.tags]
        return " ".join(p for p in parts if p)


# --- parse_lesson(): the inverse of render() -------------------------------

# Matches the leading "---\n...\n---\n" frontmatter block render() always
# emits first. DOTALL so "." spans the embedded newlines a quoted scalar
# may legitimately contain (those are escaped as literal "\n" two-char
# sequences by _yaml_quote(), never as a raw newline, so they don't
# prematurely end this match — see _yaml_quote()'s docstring above).
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)

# Sentinel render() emits for an empty failed_approaches/tags list.
_EMPTY_LIST_SENTINEL = "_(none recorded)_"


def _parse_body_sections(body_text: str) -> dict[str, str]:
    """Split render()'s body text into {header: content} using the exact
    header set/order in BODY_SECTION_HEADERS.

    Each section's content is whatever sits between one header and the
    next (or end-of-text for the last section), with surrounding blank
    lines stripped. Header matching is anchored to a full line (`^header$`
    with `re.MULTILINE`), not a plain substring search: render() always
    emits each header occupying its own line, so a real header is always
    line-anchored. Anchoring this way means a body section's own free
    text that merely *contains* another section's exact header string as
    part of a sentence (e.g. "...references the \"## Fix\" section
    below...") is correctly left alone — a bare `str.find()` substring
    search would misfire on that and silently truncate the section (see
    the regression tests for this exact scenario in
    server/tests/test_schema.py). A body section's free text that
    contains another header string *as a standalone line by itself* would
    still be ambiguous with a real header and is not handled here — real
    lesson prose doesn't emit bare `## Something` lines outside of
    render()'s own headers.
    """
    positions: list[tuple[int, str, int]] = []
    for header in BODY_SECTION_HEADERS:
        match = re.search(rf"^{re.escape(header)}$", body_text, re.MULTILINE)
        if match is None:
            raise ValueError(
                f"lesson body is missing the required section header {header!r}"
            )
        positions.append((match.start(), header, match.end()))

    positions.sort(key=lambda triple: triple[0])
    if [header for _, header, _ in positions] != list(BODY_SECTION_HEADERS):
        raise ValueError(
            "lesson body section headers are present but out of order; "
            f"expected {list(BODY_SECTION_HEADERS)}"
        )

    sections: dict[str, str] = {}
    for i, (_, header, end) in enumerate(positions):
        content_start = end
        content_end = positions[i + 1][0] if i + 1 < len(positions) else len(body_text)
        sections[header] = body_text[content_start:content_end].strip("\n")
    return sections


def _parse_list_section(content: str, *, section_name: str) -> list[str]:
    """Invert render()'s `"\\n".join(f"- {item}" for item in items)` (or
    the `_(none recorded)_` sentinel for an empty list).
    """
    content = content.strip("\n")
    if content.strip() == _EMPTY_LIST_SENTINEL:
        return []
    items = []
    for line in content.split("\n"):
        if not line.startswith("- "):
            raise ValueError(
                f"malformed {section_name!r} list line (expected '- ' prefix): "
                f"{line!r}"
            )
        items.append(line[2:])
    return items


def parse_lesson(text: str) -> Lesson:
    """Parse a rendered lesson document (as produced by `Lesson.render()`)
    back into a `Lesson`. The inverse of `render()`.

    Frontmatter is parsed with `yaml.safe_load` (a real YAML parser, not
    a hand-rolled unescaper — see module docstring for why) so it
    correctly recovers every character `_yaml_quote()` can escape,
    including embedded newlines/CR/tabs/control characters in `title`,
    `error_signature`, `created_at`, `id`, or any `domain` item. Body
    sections are parsed positionally (see `_parse_body_sections`).

    Raises `ValueError` if the frontmatter block or any required section
    is missing/malformed. Round-trips exactly for any `Lesson` produced
    via its own constructor and rendered via `render()`:
    `parse_lesson(lesson.render()) == lesson`.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(
            "lesson text does not start with a '---'-delimited YAML "
            "frontmatter block"
        )
    frontmatter_text = match.group(1)
    body_text = text[match.end() :]

    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise ValueError("lesson frontmatter did not parse to a YAML mapping")

    missing = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in frontmatter]
    if missing:
        raise ValueError(f"lesson frontmatter missing required field(s): {missing}")

    sections = _parse_body_sections(body_text)

    return Lesson(
        id=str(frontmatter["id"]),
        title=str(frontmatter["title"]),
        domain=list(frontmatter["domain"]),
        error_signature=str(frontmatter["error_signature"]),
        created_at=str(frontmatter["created_at"]),
        confidence=frontmatter["confidence"],
        symptom=sections["## Symptom"],
        failed_approaches=_parse_list_section(
            sections["## Approaches that FAILED (do not repeat)"],
            section_name="## Approaches that FAILED (do not repeat)",
        ),
        root_cause=sections["## Root cause"],
        fix=sections["## Fix"],
        tags=_parse_list_section(
            sections["## Tags for retrieval"], section_name="## Tags for retrieval"
        ),
    )
