## Task 5: `/hindsight` manual skill + list/prune tools

Files:
- Add `prune_lesson(id: str) -> {deleted: bool}` to `server/main.py` /
  `store.py` (deletes the `.md` file, rebuilds the index).
- `skills/hindsight/SKILL.md` — a skill (slash command `/hindsight`) with
  subcommands: `/hindsight save` (walks the user through providing the
  save_lesson fields, calls the tool), `/hindsight search <query>` (calls
  search_lessons, prints results with scores), `/hindsight list` (calls
  list_lessons), `/hindsight prune <id>` (confirms, then calls
  prune_lesson). Follow this plugin repo's existing skill file
  conventions if any exist yet (there won't be — base it on the
  `SKILL.md` frontmatter shape used by other installed plugins under
  `/Users/ilaakshmishra/.claude/plugins/cache/*/skills/*/SKILL.md` —
  read one for the exact frontmatter fields expected, e.g. `name`,
  `description`).

Tests: extend `server/tests/` for `prune_lesson` (save a fixture lesson,
prune it, assert the file is gone and the index no longer returns it for
a previously-matching query).

Sequence: after Task 4.

---

## Hook-event correction (binding — supersedes spec section 7)

Verified 2026-07-18 against https://code.claude.com/docs/en/hooks.md:

- `PostToolUseFailure` **is** a real event (fires after a tool call
  fails) — use it directly, no need to inspect `PostToolUse` for errors.
- `SessionEnd` does **not** support `hookSpecificOutput.additionalContext`
  — it's cleanup/logging only, no live model turn left to act on
  anything injected. **Do not use it for capture.**
- `Stop` **does** support `additionalContext` ("the conversation
  continues so Claude can act on the feedback") — this is the correct
  event for the capture nudge, not `SessionEnd`.
- `UserPromptSubmit` supports `additionalContext` too (available if a
  future task wants prompt-side pattern matching, per spec's optional
  mention — not required for Phase 3/4 below).

`hookSpecificOutput` JSON shape for all of the above:
```json
{"hookSpecificOutput": {"hookEventName": "<EventName>", "additionalContext": "..."}}
```
exit code 0.

Matcher syntax in `hooks.json` (for `PostToolUseFailure`/`PostToolUse`):
exact tool name (`"Bash"`), list (`"Edit|Write"`), regex (`"^Notebook"`),
or MCP pattern (`"mcp__servername__.*"`).

---

