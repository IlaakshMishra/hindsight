# Review package: Task 2 (no git — full file dump)

## Files
```
/Users/ilaakshmishra/Documents/hindsight/.claude-plugin/plugin.json
/Users/ilaakshmishra/Documents/hindsight/.claude/settings.local.json
/Users/ilaakshmishra/Documents/hindsight/.gitignore
/Users/ilaakshmishra/Documents/hindsight/.mcp.json
/Users/ilaakshmishra/Documents/hindsight/README.md
/Users/ilaakshmishra/Documents/hindsight/server/main.py
/Users/ilaakshmishra/Documents/hindsight/server/requirements.txt
/Users/ilaakshmishra/Documents/hindsight/server/schema.py
/Users/ilaakshmishra/Documents/hindsight/server/scrub.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/conftest.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_schema.py
/Users/ilaakshmishra/Documents/hindsight/server/tests/test_scrub.py
/Users/ilaakshmishra/Documents/hindsight/templates/LESSON_TEMPLATE.md
```

## templates/LESSON_TEMPLATE.md
```
---
id: "<id>"
title: "<title>"
domain:
  - "<domain-1>"
  - "<domain-2>"
error_signature: "<error_signature>"
created_at: "<created_at>"
confidence: <confirmed|probable>
---

## Symptom

<What was observed — the visible symptom, not yet diagnosed. Plain
prose, no raw stack traces with file paths/line numbers.>

## Approaches that FAILED (do not repeat)

- <An approach that was tried and did NOT fix the problem, and why>
- <Another failed approach, if any>

## Root cause

<The actual underlying cause, once identified.>

## Fix

<The change that resolved it.>

## Tags for retrieval

- <short retrieval tag>
- <short retrieval tag>
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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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


def _yaml_quote(value: str) -> str:
    """Double-quote a scalar for safe inclusion in hand-emitted YAML.

    Lesson text (titles, error signatures) is free-form and may contain
    colons, `#`, or quotes that would otherwise break YAML parsing if
    emitted unquoted. Double-quoted scalar style with escaped backslashes
    and quotes is valid YAML for any string content. Frontmatter here is
    flat (six scalar/list-of-scalar fields) so hand-emitting it
    deterministically avoids taking a PyYAML dependency this module
    otherwise wouldn't need.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
