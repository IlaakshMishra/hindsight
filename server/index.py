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
