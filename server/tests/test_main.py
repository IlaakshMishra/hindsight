"""Integration tests for server/main.py: the real search_lessons /
save_lesson / list_lessons MCP tool implementations, wired to schema.py +
scrub.py + index.py + store.py (Task 4).

Calls the tool functions directly (`main.save_lesson(...)`,
`main.search_lessons(...)`, `main.list_lessons()`), not through the MCP
stdio transport. This is safe: `FastMCP.tool()`'s decorator (confirmed by
reading `mcp.server.fastmcp.FastMCP.tool`'s source before relying on
this) registers the function as a side effect and then `return fn`s the
*original*, unwrapped function -- so `main.save_lesson` etc. remain
ordinary, directly-callable Python functions after decoration, exactly
like `server/tests/test_index.py` calls straight into `index.py`'s
functions without spinning up any transport.

Every test uses the `isolated_project` fixture, which monkeypatches
`CLAUDE_PROJECT_DIR` / `CLAUDE_PLUGIN_DATA` to a fresh `tmp_path` --
tests never touch this repo's own filesystem, never depend on run order,
and (since no test creates a `.git` under its tmp_path project dir,
mirroring this actual repo having none) exercise `save_lesson`'s
best-effort git-add as a real, verified no-op throughout -- see
`test_git_add_is_a_safe_no_op_when_no_git_repo_exists` for the explicit
check.

Uses the real fastembed model (no mocking), consistent with
server/tests/test_index.py's own approach.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import main

FAKE_AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# `hooks/mark_error.py` -- the real script that writes the marker file
# `clear_capture_marker` deletes -- lives outside `server/`. Invoked as a
# real subprocess (not imported) in
# `test_clear_capture_marker_matches_mark_error_pys_sanitization` below,
# the same way `hooks/tests/test_mark_and_capture.py` itself invokes it,
# so that test confirms the two independent sanitization copies
# (`hooks/mark_error.py`'s and `main._sanitize_session_id`'s) actually
# agree on a real marker filename rather than just asserting two
# hand-copied regexes match each other.
MARK_ERROR_PY = Path(__file__).resolve().parents[2] / "hooks" / "mark_error.py"


@pytest.fixture
def isolated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate a single "consuming repo" against a single shared
    "machine-wide" plugin data root, and return `(project_dir,
    cache_dir)` where `cache_dir` is the ACTUAL per-project-partitioned
    directory every MCP tool reads/writes (`main._cache_dir()`'s return
    value -- Finding C1's fix) -- not the raw, unpartitioned
    `CLAUDE_PLUGIN_DATA` root itself.

    Computing `cache_dir` via `main._cache_dir()` here (rather than just
    returning the raw `tmp_path / "plugin-data"` the old, pre-C1-fix
    fixture returned) means every existing test below that builds a path
    like `cache_dir / "index.json"` or `cache_dir / "session-....marker"`
    keeps working unchanged: it's pointed at wherever the real tool calls
    actually put those files, whatever that partitioning scheme is.
    `test_cache_is_partitioned_per_project_not_shared_across_projects`
    below is the test that exercises TWO different `isolated_project`-
    style setups sharing one raw plugin data root, which this fixture (by
    design, one project per fixture instance) cannot itself express.
    """
    project_dir = tmp_path / "consuming-repo"
    project_dir.mkdir()
    plugin_data_dir = tmp_path / "plugin-data"
    plugin_data_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(plugin_data_dir))
    cache_dir = main._cache_dir()
    return project_dir, cache_dir


def _payload(**overrides) -> dict:
    payload = dict(
        title="React useEffect infinite render loop",
        domain=["react", "javascript"],
        error_signature="Warning: Maximum update depth exceeded",
        symptom="Component re-renders in an infinite loop right after mount.",
        failed_approaches=["Removing the dependency array entirely"],
        root_cause="useEffect's state setter was called unconditionally on every render.",
        fix="Added a guard condition before calling the state setter.",
        confidence="confirmed",
    )
    payload.update(overrides)
    return payload


# --- save_lesson: scrubbing + shape -----------------------------------------


