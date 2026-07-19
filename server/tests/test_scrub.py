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


def test_aws_secret_key_surrounding_quotes_are_preserved():
    text = f'AWS_SECRET_ACCESS_KEY="{FAKE_AWS_SECRET_KEY}"'
    out = scrub(text)
    assert FAKE_AWS_SECRET_KEY not in out
    assert out == f'AWS_SECRET_ACCESS_KEY="{REDACTED}"'


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


def test_mysql_connection_string_is_redacted():
    conn = "mysql://root:hunter2@db.internal.example.com:3306/app_db"
    text = f"Connection failed: {conn} timed out after 30s"
    out = scrub(text)
    assert conn not in out
    assert "hunter2" not in out
    assert REDACTED in out


def test_mongodb_srv_connection_string_is_redacted():
    conn = "mongodb+srv://appuser:hunter2@cluster0.example.mongodb.net/mydb"
    text = f"Connection failed: {conn} timed out after 30s"
    out = scrub(text)
    assert conn not in out
    assert "hunter2" not in out
    assert REDACTED in out


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
    #
    # (This is the well-known git "empty tree" SHA-1 constant — exactly
    # 40 hex chars, chosen so the fixture is unambiguously a real,
    # canonical-length git SHA and not an off-by-one typo.)
    sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    assert len(sha) == 40
    text = f"The regression was introduced in commit {sha} on main."
    assert scrub(text) == text


def test_sha256_checksum_is_not_flagged():
    checksum = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    text = f"Expected checksum {checksum} did not match downloaded artifact."
    assert scrub(text) == text


# --- Labeled hex secrets: the pure-hex exclusion must not create a -------
# --- blind spot for hex-encoded secrets that are explicitly labeled -----

# Deliberately fabricated hex values at the three canonical digest/SHA
# lengths the scrubber special-cases (32 = MD5, 40 = SHA-1/git, 64 =
# SHA-256). None of these are real credentials.
FAKE_HEX_SECRET_32 = "a1b2c3d4e5f60718293a4b5c6d7e8f9a"[:32]
FAKE_HEX_SECRET_40 = "5f4dcc3b5aa765d61d8327deb882cf995f4dcc3b"
FAKE_HEX_SECRET_64 = "aa11bb22cc33dd44ee55ff6600112233445566778899aabbccddeeff00112233"[:64]
assert len(FAKE_HEX_SECRET_32) == 32
assert len(FAKE_HEX_SECRET_40) == 40
assert len(FAKE_HEX_SECRET_64) == 64


def test_labeled_hex_secret_api_key_32_chars_is_redacted():
    text = f"api_key: {FAKE_HEX_SECRET_32}"
    out = scrub(text)
    assert FAKE_HEX_SECRET_32 not in out
    assert REDACTED in out
    assert "api_key:" in out


def test_labeled_hex_secret_api_key_40_chars_is_redacted():
    # This is the exact shape from the reported finding: a labeled hex
    # value at a canonical SHA-1 length must redact, unlike a bare SHA.
    text = f"api_key: {FAKE_HEX_SECRET_40}"
    out = scrub(text)
    assert FAKE_HEX_SECRET_40 not in out
    assert REDACTED in out
    assert "api_key:" in out


def test_labeled_hex_secret_secret_key_64_chars_is_redacted():
    # openssl-rand-hex-32-style value assigned to SECRET_KEY.
    text = f"SECRET_KEY={FAKE_HEX_SECRET_64}"
    out = scrub(text)
    assert FAKE_HEX_SECRET_64 not in out
    assert REDACTED in out
    assert "SECRET_KEY=" in out


def test_labeled_hex_secret_token_is_redacted():
    text = f"token: {FAKE_HEX_SECRET_40}"
    out = scrub(text)
    assert FAKE_HEX_SECRET_40 not in out
    assert REDACTED in out
    assert "token:" in out


def test_labeled_hex_secret_survives_surrounding_quotes():
    text = f'SECRET_KEY="{FAKE_HEX_SECRET_32}"'
    out = scrub(text)
    assert FAKE_HEX_SECRET_32 not in out
    assert REDACTED in out


def test_bare_hex_value_with_no_label_is_still_not_flagged():
    # Regression guard: closing the labeled-secret gap must not turn
    # into a blanket "redact all canonical-length hex" rule -- a bare
    # hex value with no secret-shaped identifier in front of it is still
    # assumed to be a checksum/SHA/image-id, not a secret.
    text = f"debug hash dump: {FAKE_HEX_SECRET_40} (for reference only)"
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
