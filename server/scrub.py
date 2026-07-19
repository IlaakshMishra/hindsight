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
# Group 3 (the optional quote) is backreferenced as the closing
# delimiter so surrounding quote characters, if present, survive
# redaction instead of being dropped.
_AWS_SECRET_KEY_RE = re.compile(
    r"(?i)\b(aws_secret_access_key|aws_secret_key|secret_access_key)"
    r"(\s*[:=]\s*)"
    r"([\"']?)[A-Za-z0-9/+=]{40}\3"
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

# Hex-encoded secrets explicitly labeled with a secret-shaped variable
# name (`api_key`, `SECRET_KEY`, `auth_token`, ...) at a canonical
# digest/SHA length (32 = MD5, 40 = SHA-1/git commit, 64 = SHA-256/Docker
# image ID). Handled as its own dedicated, context-aware pattern here —
# mirroring `_AWS_SECRET_KEY_RE` above, which keys off a variable name
# rather than the value's own randomness — instead of being folded into
# the generic high-entropy catch-all below, because entropy alone can't
# distinguish a labeled hex secret from an incidental SHA/checksum
# reference: hex's 16-symbol alphabet makes near-max entropy the
# *normal* case for any hex string, not a secrecy signal. An *unlabeled*
# hex value at these lengths is assumed to be a checksum/SHA/image-id in
# ordinary technical prose and is deliberately left alone (see the
# `_HEX_CHARS` handling in `_looks_like_secret` below) — this pattern
# only fires when a recognizable identifier is directly attached via
# `:`/`=`, same as the AWS pattern's own scope.
#
# Capture groups: (1) identifier, (2) separator incl. surrounding
# whitespace, (3) optional opening quote, (4) the hex value. Group 3 is
# backreferenced as the closing delimiter so a quoted value keeps
# matching quotes (or an unquoted value keeps none) — this also means,
# unlike `_AWS_SECRET_KEY_RE`, surrounding quote characters survive
# redaction instead of being silently dropped.
_LABELED_HEX_SECRET_RE = re.compile(
    r"(?i)\b([A-Za-z][A-Za-z0-9_]*)(\s*[:=]\s*)([\"']?)"
    r"([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})"
    r"(?![0-9a-fA-F])\3"
)

# Substrings that make an identifier "secret-shaped" for
# `_LABELED_HEX_SECRET_RE`. Deliberately substring (not whole-word)
# matching so `api_key`, `SECRET_KEY`, `aws_secret_access_key` all count
# as labeled — the tradeoff is that an unrelated identifier merely
# containing one of these as a substring (e.g. `monkey`) would also
# count; for a secret scrubber, over-redacting on an ambiguous label is
# the safe failure direction.
_HEX_SECRET_LABEL_KEYWORDS = ("secret", "key", "token", "password", "credential")


def _redact_labeled_hex_secret(m: re.Match[str]) -> str:
    identifier, sep, quote = m.group(1), m.group(2), m.group(3)
    if any(kw in identifier.lower() for kw in _HEX_SECRET_LABEL_KEYWORDS):
        return f"{identifier}{sep}{quote}{REDACTED}{quote}"
    return m.group(0)


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

# Pure hex-alphabet strings (0-9, a-f, A-F) at a canonical digest/SHA
# length (`_HEX_DIGEST_LENGTHS` — same three lengths as
# `_LABELED_HEX_SECRET_RE` above) are excluded from the entropy
# threshold: hex's 16-symbol alphabet makes near-max entropy
# (log2(16) = 4 bits/char) the *normal* case for any hex string of these
# lengths — git commit SHAs, Docker image IDs, MD5/SHA checksums in
# ordinary technical prose — not a signal of randomness/secrecy the way
# it is for a wider alphabet, so entropy alone can't tell one from a hex
# secret. This is safe to do *unconditionally* here (no context check
# needed at this point) because `_LABELED_HEX_SECRET_RE` already ran
# earlier in `scrub()` and redacted every *labeled* hex secret at these
# lengths — see that pattern's docstring for the labeled/unlabeled
# split. Hex strings at *other* lengths have no such length-based signal
# and fall through to the plain entropy check like any other candidate
# token (this deliberately narrows the exclusion relative to a blanket
# "all pure hex" rule, which would also suppress a real hex secret that
# happens to land on a non-canonical length).
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")
_HEX_DIGEST_LENGTHS = frozenset({32, 40, 64})


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
    in ordinary technical prose), excludes pure hex strings at canonical
    digest/SHA lengths (git SHAs, checksums, image IDs — see
    `_HEX_DIGEST_LENGTHS`; a *labeled* hex secret at these lengths was
    already redacted earlier by `_LABELED_HEX_SECRET_RE`, so anything
    reaching this function is presumed unlabeled), AND requires Shannon
    entropy above a threshold tuned to flag randomized alphanumeric
    tokens.
    """
    has_digit = any(c.isdigit() for c in token)
    has_alpha = any(c.isalpha() for c in token)
    if not (has_digit and has_alpha):
        return False
    if len(token) in _HEX_DIGEST_LENGTHS and all(c in _HEX_CHARS for c in token):
        return False
    return _shannon_entropy(token) >= _ENTROPY_THRESHOLD_BITS_PER_CHAR


def scrub(text: str) -> str:
    """Redact secrets from `text`, returning the scrubbed string.

    Redacts, in order: PEM private key blocks, DB connection strings,
    AWS access key IDs, AWS secret access keys, bearer tokens, `sk-`
    API keys, labeled hex secrets (e.g. `api_key: <hex>`), and any
    remaining long high-entropy token. Redaction is always in place —
    only the offending token/block becomes `[REDACTED]`; the rest of the
    sentence/line is left untouched.
    """
    if not text:
        return text

    result = _PRIVATE_KEY_RE.sub(REDACTED, text)
    result = _DB_CONN_RE.sub(REDACTED, result)
    result = _AWS_ACCESS_KEY_RE.sub(REDACTED, result)
    result = _AWS_SECRET_KEY_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}",
        result,
    )
    result = _BEARER_TOKEN_RE.sub("Bearer " + REDACTED, result)
    result = _SK_KEY_RE.sub(REDACTED, result)
    result = _LABELED_HEX_SECRET_RE.sub(_redact_labeled_hex_secret, result)
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