def test_save_lesson_writes_a_scrubbed_md_file_and_returns_expected_shape(
    isolated_project,
):
    project_dir, _ = isolated_project
    payload = _payload(
        symptom=f"Leaked key found in CI logs: AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}",
    )

    result = main.save_lesson(**payload)

    assert result["wrote"] is True
    assert result["id"]
    assert result["path"]
    assert "warnings" not in result

    written_path = Path(result["path"])
    assert written_path.exists()
    assert written_path.parent == project_dir / ".debug-memory" / "lessons"

    contents = written_path.read_text(encoding="utf-8")
    assert FAKE_AWS_ACCESS_KEY not in contents
    assert "[REDACTED]" in contents


def test_save_lesson_derives_tags_from_domain_error_and_title(isolated_project):
    result = main.save_lesson(
        **_payload(
            title="Kubernetes pod crashloop",
            domain=["kubernetes", "infra"],
            error_signature="CrashLoopBackOff",
        )
    )

    contents = Path(result["path"]).read_text(encoding="utf-8").lower()
    assert "## tags for retrieval" in contents
    for expected_tag in ("kubernetes", "infra", "crashloopbackoff"):
        assert expected_tag in contents


# --- Required brief integration test: save x3 (one with a leaked AWS key), --
# --- then search_lessons finds the matching one, and the leaked key never --
# --- appears in any written .md file. ---------------------------------------


def test_save_lesson_three_times_then_search_finds_the_right_one_and_secret_never_written(
    isolated_project,
):
    project_dir, _ = isolated_project

    main.save_lesson(
        **_payload(
            title="React useEffect infinite render loop",
            domain=["react", "javascript"],
            error_signature="Warning: Maximum update depth exceeded",
            symptom="Component re-renders in an infinite loop right after mount.",
            failed_approaches=["Removing the dependency array entirely"],
            root_cause="useEffect's state setter was called unconditionally on every render.",
            fix="Added a guard condition before calling the state setter.",
        )
    )
    main.save_lesson(
        **_payload(
            title="Docker build killed with out of memory error",
            domain=["docker", "ci"],
            error_signature="Killed (exit code 137)",
            symptom=(
                "Build container dies mid-build. Leaked credential in build "
                f"log: AWS_ACCESS_KEY_ID={FAKE_AWS_ACCESS_KEY}"
            ),
            failed_approaches=["Increasing the build timeout"],
            root_cause="The build step's memory usage exceeded the container's cgroup limit.",
            fix="Raised the Docker daemon's memory limit and reduced parallel build jobs.",
        )
    )
    main.save_lesson(
        **_payload(
            title="Postgres connection pool exhausted",
            domain=["postgres", "database"],
            error_signature="FATAL: remaining connection slots are reserved",
            symptom="API requests start timing out under moderate load.",
            failed_approaches=["Restarting the app servers"],
            root_cause="Each worker process opened its own unpooled database connection.",
            fix="Introduced pgbouncer as a shared connection pooler.",
        )
    )

    results = main.search_lessons(
        "useEffect causing an infinite re-render loop in a React component", k=3
    )

    assert results, "expected at least one match"
    assert results[0]["title"] == "React useEffect infinite render loop"
    for key in ("id", "title", "score", "failed_approaches", "root_cause", "fix", "path"):
        assert key in results[0]
    assert results[0]["failed_approaches"] == ["Removing the dependency array entirely"]

    # The fake AWS key from lesson #2's symptom must never survive to disk,
    # in ANY saved lesson file (read every file back and grep for it).
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    md_files = list(lessons_dir.glob("*.md"))
    assert len(md_files) == 3
    for md_file in md_files:
        assert FAKE_AWS_ACCESS_KEY not in md_file.read_text(encoding="utf-8")


# --- search_lessons ----------------------------------------------------------


def test_search_lessons_returns_empty_list_when_nothing_saved(isolated_project):
    assert main.search_lessons("anything at all") == []


