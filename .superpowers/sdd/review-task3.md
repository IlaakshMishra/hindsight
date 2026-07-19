# Review package: Task 3 (no git — full file dump)

## Files
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
/Users/ilaakshmishra/Documents/hindsight/.claude/settings.local.json
/Users/ilaakshmishra/Documents/hindsight/.gitignore
/Users/ilaakshmishra/Documents/hindsight/.mcp.json
/Users/ilaakshmishra/Documents/hindsight/README.md
/Users/ilaakshmishra/Documents/hindsight/server/index.py
/Users/ilaakshmishra/Documents/hindsight/server/main.py
/Users/ilaakshmishra/Documents/hindsight/server/requirements.txt
/Users/ilaakshmishra/Documents/hindsight/server/schema.py
/Users/ilaakshmishra/Documents/hindsight/server/scrub.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/conftest.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-04-01-postgres-pool-exhausted.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-05-14-docker-build-oom-killed.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-06-02-react-useeffect-infinite-loop.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-07-18-fastmcp-pydantic-floor.md
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_index.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_schema.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_scrub.py
/Users/ilaakshmishra/Documents/hindsight/templates/LESSON_TEMPLATE.md
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
containing `{model, dim, records: [{id, path, vector}, ...]}`. Every
field in a record is either present in, or trivially recomputed from, the
lesson `.md` files themselves (`id` and `vector` come from parsing +
embedding a lesson's `match_text()`; `path` is just the file's location)
— nothing lives only in the index. `build_index` always does a full
rebuild by re-reading every `.md` file in `lessons_dir` from scratch, so
a corrupted or deleted `index.json` is always fully recoverable by
calling `build_index` again; the cache is never treated as authoritative.

No MCP dependency. Pure logic (network access is needed only once, on
first use, for fastembed to download and locally cache the ONNX model
weights — after that, embedding is fully local). `server/main.py` is not
touched by this module or by this task.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from fastembed import TextEmbedding

from schema import parse_lesson

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

    Returns the path to the written index file.
    """
    lessons_dir = Path(lessons_dir)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    if lessons_dir.exists():
        for lesson_path in sorted(lessons_dir.glob("*.md")):
            text = lesson_path.read_text(encoding="utf-8")
            lesson = parse_lesson(text)
            vector = embed(lesson.match_text())
            records.append(
                {
                    "id": lesson.id,
                    "path": str(lesson_path),
                    "vector": vector,
                }
            )

    index_path = cache_dir / INDEX_FILENAME
    index_path.write_text(
        json.dumps({"model": MODEL_NAME, "dim": EMBEDDING_DIM, "records": records}),
        encoding="utf-8",
    )
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

## server/schema.py
```
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
    lines stripped. This is a plain positional split, not a "## " line
    scanner: render() always emits headers in this fixed order with a
    single blank line of padding on each side, so locating each header's
    string offset and slicing between them exactly inverts that format.
    A body section's own free text containing another section's exact
    header string as a literal substring (e.g. a symptom that quotes
    "## Fix" verbatim) would confuse this split — an accepted, narrow
    limitation given real lesson prose doesn't do that.
    """
    positions: list[tuple[int, str]] = []
    for header in BODY_SECTION_HEADERS:
        idx = body_text.find(header)
        if idx == -1:
            raise ValueError(
                f"lesson body is missing the required section header {header!r}"
            )
        positions.append((idx, header))

    positions.sort(key=lambda pair: pair[0])
    if [header for _, header in positions] != list(BODY_SECTION_HEADERS):
        raise ValueError(
            "lesson body section headers are present but out of order; "
            f"expected {list(BODY_SECTION_HEADERS)}"
        )

    sections: dict[str, str] = {}
    for i, (idx, header) in enumerate(positions):
        content_start = idx + len(header)
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
```

## server/tests/test_index.py
```
"""Tests for server/index.py: fastembed-backed local similarity index.

Builds a real index (via fastembed's BAAI/bge-small-en-v1.5 model — no
mocking; per the Task 3 brief, this must be exercised for real) from the
fixture lesson files in server/tests/fixtures/, then asserts:
  - a query closely matching one lesson's title/tags ranks that lesson
    first;
  - a clearly unrelated query returns an empty list (nothing clears the
    similarity threshold — Global Constraints: never a weak match
    dressed as strong).

Requires network access on first run only, for fastembed to download and
locally cache BAAI/bge-small-en-v1.5's ONNX weights (~130MB). After that
first download the model is read from fastembed's own local cache and no
further network access is needed.
"""

from __future__ import annotations

from pathlib import Path

import index as idx

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# One id per fixture lesson in server/tests/fixtures/, for readability in
# assertions below.
FASTMCP_LESSON_ID = "2026-07-18-fastmcp-pydantic-floor"
REACT_LESSON_ID = "2026-06-02-react-useeffect-infinite-loop"
DOCKER_LESSON_ID = "2026-05-14-docker-build-oom-killed"
POSTGRES_LESSON_ID = "2026-04-01-postgres-pool-exhausted"