```

## server/scrub.py
```
"""Secret scrubber: redacts credentials and high-entropy tokens from
free-text before it is ever written to disk.

Global Constraints (binding, copied verbatim from the plan):

    Secrets never written: regex pass (AWS keys, bearer tokens, `sk-`
    style keys, connection strings, private key blocks, long
    high-entropy strings) must run before anything touches disk (that
    wiring happens in a later task — this task just builds the scrubber
    function itself and proves it works standalone).

This module has no MCP dependency and does not touch `server/main.py` —
wiring `scrub`/`scrub_payload` into `save_lesson`'s write path is Task 4.

Redaction is always in place: only the offending token/block is replaced
with the `[REDACTED]` marker; the surrounding sentence is never dropped.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

REDACTED = "[REDACTED]"

# --- Specific, low-false-positive patterns --------------------------------

# AWS access key IDs: fixed, well-known prefixes (also covers STS
# temporary session keys under ASIA).
_AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")

# AWS secret access keys have no distinguishing prefix — just 40
# base64-alphabet characters — so matching them standalone anywhere in
# text is too false-positive-prone (a 40-char base64 blob could be
# almost anything). Real-world secret scanners key off the surrounding
# variable name; this does the same: a recognizable "secret key"
# identifier followed by `:`/`=` and a quoted-or-bare 40-char value.
_AWS_SECRET_KEY_RE = re.compile(
    r"(?i)\b(aws_secret_access_key|aws_secret_key|secret_access_key)"
    r"(\s*[:=]\s*)"
    r"[\"']?[A-Za-z0-9/+=]{40}[\"']?"
)

# Generic bearer tokens: `Bearer <token>` (Authorization headers, etc).
# Redact only the token; keep the scheme word for context.
_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{10,}")

# `sk-`-prefixed API keys (OpenAI-style and similar). Negative lookbehind
# stops this from matching as a substring of some longer unrelated token.
_SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{16,}\b")

# DB connection strings with embedded credentials:
# scheme://user:pass@host[:port]/db
_DB_CONN_RE = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)"
    r"://[^\s'\"]+:[^\s'\"@]+@[^\s'\"]+"
)

# PEM-style private key blocks (RSA/EC/DSA/OpenSSH/generic). Redact the
# entire block, including the BEGIN/END markers.
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# --- Generic high-entropy token catch-all ---------------------------------

# Candidate runs of secret-alphabet characters, >=32 chars long.
# Deliberately excludes `/` and whitespace so ordinary filesystem paths
# and URLs (exactly the "ordinary technical prose" this scrubber must
# leave alone) don't get swept into one long token.
_TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+_=\-]{32,}")

# Threshold tuned empirically (see server/tests/test_scrub.py) to flag
# randomized alphanumeric tokens (API keys, generated secrets) while
# passing plain-English kebab/snake-case identifiers and hex-ish IDs that
# lack digit+letter variety.
_ENTROPY_THRESHOLD_BITS_PER_CHAR = 3.5

# Pure hex-alphabet strings (0-9, a-f, A-F) are excluded from the
# high-entropy catch-all even when they clear the entropy threshold.
# Hex-only tokens of this length are overwhelmingly git commit SHAs,
# Docker image IDs, and MD5/SHA checksums in ordinary technical prose —
# not secrets — and hex's 16-symbol alphabet makes near-max entropy
# (log2(16) = 4 bits/char) the *normal* case for any of those, not a
# signal of randomness/secrecy the way it is for a wider alphabet.
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _looks_like_secret(token: str) -> bool:
    """Heuristic for a "long high-entropy token" per Global Constraints.

    Requires a mix of letters and digits (this rules out plain
    hyphenated slugs, lowercase words, and pure numeric IDs — all common
    in ordinary technical prose), excludes pure hex strings (git SHAs,
    checksums, image IDs — see `_HEX_CHARS`), AND requires Shannon
    entropy above a threshold tuned to flag randomized alphanumeric
    tokens.
    """
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    if not (has_digit and has_alpha):
        return False
    if all(c in _HEX_CHARS for c in token):
        return False
    return _shannon_entropy(token) >= _ENTROPY_THRESHOLD_BITS_PER_CHAR


def scrub(text: str) -> str:
    """Redact secrets from `text`, returning the scrubbed string.

    Redacts, in order: PEM private key blocks, DB connection strings,
    AWS access key IDs, AWS secret access keys, bearer tokens, `sk-`
    API keys, and any remaining long high-entropy token. Redaction is
    always in place — only the offending token/block becomes
    `[REDACTED]`; the rest of the sentence/line is left untouched.
    """
    if not text:
        return text

    result = _PRIVATE_KEY_RE.sub(REDACTED, text)
    result = _DB_CONN_RE.sub(REDACTED, result)
    result = _AWS_ACCESS_KEY_RE.sub(REDACTED, result)
    result = _AWS_SECRET_KEY_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", result
    )
    result = _BEARER_TOKEN_RE.sub("Bearer " + REDACTED, result)
    result = _SK_KEY_RE.sub(REDACTED, result)
    result = _TOKEN_CANDIDATE_RE.sub(
        lambda m: REDACTED if _looks_like_secret(m.group(0)) else m.group(0),
        result,
    )
    return result


def scrub_payload(payload: Any) -> Any:
    """Recursively scrub every string value in a dict/list payload.

    Convenience wrapper anticipated by the brief ("scrub a whole payload
    dict") for the eventual `save_lesson` write path (wired up in Task
    4) — scrubs an entire tool-call payload, not just a single string.
    Non-string leaves (numbers, bools, None) pass through unchanged.
    """
    if isinstance(payload, str):
        return scrub(payload)
    if isinstance(payload, dict):
        return {k: scrub_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [scrub_payload(v) for v in payload]
    return payload
```

## server/tests/conftest.py
```
"""pytest config for server/tests.

