"""Pins `hooks/hooks.json`'s actual launcher shape.

Regression guard for a real bug: `hooks.json` originally invoked every
hook script via bare `command: "python3"`. That broke for users whose
only interpreter on PATH is named `python`, not `python3` (common on some
Windows/Linux setups) -- the hook failed to launch at all, silently (no
nudge, no marker, no capture) rather than erroring visibly to the
developer. Fixed by routing every hook through `command: "uv"`,
`args: ["run", "--no-project", <script>, ...]` instead -- `uv` is already
a hard prerequisite for this plugin (the MCP server needs it) and
resolves a real Python regardless of what's named what on PATH.

This test does not re-invoke the scripts (that's `test_retrieve.py` /
`test_mark_and_capture.py`'s job) -- it only asserts the config shape
itself, so a future edit that reverts to bare `python3` (or any other
non-`uv` launcher) fails loudly here instead of silently reintroducing
the bug on some users' machines.

Runnable directly (`python3 hooks/tests/test_hooks_json.py`) or via
pytest -- no non-stdlib imports.
"""

from __future__ import annotations

import json
from pathlib import Path

HOOKS_JSON = Path(__file__).resolve().parent.parent / "hooks.json"


def _load_hook_commands() -> list[dict]:
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    commands = []
    for event_groups in data["hooks"].values():
        for group in event_groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command", (
                    f"expected a command hook, got {hook['type']!r}: {hook}"
                )
                commands.append(hook)
    return commands


def test_every_hook_is_launched_via_uv_run_not_bare_python() -> None:
    commands = _load_hook_commands()
    assert commands, "expected at least one hook entry in hooks.json"
    for hook in commands:
        assert hook["command"] == "uv", (
            f"hook launcher regressed to a non-uv command: {hook!r} -- "
            "bare python3/python breaks for users whose interpreter isn't "
            "named the one hardcoded here (the original bug this test "
            "guards against)"
        )
        args = hook["args"]
        assert args[:2] == ["run", "--no-project"], (
            f"expected 'uv run --no-project <script>', got args={args!r}"
        )


def test_every_hook_script_path_uses_literal_plugin_root_var() -> None:
    commands = _load_hook_commands()
    for hook in commands:
        script_arg = hook["args"][-1]
        assert script_arg.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"), (
            f"hook script path must use the literal ${{CLAUDE_PLUGIN_ROOT}} "
            f"token, not a resolved machine path: {script_arg!r}"
        )
        assert script_arg.endswith(".py")


def test_three_hook_scripts_are_all_registered() -> None:
    commands = _load_hook_commands()
    script_names = {hook["args"][-1].rsplit("/", 1)[-1] for hook in commands}
    assert script_names == {"retrieve.py", "mark_error.py", "capture.py"}, (
        f"expected exactly retrieve.py, mark_error.py, capture.py "
        f"registered as hooks, got {script_names!r}"
    )


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    if failures:
        raise SystemExit(f"{failures} test(s) failed")
    print("All tests passed")