def test_search_lessons_builds_index_on_demand_when_cache_is_missing(
    isolated_project,
):
    """Regression test for the Task 4 review finding: search_lessons must
    not silently return [] on a fresh clone/pull where lesson .md files
    already exist on disk (as if committed by a teammate and shared via
    git -- .debug-memory/lessons/ is git-committed) but this machine has
    no local index.json cache yet (cache_dir under CLAUDE_PLUGIN_DATA is
    machine-local and never git-committed). A silent [] here would be
    indistinguishable from "no relevant lessons exist."

    Writes a known fixture lesson .md file directly into lessons_dir --
    bypassing save_lesson entirely -- so this actually exercises "these
    were already committed by a teammate," not just "save_lesson
    happened to build the index as a side effect already" (which a test
    that called save_lesson first would not catch).
    """
    project_dir, cache_dir = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    fixture = FIXTURES_DIR / "2026-06-02-react-useeffect-infinite-loop.md"
    (lessons_dir / fixture.name).write_text(
        fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Precondition: genuinely the "fresh clone" state -- a lesson file is
    # already on disk, but no index cache exists yet.
    assert not (cache_dir / "index.json").exists()

    results = main.search_lessons(
        "useEffect causing an infinite re-render loop in a React component"
    )

    assert results, (
        "expected the pre-existing (not save_lesson-created) lesson to be "
        "found via an on-demand index build"
    )
    assert results[0]["id"] == "2026-06-02-react-useeffect-infinite-loop"
    assert (
        results[0]["title"]
        == "React useEffect infinite loop from missing dependency array"
    )
    for key in ("id", "title", "score", "failed_approaches", "root_cause", "fix", "path"):
        assert key in results[0]

    # The on-demand build must have actually written a usable cache (not
    # just returned a result some other way).
    assert (cache_dir / "index.json").exists()


# --- list_lessons -------------------------------------------------------------


def test_list_lessons_returns_all_saved_lessons(isolated_project):
    main.save_lesson(**_payload(title="Lesson A"))
    main.save_lesson(
        **_payload(title="Lesson B", error_signature="A totally different error")
    )

    listing = main.list_lessons()

    assert len(listing) == 2
    assert {entry["title"] for entry in listing} == {"Lesson A", "Lesson B"}


def test_list_lessons_on_fresh_project_returns_empty_list(isolated_project):
    assert main.list_lessons() == []


# --- git add: safe no-op when absent, attempted when present ----------------


def test_git_add_is_a_safe_no_op_when_no_git_repo_exists(isolated_project):
    project_dir, _ = isolated_project
    assert not (project_dir / ".git").exists()

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True  # never errors just because git/.git is absent


def test_git_add_is_attempted_when_git_repo_exists(
    isolated_project, monkeypatch: pytest.MonkeyPatch
):
    project_dir, _ = isolated_project
    (project_dir / ".git").mkdir()  # simulate a git repo -- no real git invoked below

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True
    assert len(calls) == 1
    assert calls[0][:4] == ["git", "-C", str(project_dir), "add"]
    assert result["path"] in calls[0]


def test_git_add_failure_never_fails_the_save(
    isolated_project, monkeypatch: pytest.MonkeyPatch
):
    project_dir, _ = isolated_project
    (project_dir / ".git").mkdir()

    def raising_run(cmd, **kwargs):
        raise FileNotFoundError("git not on PATH")

    monkeypatch.setattr(main.subprocess, "run", raising_run)

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True


# --- skipped-lessons surfacing (Task 3 review note) --------------------------


def test_save_lesson_surfaces_warnings_when_index_build_skips_a_file(isolated_project):
    project_dir, _ = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    # A pre-existing malformed lesson file that will fail to parse when
    # save_lesson rebuilds the index as part of this call.
    (lessons_dir / "2020-01-01-malformed.md").write_text(
        '---\nid: "unterminated\ntitle: "oops"\n---\n\n## Symptom\n\nx\n',
        encoding="utf-8",
    )

    result = main.save_lesson(**_payload())

    assert result["wrote"] is True
    assert "warnings" in result
    assert len(result["warnings"]) == 1
    assert "2020-01-01-malformed.md" in result["warnings"][0]


def test_save_lesson_has_no_warnings_key_when_nothing_skipped(isolated_project):
    result = main.save_lesson(**_payload())
    assert "warnings" not in result


# --- prune_lesson (Task 5) ----------------------------------------------------


def test_prune_lesson_deletes_file_and_removes_it_from_search(isolated_project):
    project_dir, _ = isolated_project
    saved = main.save_lesson(**_payload())
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lesson_path = lessons_dir / f"{saved['id']}.md"
    assert lesson_path.exists()

    query = "useEffect causing an infinite re-render loop in a React component"

    # Sanity check: the lesson is actually searchable before pruning, so
    # the post-prune assertion below is a real regression check and not
    # trivially true because the query never matched anything.
    pre_results = main.search_lessons(query)
    assert any(hit["id"] == saved["id"] for hit in pre_results)

    result = main.prune_lesson(saved["id"])

    assert result == {"deleted": True}
    assert not lesson_path.exists()

    post_results = main.search_lessons(query)
    assert all(hit["id"] != saved["id"] for hit in post_results)


def test_prune_lesson_returns_false_for_nonexistent_id_and_does_not_error(
    isolated_project,
):
    result = main.prune_lesson("2020-01-01-never-saved")
    assert result == {"deleted": False}


def test_prune_lesson_leaves_other_saved_lessons_searchable(isolated_project):
    keep = main.save_lesson(**_payload(title="Lesson to keep"))
    remove = main.save_lesson(
        **_payload(
            title="Lesson to remove",
            error_signature="A totally different, unrelated error signature",
        )
    )

    result = main.prune_lesson(remove["id"])

    assert result == {"deleted": True}
    listing = main.list_lessons()
    assert [entry["id"] for entry in listing] == [keep["id"]]


# --- prune_lesson: path-traversal rejection (security regression, Task 5 review) ---
#
# Before the fix, `id` was concatenated straight into a filesystem path
# with no validation, so `prune_lesson(id="/etc/passwd")` or a relative
# `..` id could delete an arbitrary `.md`-suffixed file anywhere the
# server process can write. Each test plants a real "victim" file
# outside the project's `lessons_dir` and asserts it survives untouched.


def test_prune_lesson_rejects_absolute_path_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    victim = project_dir / "victim.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson(str(victim))

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_prune_lesson_rejects_relative_traversal_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    # lessons_dir is project_dir/.debug-memory/lessons -- two levels deep.
    victim = project_dir / "some-marker-file.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson("../../some-marker-file")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_prune_lesson_rejects_id_with_embedded_slash(isolated_project):
    project_dir, _ = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    subdir = lessons_dir / "subdir"
    subdir.mkdir(parents=True)
    victim = subdir / "thing.md"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.prune_lesson("subdir/thing")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


# --- clear_capture_marker (Task 7 review fix) --------------------------------
#
# Moves marker deletion out of agents/lesson-distiller.md's Bash `rm -f`
# (which silently no-op'd: ${CLAUDE_PLUGIN_DATA} isn't reliably exported
# to a Bash-tool subprocess) into this MCP tool, which reuses _cache_dir
# -- already confirmed to read CLAUDE_PLUGIN_DATA successfully by every
# other tool above.


def test_clear_capture_marker_deletes_an_existing_marker(isolated_project):
    _, cache_dir = isolated_project
    marker = cache_dir / "session-abc-123.marker"
    marker.touch()

    result = main.clear_capture_marker("abc-123")

    assert result == {"cleared": True}
    assert not marker.exists()


def test_clear_capture_marker_is_a_no_op_on_a_missing_marker(isolated_project):
    _, cache_dir = isolated_project
    assert list(cache_dir.glob("*.marker")) == []

    result = main.clear_capture_marker("never-marked-session")

    assert result == {"cleared": False}
    assert list(cache_dir.glob("*.marker")) == []


def test_clear_capture_marker_leaves_other_sessions_markers_alone(isolated_project):
    _, cache_dir = isolated_project
    other_marker = cache_dir / "session-someone-else.marker"
    other_marker.touch()
    my_marker = cache_dir / "session-my-session.marker"
    my_marker.touch()

    result = main.clear_capture_marker("my-session")

    assert result == {"cleared": True}
    assert not my_marker.exists()
    assert other_marker.exists()


# --- clear_capture_marker: path-traversal rejection (mirrors prune_lesson) ---
#
# Same shape of regression coverage as prune_lesson's own path-traversal
# tests above: a hostile session_id must be rejected with ValueError
# before it ever gets a chance to build a path outside the plugin data
# directory, and any victim file placed where the traversal would have
# landed must survive untouched.


def test_clear_capture_marker_rejects_relative_traversal_session_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, cache_dir = isolated_project
    # "one level up" from cache_dir (the per-project-partitioned dir --
    # see isolated_project's own docstring) is the raw, unpartitioned
    # plugin data root isolated_project created. The exact location
    # doesn't actually matter for this test: _resolve_marker_path rejects
    # "../victim" on its name-only shape check before it ever builds or
    # resolves a candidate path, so this victim file is never at real
    # risk regardless of directory depth -- it's just some file elsewhere
    # that must survive untouched.
    victim = cache_dir.parent / "victim.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker("../victim")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_absolute_path_session_id_and_leaves_victim_file_alone(
    isolated_project,
):
    project_dir, _ = isolated_project
    victim = project_dir / "victim.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker(str(victim))

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_session_id_with_embedded_slash(isolated_project):
    _, cache_dir = isolated_project
    subdir = cache_dir / "subdir"
    subdir.mkdir()
    victim = subdir / "thing.marker"
    victim.write_text("do not delete me")

    with pytest.raises(ValueError):
        main.clear_capture_marker("subdir/thing")

    assert victim.exists()
    assert victim.read_text() == "do not delete me"


