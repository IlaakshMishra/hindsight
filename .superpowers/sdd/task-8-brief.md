## Task 8: Distribution (Phase 5)

Files:
- `marketplace.json` at repo root, following whatever schema Claude Code
  plugin marketplaces require (check an existing marketplace.json from
  an installed plugin under `/Users/ilaakshmishra/.claude/plugins/cache/`
  or `/Users/ilaakshmishra/.claude/plugins/` for the exact shape before
  inventing fields) — points at this repo, lists the `hindsight` plugin.
- `README.md` — replace Task 1's stub with the full version: the
  context-economics pitch (spec section 1, condensed), one-line install
  instructions (`/plugin marketplace add ...`, `/plugin install
  hindsight`), the architecture diagram from spec section 3, and a
  placeholder note for where a demo GIF will go (do not fabricate a GIF).
- A `hindsight reindex` command: decide and document whether this is a
  `/hindsight reindex` SKILL.md subcommand (extends Task 5's skill) or a
  standalone CLI entry point (`server/reindex.py` callable via
  `python3 -m server.reindex`) — implementer's judgment, but it must call
  `index.build_index` over the full `.debug-memory/lessons/` directory
  from scratch (full rebuild, not incremental) and report how many
  lessons were indexed.
- Run `claude plugin validate` (or document exactly why it couldn't be
  run in this environment) against the repo and report the result in the
  task report; fix any validation errors it surfaces.

Sequence: last — after all other tasks.

