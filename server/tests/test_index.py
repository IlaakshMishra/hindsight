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

import json
from pathlib import Path

import pytest

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


def test_build_index_skips_malformed_lesson_file_and_indexes_the_rest(tmp_path: Path):
    # Regression test (Task 3 review fix): one malformed lesson file must
    # not abort the entire build -- build_index must skip it, collect why,
    # and still produce a working index for every lesson that DOES parse.
    from schema import Lesson

    lessons_dir = tmp_path / "lessons"
    lessons_dir.mkdir()
    cache_dir = tmp_path / "cache"

    valid_ids = []
    for i in range(3):
        lesson = Lesson(
            id=f"2026-01-0{i + 1}-valid-lesson",
            title=f"Valid lesson number {i}",
            domain=["python"],
            error_signature=f"ValueError: boom number {i}",
            created_at="2026-01-01T00:00:00Z",
            confidence="confirmed",
            symptom=f"Something broke in scenario {i}.",
            failed_approaches=["Tried restarting the service"],
            root_cause=f"Root cause for scenario {i}.",
            fix=f"Fix applied for scenario {i}.",
            tags=["regression-test"],
        )
        valid_ids.append(lesson.id)
        (lessons_dir / f"{lesson.id}.md").write_text(lesson.render(), encoding="utf-8")

    # Malformed frontmatter: an unterminated double-quoted YAML scalar.
    # Confirmed (outside this test) that this raises yaml.parser.ParserError
    # -- a different exception hierarchy than the ValueError parse_lesson
    # raises for missing fields/sections, so this also proves the fix
    # catches more than just ValueError.
    malformed_path = lessons_dir / "2026-01-04-malformed.md"
    malformed_path.write_text(
        '---\nid: "unterminated\ntitle: "oops"\n---\n\n## Symptom\n\nx\n',
        encoding="utf-8",
    )

    index_path = idx.build_index(lessons_dir, cache_dir)  # must not raise

    import json

    data = json.loads(index_path.read_text(encoding="utf-8"))
    ids = {record["id"] for record in data["records"]}
    assert ids == set(valid_ids)
    assert len(data["records"]) == 3

    assert len(data["skipped"]) == 1
    assert data["skipped"][0]["path"] == str(malformed_path)
    assert data["skipped"][0]["error"]  # non-empty explanation

    # The index built from the valid lessons is actually usable.
    results = idx.search(
        "Valid lesson number 0 ValueError boom number 0",
        cache_dir,
        k=3,
        threshold=0.0,
    )
    assert results
    assert results[0]["id"] == "2026-01-01-valid-lesson"


def test_search_against_missing_index_returns_empty_list(tmp_path: Path):
    cache_dir = tmp_path / "cache-never-built"
    results = idx.search("anything", cache_dir, k=3)
    assert results == []


# --- atomic index write (final whole-project review, Finding I2) ------------
#
# Before this fix, build_index did a plain index_path.write_text(...) --
# truncate-then-write, not atomic. A concurrent search() call racing a
# rebuild could observe index_path mid-truncation: a file that's been
# emptied but not yet fully rewritten. json.loads() on that content raises
# json.JSONDecodeError and crashes the search tool call outright. The fix:
# write to a temp file in the same directory, then os.replace() it over
# index_path -- atomic on POSIX, so a reader always sees either the
# complete old file or the complete new one, never a partial mix.