def _build_fixture_index(cache_dir: Path) -> Path:
    return idx.build_index(FIXTURES_DIR, cache_dir)


def test_fixtures_dir_has_expected_lesson_files():
    # Guards against a typo/rename in the fixture filenames silently
    # turning every test below into a no-op (build_index would just
    # index nothing and every assertion would vacuously pass/fail wrong).
    md_files = sorted(p.stem for p in FIXTURES_DIR.glob("*.md"))
    assert md_files == sorted(
        [FASTMCP_LESSON_ID, REACT_LESSON_ID, DOCKER_LESSON_ID, POSTGRES_LESSON_ID]
    )


def test_embed_returns_384_dim_float_vector():
    vector = idx.embed("a short test string")
    assert isinstance(vector, list)
    assert len(vector) == idx.EMBEDDING_DIM == 384
    assert all(isinstance(x, float) for x in vector)


def test_build_index_writes_a_record_per_lesson(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    index_path = _build_fixture_index(cache_dir)

    assert index_path.exists()
    assert index_path == cache_dir / idx.INDEX_FILENAME

    import json

    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["model"] == idx.MODEL_NAME == "BAAI/bge-small-en-v1.5"
    assert data["dim"] == 384
    ids = {record["id"] for record in data["records"]}
    assert ids == {FASTMCP_LESSON_ID, REACT_LESSON_ID, DOCKER_LESSON_ID, POSTGRES_LESSON_ID}
    for record in data["records"]:
        assert len(record["vector"]) == 384
        assert Path(record["path"]).exists()


def test_build_index_over_empty_lessons_dir_produces_empty_index(tmp_path: Path):
    empty_lessons_dir = tmp_path / "no-lessons-here"
    cache_dir = tmp_path / "cache"
    # lessons_dir doesn't even exist yet -- must not error.
    idx.build_index(empty_lessons_dir, cache_dir)

    results = idx.search("anything at all", cache_dir, k=3, threshold=0.0)
    assert results == []


def test_index_is_rebuildable_from_markdown_alone(tmp_path: Path):
    # Global Constraints: index format must be fully rebuildable from the
    # markdown lessons alone -- never treat the cache as authoritative.
    # Prove it by building twice (simulating a deleted/corrupted cache in
    # between) and getting equivalent search results both times.
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)
    first = idx.search(
        "FastMCP crashes with PydanticUserError non-annotated attribute",
        cache_dir,
        k=1,
    )

    # Simulate cache loss, then rebuild purely from the lesson .md files.
    (cache_dir / idx.INDEX_FILENAME).unlink()
    _build_fixture_index(cache_dir)
    second = idx.search(
        "FastMCP crashes with PydanticUserError non-annotated attribute",
        cache_dir,
        k=1,
    )

    assert first and second
    assert first[0]["id"] == second[0]["id"] == FASTMCP_LESSON_ID


def test_query_closely_matching_a_lesson_ranks_it_first(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)

    results = idx.search(
        "pydantic annotation error registering a FastMCP tool", cache_dir, k=3
    )

    assert results, "expected at least one result to clear the default threshold"
    assert results[0]["id"] == FASTMCP_LESSON_ID
    # Sorted descending by score.
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_query_matching_a_different_lesson_ranks_that_one_first(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)

    results = idx.search(
        "useEffect causing an infinite re-render loop in a React component",
        cache_dir,
        k=3,
    )

    assert results
    assert results[0]["id"] == REACT_LESSON_ID


def test_unrelated_query_returns_empty_list(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)

    results = idx.search(
        "best hiking trails in the Pacific Northwest this summer", cache_dir, k=3
    )

    assert results == []


def test_search_respects_k_limit(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)

    # threshold=0.0 so every fixture lesson clears it -- isolates the k
    # cutoff behavior from threshold behavior.
    results = idx.search("docker postgres react fastmcp", cache_dir, k=2, threshold=0.0)
    assert len(results) == 2


def test_search_against_missing_index_returns_empty_list(tmp_path: Path):
    cache_dir = tmp_path / "cache-never-built"
    results = idx.search("anything", cache_dir, k=3)
    assert results == []
```

## server/tests/test_schema.py
```
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


def test_parse_lesson_raises_on_missing_frontmatter():
    with pytest.raises(ValueError):
        parse_lesson("## Symptom\n\nno frontmatter block here\n")


def test_parse_lesson_raises_on_missing_body_section():
    lesson = make_lesson()
    doc = lesson.render()
    truncated = doc.split("## Fix")[0]  # drop Fix and Tags sections
    with pytest.raises(ValueError):
        parse_lesson(truncated)
```

## server/requirements.txt
```
# Pinned to the versions verified against this plugin during development.
#
# .mcp.json launches the server via `uv run --no-project --with-requirements
# server/requirements.txt server/main.py`. uv reads this file and
# auto-provisions an isolated, ephemeral environment (cached in uv's own
# cache dir, not a project-local directory) on first launch — no manual
# venv-bootstrap step required on a fresh checkout. Requires `uv`
# (https://docs.astral.sh/uv/) to be installed on the developer's machine;
# nothing else to set up.
#
# To reproduce the same environment manually (e.g. for local testing
# outside Claude Code):
#   uv run --no-project --with-requirements server/requirements.txt server/main.py