def test_clear_capture_marker_rejects_dot_dot_session_id(isolated_project):
    with pytest.raises(ValueError):
        main.clear_capture_marker("..")


def test_clear_capture_marker_rejects_empty_session_id(isolated_project):
    with pytest.raises(ValueError):
        main.clear_capture_marker("")


# --- clear_capture_marker: sanitization must match hooks/mark_error.py -------


def test_reindex_lessons_rebuilds_from_scratch_and_reports_count(isolated_project):
    project_dir, cache_dir = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    for fixture_name in (
        "2026-04-01-postgres-pool-exhausted.md",
        "2026-05-14-docker-build-oom-killed.md",
        "2026-06-02-react-useeffect-infinite-loop.md",
    ):
        fixture = FIXTURES_DIR / fixture_name
        (lessons_dir / fixture.name).write_text(
            fixture.read_text(encoding="utf-8"), encoding="utf-8"
        )

    assert not (cache_dir / "index.json").exists()

    result = main.reindex_lessons()

    assert result["indexed"] == 3
    assert result["skipped"] == []
    assert result["lessons_dir"] == str(lessons_dir)
    assert Path(result["index_path"]) == cache_dir / "index.json"
    assert (cache_dir / "index.json").exists()

    results = main.search_lessons(
        "useEffect causing an infinite re-render loop in a React component"
    )
    assert results
    assert results[0]["id"] == "2026-06-02-react-useeffect-infinite-loop"


