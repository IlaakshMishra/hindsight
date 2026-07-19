## Task 7: Automatic capture — session marker, Stop hook, lesson-distiller agent (Phase 4)

Files:
- `hooks/hooks.json` — add two more entries:
  1. `PostToolUseFailure` hook (can reuse or extend `retrieve.py`, or a
     separate `hooks/mark_error.py`) that, in addition to Task 6's
     retrieve nudge, writes a per-session marker file to
     `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` (session_id from
     the hook payload's `session_id` field). Content doesn't matter, only
     existence. This must not fail or block if the directory doesn't
     exist yet — create it.
  2. `Stop` hook: `hooks/capture.py`. Reads the same `session_id` from
     its payload, checks whether
     `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker` exists. If not,
     exit 0 with no output (no-op — nothing to capture). If it exists,
     emit:
     ```json
     {"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "This session hit a tool failure earlier. If it's now resolved, the lesson-distiller agent (subagent_type: lesson-distiller) can turn it into a saved lesson from a concise summary — error signature, symptom, failed approaches, root cause, fix, with secrets/tokens/customer data excluded. Not worth dispatching if the error wasn't actually resolved this session."}}
     ```
     (Phrased factually, not imperatively, per the Task 6 correction above
     — same reasoning: an imperative "dispatch the agent... exclude
     secrets..." risks triggering Claude's prompt-injection defenses and
     getting surfaced as raw text instead of acted on.)
     Do NOT delete the marker file from inside this hook — deletion must
     only happen after a real save, so an unresolved session's next
     `Stop` firing (if the session continues) can still trigger capture
     once it IS resolved. Deletion of the marker is the distiller agent's
     job (see below), not the hook's.
- `agents/lesson-distiller.md` — a plugin-provided subagent (frontmatter:
  `name: lesson-distiller`, `description`, tool access limited to
  whatever's needed to call the `hindsight` MCP tools plus `Read` if it
  needs to re-check anything). Body instructs it to: take the incident
  summary it was dispatched with, structure it into the exact
  `save_lesson` input shape from Global Constraints (title, domain[],
  error_signature, symptom, failed_approaches[], root_cause, fix,
  confidence — mark `probable` unless the fix was actually verified
  working), never fabricate a failed-approach that wasn't actually tried,
  never include secrets/tokens/customer data (belt-and-suspenders on top
  of server-side `scrub.py`), call `save_lesson`, then delete the
  session's marker file at `${CLAUDE_PLUGIN_DATA}/session-<session_id>.marker`
  (the session_id is passed to it in the dispatch prompt) so a later
  `Stop` in the same session doesn't re-trigger.

Tests:
- `hooks/tests/test_mark_and_capture.py` (or shell-based, implementer's
  choice): simulate `PostToolUseFailure` → assert marker file created;
  simulate `Stop` with that session_id → assert the capture
  `additionalContext` is emitted; simulate `Stop` with a session_id that
  has no marker → assert stdout is empty / no `additionalContext` (the
  no-op case from spec section 10's "no-op tests").

Sequence: after Task 6 (shares hook plumbing) and after Task 4 (the agent
dispatches `save_lesson`, which must be real by then).

---

