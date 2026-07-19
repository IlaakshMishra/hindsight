#!/usr/bin/env python3
"""Standalone CLI: full rebuild of the hindsight local similarity index.

Usage (`uv`, not bare `python3` -- this imports `index.py`, which needs
`fastembed`, and `main.py`, which needs `mcp`; see `server/requirements.txt`
and this repo's own `.mcp.json`, which launches the MCP server the exact
same way):

    uv run --no-project --with-requirements server/requirements.txt \\
        server/reindex.py [--lessons-dir DIR] [--cache-dir DIR]

Always a FULL rebuild -- `index.build_index` re-reads every `*.md` file
under `lessons_dir` from scratch every time it's called (see that
function's own docstring); this script never attempts an incremental
update. Prints how many lessons were indexed and, if any lesson files
failed to parse, which ones and why (`skipped`, same shape
`save_lesson`'s own `warnings` surfaces).

Path resolution: `--lessons-dir`/`--cache-dir` are optional. Omitted,
they fall back to `main.py`'s own `_lessons_dir()`/`_cache_dir()` -- the
exact same `CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA`-then-cwd resolution
every MCP tool in this server already uses (imported from `main.py`
rather than re-implemented a third time here, matching this codebase's
existing "one parser"/"one sanitizer" preference -- see e.g.
`schema.parse_lesson`'s and `main._sanitize_session_id`'s own docstrings
for the same reasoning applied elsewhere). A run from inside a real
Claude Code project directory with those two env vars actually exported
(or set by hand) resolves the same `lessons_dir`/`cache_dir` the MCP
server itself reads from and writes to.

IMPORTANT -- this is NOT what `/hindsight reindex` calls. `${CLAUDE_
PLUGIN_DATA}` (and `${CLAUDE_PROJECT_DIR}`) are only reliably exported as
real environment variables to a hook process or an MCP/LSP server
subprocess -- NOT to a `Bash`-tool invocation made during a normal agent
turn (see `main.py`'s own module docstring, and the Task 7 review fix for
`clear_capture_marker`, which hit exactly this failure mode: a `Bash`
`rm -f "${CLAUDE_PLUGIN_DATA}/..."` silently no-op'd because the shell
never saw the variable, and the fix was to move that logic into the MCP
server process instead). Running *this* script via the `Bash` tool from
inside a live session would hit the identical problem -- `_lessons_dir()`/
`_cache_dir()`'s env-var reads would silently fail and fall back to
cwd-relative directories that do NOT match the real, Claude-Code-managed
plugin data directory the running MCP server actually reads its index
cache from. It would look like it worked (a plausible "N lessons
indexed" message) while rebuilding an index nobody ever searches.

`skills/hindsight/SKILL.md`'s `/hindsight reindex` subcommand therefore
calls the `reindex_lessons` MCP tool (`server/main.py`) instead, which
runs inside the MCP server process and always resolves the real env vars
correctly -- see that tool's own docstring for the full reasoning. This
script exists for everything else a full rebuild is useful for outside
that specific in-session context: CI, a maintainer's own terminal with
`CLAUDE_PROJECT_DIR`/`CLAUDE_PLUGIN_DATA` exported by hand, or pointed at
an explicit `--lessons-dir`/`--cache-dir` pair (e.g. for local testing
against a scratch fixtures directory, independent of any real plugin
install).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import index
from main import _cache_dir, _lessons_dir


def reindex(lessons_dir: Path, cache_dir: Path) -> dict:
    """Rebuild the index at `cache_dir` from every lesson `.md` file
    under `lessons_dir`, and return a summary dict: `{"indexed": <N>,
    "skipped": [...], "lessons_dir": <str>, "index_path": <str>}` -- the
    exact same shape `server/main.py`'s `reindex_lessons` MCP tool
    returns (this function IS that tool's implementation, extracted so
    both the CLI below and, in principle, a test can call it directly
    without going through `argparse`).
    """
    index_path = index.build_index(lessons_dir, cache_dir)
    data = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "indexed": len(data.get("records", [])),
        "skipped": data.get("skipped", []),
        "lessons_dir": str(lessons_dir),
        "index_path": str(index_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Full rebuild of the hindsight local similarity index from "
            "every lesson .md file on disk."
        )
    )
    parser.add_argument(
        "--lessons-dir",
        type=Path,
        default=None,
        help=(
            "Directory of lesson .md files to index. Defaults to the same "
            "CLAUDE_PROJECT_DIR-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/lessons under the current "
            "working directory if CLAUDE_PROJECT_DIR is unset)."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write index.json to. Defaults to the same "
            "CLAUDE_PLUGIN_DATA-based resolution main.py's MCP tools use "
            "(falls back to ./.debug-memory/.hindsight-cache if unset, or "
            "${CLAUDE_PLUGIN_DATA}/<project slug>/ if set -- see "
            "this script's module docstring for why that default will NOT "
            "match a real installed plugin's actual cache directory unless "
            "CLAUDE_PLUGIN_DATA is exported."
        ),
    )
    args = parser.parse_args()

    lessons_dir = args.lessons_dir if args.lessons_dir is not None else _lessons_dir()
    cache_dir = args.cache_dir if args.cache_dir is not None else _cache_dir()

    result = reindex(lessons_dir, cache_dir)

    print(f"Reindexed {result['indexed']} lesson(s) from {result['lessons_dir']}")
    if result["skipped"]:
        print(f"Skipped {len(result['skipped'])} file(s) that failed to parse:")
        for entry in result["skipped"]:
            print(f"  - {entry['path']}: {entry['error']}")
    print(f"Index written to {result['index_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