def test_reindex_lessons_on_fresh_project_reports_zero(isolated_project):
    result = main.reindex_lessons()
    assert result["indexed"] == 0
    assert result["skipped"] == []


def test_reindex_lessons_surfaces_skipped_malformed_files(isolated_project):
    project_dir, _ = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"
    lessons_dir.mkdir(parents=True, exist_ok=True)
    (lessons_dir / "2020-01-01-malformed.md").write_text(
        '---\nid: "unterminated\ntitle: "oops"\n---\n\n## Symptom\n\nx\n',
        encoding="utf-8",
    )

    result = main.reindex_lessons()

    assert result["indexed"] == 0
    assert len(result["skipped"]) == 1
    assert "2020-01-01-malformed.md" in result["skipped"][0]["path"]


def test_reindex_lessons_picks_up_a_stale_cache_unlike_search_lessons_on_demand_build(
    isolated_project,
):
    """`search_lessons`'s on-demand index build (see its own docstring)
    only triggers when `index.json` is entirely *missing*; it
    deliberately leaves an existing-but-stale index alone.
    `reindex_lessons` is the tool for that gap: a teammate's newly-pulled
    lesson file must become searchable after a manual reindex, even
    though this machine already has a (now-stale) cache from before that
    file existed.
    """
    project_dir, cache_dir = isolated_project
    lessons_dir = project_dir / ".debug-memory" / "lessons"

    # Establish a cache before the "new" lesson file exists.
    main.save_lesson(**_payload(title="Existing lesson"))
    assert (cache_dir / "index.json").exists()

    # Simulate a teammate's lesson file landing on disk via `git pull`,
    # bypassing save_lesson so the existing cache doesn't already know
    # about it.
    fixture = FIXTURES_DIR / "2026-06-02-react-useeffect-infinite-loop.md"
    (lessons_dir / fixture.name).write_text(
        fixture.read_text(encoding="utf-8"), encoding="utf-8"
    )

    query = "useEffect causing an infinite re-render loop in a React component"

    # Not found yet: the existing cache is stale, and search_lessons's
    # on-demand build only fires when index.json is missing, not stale.
    assert not any(
        hit["id"] == "2026-06-02-react-useeffect-infinite-loop"
        for hit in main.search_lessons(query)
    )

    result = main.reindex_lessons()
    assert result["indexed"] == 2

    results = main.search_lessons(query)
    assert any(
        hit["id"] == "2026-06-02-react-useeffect-infinite-loop" for hit in results
    )