def test_build_index_leaves_previous_index_intact_if_the_atomic_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If anything goes wrong between writing the temp file and the
    atomic os.replace() swap, the PREVIOUS index.json (if any) must be
    left completely untouched -- proving build_index never truncates the
    real file in place the way a plain `.write_text()` would.
    """
    cache_dir = tmp_path / "cache"
    # First real build -- establishes a real, valid "previous" index.json.
    _build_fixture_index(cache_dir)
    index_path = cache_dir / idx.INDEX_FILENAME
    original_bytes = index_path.read_bytes()
    assert original_bytes  # sanity: non-empty

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash between temp-write and replace")

    # idx.os IS the real os module (a shared singleton) -- patching its
    # `replace` attribute here patches exactly the call build_index makes
    # (`os.replace(tmp_name, index_path)`), and monkeypatch reverts it
    # automatically at the end of this test.
    monkeypatch.setattr(idx.os, "replace", _boom)

    with pytest.raises(RuntimeError):
        _build_fixture_index(cache_dir)

    # The previous, valid index.json must be untouched -- byte-for-byte.
    assert index_path.read_bytes() == original_bytes
    # And still valid, parseable JSON (the whole point of atomicity here).
    json.loads(index_path.read_text(encoding="utf-8"))

    # No leftover temp file from the failed attempt.
    leftover = [p for p in cache_dir.iterdir() if p.name != idx.INDEX_FILENAME]
    assert leftover == [], f"leftover temp file(s) after a failed build: {leftover}"


def test_build_index_still_produces_a_valid_index_after_the_atomic_write_change(
    tmp_path: Path,
):
    # Confirms the existing (pre-Finding-I2) behavior still holds with the
    # new write mechanism: a normal, successful build produces a single,
    # valid index.json and no stray temp files left behind.
    cache_dir = tmp_path / "cache"
    index_path = _build_fixture_index(cache_dir)

    assert index_path == cache_dir / idx.INDEX_FILENAME
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(data["records"]) == 4

    all_files = list(cache_dir.iterdir())
    assert all_files == [index_path], f"expected only index.json, got {all_files}"


# --- model/dim validation on index load (final whole-project review, --------
# --- Finding M1) --------------------------------------------------------------
#
# index.json stores model/dim but search() never checked them -- a future
# model change (different EMBEDDING_DIM) would silently compare
# mismatched-dimension vectors via _cosine_similarity's zip(a, b), which
# truncates to the shorter vector instead of raising, producing a
# meaningless score dressed up as a real one. This same guard is defense in
# depth for Finding C1's per-project cache partitioning: if some other bug
# ever let one project's index.json get read by another project (or a
# machine running a different pinned model), this check catches the
# mismatch instead of silently comparing vectors that were never meant to
# be compared.


def test_search_returns_empty_and_deletes_index_on_model_mismatch(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    index_path = cache_dir / idx.INDEX_FILENAME
    index_path.write_text(
        json.dumps(
            {
                "model": "some-other-model-v1",
                "dim": 999,
                "records": [
                    {
                        "id": "foo",
                        "path": str(tmp_path / "foo.md"),
                        "vector": [0.1] * 999,
                    }
                ],
                "skipped": [],
            }
        ),
        encoding="utf-8",
    )

    results = idx.search("anything at all", cache_dir, k=3, threshold=0.0)

    assert results == []
    # Self-healing: the stale/foreign index is deleted so the caller's own
    # on-demand-build-if-missing logic (server/main.py's search_lessons)
    # rebuilds it correctly from the markdown lessons on the next call,
    # rather than this function silently comparing mismatched vectors
    # forever.
    assert not index_path.exists()


def test_search_returns_empty_and_deletes_index_on_dim_mismatch_alone(tmp_path: Path):
    # dim can drift independently of model (e.g. a hand-edited or
    # corrupted index.json) -- both fields are checked, not just model.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    index_path = cache_dir / idx.INDEX_FILENAME
    index_path.write_text(
        json.dumps(
            {
                "model": idx.MODEL_NAME,
                "dim": 42,
                "records": [
                    {
                        "id": "foo",
                        "path": str(tmp_path / "foo.md"),
                        "vector": [0.1] * 42,
                    }
                ],
                "skipped": [],
            }
        ),
        encoding="utf-8",
    )

    results = idx.search("anything at all", cache_dir, k=3, threshold=0.0)

    assert results == []
    assert not index_path.exists()


def test_search_accepts_index_with_matching_model_and_dim(tmp_path: Path):
    # Negative check for the two tests above: a normal, correctly built
    # index (matching MODEL_NAME/EMBEDDING_DIM) must not be treated as
    # stale -- the guard must not false-positive on real indexes.
    cache_dir = tmp_path / "cache"
    _build_fixture_index(cache_dir)

    results = idx.search(
        "useEffect causing an infinite re-render loop in a React component",
        cache_dir,
        k=3,
    )

    assert results
    assert (cache_dir / idx.INDEX_FILENAME).exists()