`server/` has no package (`__init__.py`) — `main.py` is a flat script and
Task 1 deliberately kept it that way. To let test modules do plain
`import schema` / `import scrub` regardless of the directory pytest was
invoked from, put `server/` (this file's parent) on sys.path once, here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))
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
from schema import (
    BODY_SECTION_HEADERS,
    CONFIDENCE_VALUES,
    REQUIRED_FRONTMATTER_FIELDS,
    Lesson,
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
```

## server/tests/test_scrub.py
```
"""Tests for server/scrub.py.

Feeds payloads seeded with fake secrets (AWS keys, an `sk-...` key, a
bearer token, a Postgres connection string, a PEM private key block, and
a generic high-entropy token) and asserts none survive in the scrubbed
output. Also asserts ordinary technical prose (stack traces, code,
normal sentences) passes through unmodified, per Task 2's brief.

All secrets below are fabricated/example values (several are AWS's own
published documentation example keys) — none are real credentials.
"""

from __future__ import annotations

from scrub import REDACTED, scrub, scrub_payload

FAKE_AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
FAKE_AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
FAKE_SK_KEY = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"
FAKE_BEARER_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)
FAKE_PG_CONN_STRING = (
    "postgres://admin:Sup3rSecretPassw0rd@db.internal.example.com:5432/production_db"
)
FAKE_PEM_BLOCK = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEAxjM3examplefakekeymaterialnotarealkeyatallxxxxx\n"
    "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy\n"
    "-----END RSA PRIVATE KEY-----"
)
FAKE_HIGH_ENTROPY_TOKEN = "aB3dEf7gH9jKlMnOpQrStUvWxYz0123456QpXr9Z"


def test_aws_access_key_is_redacted():
    text = f"export AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}"
    out = scrub(text)
    assert FAKE_AWS_ACCESS_KEY not in out
    assert REDACTED in out
    assert "export AWS_ACCESS_KEY_ID=" in out  # sentence context preserved


def test_aws_secret_key_is_redacted():
    text = f"AWS_SECRET_ACCESS_KEY={FAKE_AWS_SECRET_KEY}"
    out = scrub(text)
    assert FAKE_AWS_SECRET_KEY not in out
    assert REDACTED in out
    assert "AWS_SECRET_ACCESS_KEY=" in out


def test_sk_style_api_key_is_redacted():
    text = f"Set OPENAI_API_KEY to {FAKE_SK_KEY} in your .env file."
    out = scrub(text)
    assert FAKE_SK_KEY not in out
    assert REDACTED in out
    assert "Set OPENAI_API_KEY to" in out
    assert "in your .env file." in out


def test_bearer_token_is_redacted():
    text = f"curl -H 'Authorization: Bearer {FAKE_BEARER_TOKEN}' https://api.example.com"
    out = scrub(text)
    assert FAKE_BEARER_TOKEN not in out
    assert REDACTED in out
    assert "curl -H 'Authorization: Bearer" in out
    assert "https://api.example.com" in out


def test_postgres_connection_string_is_redacted():
    text = f"Connection failed: {FAKE_PG_CONN_STRING} timed out after 30s"
    out = scrub(text)
    assert FAKE_PG_CONN_STRING not in out
    assert "Sup3rSecretPassw0rd" not in out
    assert REDACTED in out
    assert "Connection failed:" in out
    assert "timed out after 30s" in out


def test_pem_private_key_block_is_redacted():
    text = f"Here is the key:\n{FAKE_PEM_BLOCK}\nDo not commit this."
    out = scrub(text)
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "examplefakekeymaterial" not in out
    assert REDACTED in out
    assert "Here is the key:" in out
    assert "Do not commit this." in out


def test_generic_high_entropy_token_is_redacted():
    text = f"debug token dump: {FAKE_HIGH_ENTROPY_TOKEN} (session cache)"
    out = scrub(text)
    assert FAKE_HIGH_ENTROPY_TOKEN not in out
    assert REDACTED in out
    assert "debug token dump:" in out
    assert "(session cache)" in out