def test_clear_capture_marker_matches_mark_error_pys_sanitization(isolated_project):
    """A session_id containing characters mark_error.py sanitizes (but
    with no path separator, so it isn't the path-traversal-shaped case
    _resolve_marker_path rejects outright -- see that function's
    docstring for why those two cases are handled differently) must
    resolve to the exact same marker filename on both the write side
    (the real hooks/mark_error.py script, run as a subprocess here,
    matching how hooks/tests/test_mark_and_capture.py itself invokes it)
    and this tool's delete side -- including the per-project subdirectory
    both now partition into (Finding C1's fix).
    """
    project_dir, cache_dir = isolated_project
    session_id = "session: weird chars! ☃"

    payload = {
        "session_id": session_id,
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {},
        "tool_use_id": "toolu_01ABC123",
        "error": "boom",
    }
    env = dict(os.environ)
    # cache_dir is the per-project-PARTITIONED dir (see isolated_project's
    # own docstring); cache_dir.parent recovers the raw, unpartitioned
    # plugin data root that main._cache_dir() reads CLAUDE_PLUGIN_DATA as.
    # Setting the subprocess's CLAUDE_PLUGIN_DATA to that raw root (not to
    # cache_dir itself) and CLAUDE_PROJECT_DIR to the same project_dir
    # this test process already has -- inherited into `env` via
    # dict(os.environ), since isolated_project's own monkeypatch.setenv
    # already put it there -- makes the subprocess compute the IDENTICAL
    # _project_slug() this test's own in-process main.clear_capture_marker
    # call (below) resolves to. Getting either of those wrong would make
    # this test pass for the wrong reason (or fail) regardless of whether
    # the two sanitization copies actually agree, which is the thing this
    # test exists to check.
    env["CLAUDE_PLUGIN_DATA"] = str(cache_dir.parent)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)

    mark_result = subprocess.run(
        [sys.executable, str(MARK_ERROR_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert mark_result.returncode == 0, f"stderr: {mark_result.stderr!r}"

    markers_before = list(cache_dir.glob("*.marker"))
    assert len(markers_before) == 1, (
        f"expected exactly one marker written by mark_error.py, got {markers_before}"
    )

    result = main.clear_capture_marker(session_id)

    assert result == {"cleared": True}
    assert not markers_before[0].exists()
    assert list(cache_dir.glob("*.marker")) == []


# --- _cache_dir / _project_slug per-project partitioning (final --------------
# --- whole-project review, Finding C1) ---------------------------------------
#
# Before this fix, _cache_dir() returned ${CLAUDE_PLUGIN_DATA} directly with
# no per-project component. ${CLAUDE_PLUGIN_DATA} is one directory per
# plugin PER MACHINE (confirmed against the real on-disk layout, ~/.claude/
# plugins/data/<plugin-id>/) -- shared across every project on that machine
# that has this plugin installed, unlike CLAUDE_PROJECT_DIR which is already
# one directory per project. So a developer working in two different repos
# on the same machine got ONE shared index.json: whichever project saved a
# lesson most recently "won," and search_lessons in the OTHER project would
# silently return the wrong project's lessons (paths pointing into the
# wrong repo) instead of [] or its own project's lessons. list_lessons
# (already per-project, reads _lessons_dir() directly) and search_lessons
# (reading the shared cache) would disagree.


def test_project_slug_is_stable_and_distinct_per_project(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/dev/work/api")
    slug_1a = main._project_slug()
    slug_1b = main._project_slug()
    assert slug_1a == slug_1b, "same CLAUDE_PROJECT_DIR must yield a stable slug"

    # A different project dir that happens to share the same basename
    # ("api") must still produce a DIFFERENT slug -- proves the slug isn't
    # relying on the human-readable basename half alone for uniqueness.
    # Both slugs share the "api-" prefix (same basename); the hash
    # suffix after it is what must actually differ.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/Users/dev/personal/api")
    slug_2 = main._project_slug()
    assert slug_1a.startswith("api-") and slug_2.startswith("api-")
    assert slug_2 != slug_1a
    hash_1a = slug_1a.split("-")[-1]
    hash_2 = slug_2.split("-")[-1]
    assert hash_1a != hash_2

    # Slugs must be filesystem-safe (no path separators, no leading '.'
    # weirdness beyond what mkdir can handle) since _cache_dir() joins
    # this directly onto a Path.
    for slug in (slug_1a, slug_2):
        assert "/" not in slug
        assert slug == Path(slug).name


def test_cache_dir_fallback_when_plugin_data_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The fallback path (CLAUDE_PLUGIN_DATA unset) is already nested
    under CLAUDE_PROJECT_DIR -- i.e. already per-project on its own -- so
    _project_slug() partitioning must NOT be applied there (that would be
    redundant double-nesting). This also pins the canonical fallback leaf
    name (Finding I4): it must match hooks/mark_error.py's and
    hooks/capture.py's own fallback leaf exactly.
    """
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)

    cache_dir = main._cache_dir()

    assert cache_dir == project_dir / ".debug-memory" / main._FALLBACK_CACHE_LEAF
    assert main._FALLBACK_CACHE_LEAF == ".hindsight-cache"
    assert cache_dir.is_dir()


def test_cache_is_partitioned_per_project_not_shared_across_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Finding C1's own regression test: two different CLAUDE_PROJECT_DIR
    values (simulating two separate repos) pointed at the SAME
    CLAUDE_PLUGIN_DATA (simulating one shared machine-wide plugin data
    directory) must not see each other's lessons via search_lessons --
    and vice versa. This is exactly the test shape that structurally
    couldn't exist in any single task's own test suite: it requires
    simulating two DIFFERENT projects sharing one plugin data root, which
    the isolated_project fixture (one project per fixture instance)
    doesn't express.
    """
    shared_plugin_data = tmp_path / "shared-plugin-data"
    shared_plugin_data.mkdir()

    project_a = tmp_path / "project-a"
    project_a.mkdir()
    project_b = tmp_path / "project-b"
    project_b.mkdir()

    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(shared_plugin_data))

    # Save a lesson while "in" project A.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_a))
    main.save_lesson(**_payload(title="Project A's lesson"))

    # Switch to project B (same shared CLAUDE_PLUGIN_DATA). Its
    # list_lessons and search_lessons must NOT see project A's lesson.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_b))
    assert main.list_lessons() == []
    results_b = main.search_lessons(
        "React useEffect infinite render loop maximum update depth exceeded"
    )
    assert results_b == [], (
        "search_lessons in project B must not see project A's lesson via "
        "a shared index.json"
    )

    # Save a different lesson while "in" project B.
    main.save_lesson(
        **_payload(
            title="Project B's lesson",
            error_signature="A totally different, unrelated error signature",
        )
    )

    # Switch back to project A -- must see ONLY its own lesson, not B's.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_a))
    listing_a = main.list_lessons()
    assert [entry["title"] for entry in listing_a] == ["Project A's lesson"]

    results_a = main.search_lessons(
        "React useEffect infinite render loop maximum update depth exceeded"
    )
    assert results_a, "expected project A's own lesson to still be searchable"
    assert results_a[0]["title"] == "Project A's lesson"
    assert all(hit["title"] != "Project B's lesson" for hit in results_a)

    # And project B must still only see its own lesson too (not a fluke
    # of assertion order above).
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_b))
    listing_b = main.list_lessons()
    assert [entry["title"] for entry in listing_b] == ["Project B's lesson"]

    # The two projects' index caches must actually live in different
    # subdirectories under the shared plugin data root -- not just
    # "search happens to filter correctly for some other reason."
    project_subdirs = [p for p in shared_plugin_data.iterdir() if p.is_dir()]
    assert len(project_subdirs) == 2, (
        f"expected 2 per-project cache subdirectories under the shared "
        f"plugin data root, got {project_subdirs}"
    )
    for subdir in project_subdirs:
        assert (subdir / "index.json").exists()