# Official MCP Python SDK - server transport, tool registration (FastMCP).
mcp==1.27.0

# Local embeddings for the similarity index (BAAI/bge-small-en-v1.5).
# Wired up starting Task 3 (server/index.py).
fastembed==0.8.0

# YAML frontmatter parsing (schema.py's parse_lesson(), the inverse of
# Lesson.render()). render()'s emission stays hand-rolled (see schema.py's
# module docstring for why); parsing takes the PyYAML dependency instead
# of hand-rolling a YAML-escape unescaper. Was already an indirect
# dependency (pulled in transitively by mcp) and used directly by
# server/tests/test_schema.py since Task 2 — pinned explicitly here from
# Task 3 onward since production code (schema.py) now imports it too, not
# just tests.
PyYAML==6.0.3

# Test runner for server/tests/ (schema.py, scrub.py, and later modules).
# Run with:
#   uv run --no-project --with-requirements server/requirements.txt \
#       pytest server/tests/
pytest==8.3.4
```

## fixtures

### /Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-04-01-postgres-pool-exhausted.md
```
---
id: "2026-04-01-postgres-pool-exhausted"
title: "Postgres connection pool exhausted under load"
domain:
  - "postgres"
  - "database"
  - "backend"
error_signature: "FATAL: remaining connection slots are reserved for non-replication superuser connections"
created_at: "2026-04-01T08:15:00Z"
confidence: confirmed
---

## Symptom

API requests start timing out under moderate traffic with database connection errors in the logs.

## Approaches that FAILED (do not repeat)

- Increasing Postgres's max_connections setting without addressing app-side leaks

## Root cause

A connection leak in a request-scoped session that was never closed on the error path.

## Fix

Added a try/finally around the session so it always closes, and switched to a bounded connection pool.

## Tags for retrieval

- postgres
- connection-pool
- database-timeout
```

### /Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-05-14-docker-build-oom-killed.md
```
---
id: "2026-05-14-docker-build-oom-killed"
title: "Docker image build gets OOM killed during webpack bundling"
domain:
  - "docker"
  - "devops"
  - "ci"
error_signature: "exit code 137"
created_at: "2026-05-14T18:00:00Z"
confidence: probable
---

## Symptom

The CI build step exits abruptly partway through the frontend bundling stage.

## Approaches that FAILED (do not repeat)

- Increasing the webpack cache size, which made memory pressure worse

## Root cause

The CI runner's container memory limit was lower than webpack's peak heap usage during minification.

## Fix

Raised the container memory limit and enabled webpack's memory-friendly minifier.

## Tags for retrieval

- docker
- oom
- webpack
- ci-build
```

### /Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-06-02-react-useeffect-infinite-loop.md
```
---
id: "2026-06-02-react-useeffect-infinite-loop"
title: "React useEffect infinite loop from missing dependency array"
domain:
  - "javascript"
  - "react"
  - "frontend"
error_signature: "Maximum update depth exceeded"
created_at: "2026-06-02T09:30:00Z"
confidence: confirmed
---

## Symptom

Component re-renders continuously and the browser tab freezes shortly after mount.

## Approaches that FAILED (do not repeat)

- Wrapping the state setter in useCallback without fixing the effect's dependency array

## Root cause

useEffect had no dependency array, so it ran after every render, and the effect itself called a state setter, triggering another render.

## Fix

Added the correct dependency array so the effect only runs when its inputs change.

## Tags for retrieval

- react
- hooks
- infinite-loop
- useeffect
```

### /Users/ilaakshmishra/Documents/hindsight/server/tests/fixtures/2026-07-18-fastmcp-pydantic-floor.md
```
---
id: "2026-07-18-fastmcp-pydantic-floor"
title: "FastMCP tool registration crashes with stale pydantic"
domain:
  - "python"
  - "mcp"
  - "fastmcp"
error_signature: "PydanticUserError: A non-annotated attribute was detected"
created_at: "2026-07-18T12:00:00Z"
confidence: confirmed
---

## Symptom

Server crashes at import time when registering any tool with a bare return type annotation.

## Approaches that FAILED (do not repeat)

- Upgrading only the mcp package without checking pydantic's floor
- Adding explicit Pydantic BaseModel wrappers to every tool return type

## Root cause

Global python3's pydantic (2.9.2) predates the floor mcp==1.27.0 requires (>=2.11.0); create_model() with a bare annotation is rejected by the old version.

## Fix

Run the server via `uv run --with-requirements server/requirements.txt server/main.py` so a compliant pydantic is resolved in an ephemeral environment.

## Tags for retrieval

- pydantic
- fastmcp
- dependency-conflict
- mcp-sdk
```