def test_all_secrets_in_one_payload_are_scrubbed_simultaneously():
    text = "\n".join(
        [
            f"AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}",
            f"AWS_SECRET_ACCESS_KEY={FAKE_AWS_SECRET_KEY}",
            f"OPENAI_API_KEY={FAKE_SK_KEY}",
            f"Authorization: Bearer {FAKE_BEARER_TOKEN}",
            f"DATABASE_URL={FAKE_PG_CONN_STRING}",
            FAKE_PEM_BLOCK,
        ]
    )
    out = scrub(text)
    for secret in (
        FAKE_AWS_ACCESS_KEY,
        FAKE_AWS_SECRET_KEY,
        FAKE_SK_KEY,
        FAKE_BEARER_TOKEN,
        FAKE_PG_CONN_STRING,
        "BEGIN RSA PRIVATE KEY",
    ):
        assert secret not in out, f"{secret!r} survived scrubbing"


def test_ordinary_stack_trace_passes_through_unmodified():
    text = (
        'Traceback (most recent call last):\n'
        '  File "/Users/dev/project/app.py", line 42, in <module>\n'
        "    result = risky_call()\n"
        '  File "/Users/dev/project/utils.py", line 17, in risky_call\n'
        '    raise ValueError("something broke: unexpected token at position 12")\n'
        "ValueError: something broke: unexpected token at position 12"
    )
    assert scrub(text) == text


def test_ordinary_code_snippet_passes_through_unmodified():
    text = (
        "def foo(bar, baz):\n"
        "    total = bar + baz * 2\n"
        "    return total\n"
    )
    assert scrub(text) == text


def test_ordinary_sentence_passes_through_unmodified():
    text = (
        "The bug was caused by a race condition between two goroutines "
        "writing to the same map without a mutex."
    )
    assert scrub(text) == text


def test_long_kebab_case_identifier_without_digits_is_not_flagged():
    # Long, but low-entropy / no digit+letter mix -> should NOT be treated
    # as a high-entropy secret (avoids false positives on branch names,
    # slugs, etc. common in ordinary technical prose).
    text = (
        "git checkout -b this-is-a-very-long-descriptive-kebab-case-branch-name"
    )
    assert scrub(text) == text


def test_git_commit_sha_is_not_flagged():
    # A 40-char lowercase-hex git SHA has entropy close to hex's
    # theoretical max (log2(16) = 4 bits/char) purely by construction —
    # it is not a secret, and appears constantly in ordinary debugging
    # prose ("introduced in commit <sha>"). Must not be redacted.
    sha = "9fceb02d0ae598e95dc970b74767f19372d61d6"
    text = f"The regression was introduced in commit {sha} on main."
    assert scrub(text) == text


def test_sha256_checksum_is_not_flagged():
    checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    text = f"Expected checksum {checksum} did not match downloaded artifact."
    assert scrub(text) == text


def test_long_file_path_is_not_flagged():
    text = (
        "Wrote output to /Users/ilaakshmishra/Documents/hindsight/server/"
        "tests/fixtures/very-long-nested-directory-structure/output.json"
    )
    assert scrub(text) == text


def test_empty_string_returns_empty_string():
    assert scrub("") == ""


def test_scrub_payload_recurses_through_dict_and_list():
    payload = {
        "title": "Leaked AWS key in logs",
        "notes": [
            f"found {FAKE_AWS_ACCESS_KEY} in CI output",
            "unrelated normal note",
        ],
        "nested": {"secret": f"Bearer {FAKE_BEARER_TOKEN}"},
        "count": 3,
        "resolved": True,
        "extra": None,
    }
    out = scrub_payload(payload)

    assert FAKE_AWS_ACCESS_KEY not in out["notes"][0]
    assert "unrelated normal note" == out["notes"][1]
    assert FAKE_BEARER_TOKEN not in out["nested"]["secret"]
    # Non-string leaves pass through unchanged.
    assert out["count"] == 3
    assert out["resolved"] is True
    assert out["extra"] is None
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
# Not imported yet in Task 1's stub server; wired up starting Task 3.
fastembed==0.8.0

# Test runner for server/tests/ (schema.py, scrub.py, and later modules).
# Run with:
#   uv run --no-project --with-requirements server/requirements.txt \
#       pytest server/tests/
pytest==8.3.4
```
