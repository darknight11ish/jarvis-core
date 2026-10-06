# ==============================================================================
# Author: James through Deepseek Harness
# Description: The two example actions, kept boring on purpose so they prove the gate instead of being interesting themselves. Exports get_time, write_note, their card text in ACTION_INFO, and registry(), the table of what this build can actually run.
# ==============================================================================

"""The two example actions. There are exactly two, on purpose.

The point of this file is to prove the gate works, not to give Jarvis things to
do. Both actions are boring on purpose: if they were interesting you would be
reading about them instead of about the gate.

  get_time    tier "auto"  - looks at the clock on this PC. It cannot read a
                             file, open a socket, or change anything, which is
                             the only reason "auto" is honest for it.
  write_note  tier "ask"   - writes one small text file into notes/. It waits
                             for a card every single time. There is no "always
                             allow" and no remembered permission, because a
                             permission you gave once is not a permission you
                             gave today.

Adding a third action means three edits: a function here, its name and tier in
settings.json, and its title in the ACTION_INFO table below. The gate refuses
anything that skips the settings edit, so it cannot be added by accident.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Callable

from . import config

# The plain-English title and one-line description shown on the card and in
# /api/status. Why inside the program rather than in settings.json: this text
# is what the owner reads before saying yes, so it should be written by the
# person who wrote the action, and reviewed with it.
ACTION_INFO: dict[str, dict[str, str]] = {
    "get_time": {
        "title": "Read the clock on this PC",
        "shows": "Today's date and the time right now.",
    },
    "write_note": {
        "title": "Write a note file on this PC",
        "shows": "The file path and the first part of the text it will write.",
    },
}


class ActionError(Exception):
    """The action was called with something it cannot use.

    This is a failure, not a refusal: the gate already said yes. It still gets
    reported plainly, because a half-done action that says nothing is worse
    than one that says what went wrong.
    """


def _reject_unknown_args(args: dict[str, Any], allowed: tuple[str, ...]) -> None:
    """Refuse arguments the action does not understand.

    Why bother: if an action ignores what it does not know, a caller can pass
    `{"path": "C:/Windows/..."}` to something that happens to ignore a "path"
    key today, and the day someone adds path support it silently starts
    working. Refusing is one line and closes that door.
    """
    unexpected = sorted(set(args) - set(allowed))
    if unexpected:
        raise ActionError(
            f"This action does not understand the argument(s) "
            f"{', '.join(repr(name) for name in unexpected)}. "
            f"It accepts: {', '.join(allowed) or 'none'}."
        )


def get_time(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the local date and time. Tier: auto."""
    args = dict(args or {})
    _reject_unknown_args(args, ())
    now = _dt.datetime.now().astimezone()
    return {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": now.strftime("%A"),
        "zone": now.tzname() or "unknown",
    }


def write_note(
    args: dict[str, Any] | None = None,
    *,
    settings: dict[str, Any] | None = None,
    settings_path: str | None = None,
) -> dict[str, Any]:
    """Write one small note file into notes/. Tier: ask.

    `settings` and `settings_path` are how the tests point this at a temporary
    folder. In normal use neither is passed and the note lands beside the
    program.
    """
    args = dict(args or {})
    _reject_unknown_args(args, ("text",))

    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ActionError('write_note needs some text, like {"text": "buy milk"}.')
    if len(text) > 2000:
        # A limit rather than a truncation, so nobody loses the end of a note
        # without being told.
        raise ActionError(f"That note is {len(text)} characters; the limit is 2000.")

    settings = settings or config.load(settings_path)
    notes_dir = config.data_path(str(settings["storage"]["notes_dir"]), settings_path)
    notes_dir.mkdir(parents=True, exist_ok=True)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = notes_dir / f"note-{stamp}.txt"
    target.write_text(text + "\n", encoding="utf-8")

    return {"written": str(target), "chars": len(text)}


def registry() -> dict[str, Callable[..., dict[str, Any]]]:
    """The functions this build can actually run, by name.

    The gate decides whether a name may run. This table is the other half: what
    that name would do. A name can be in settings and missing here, and that is
    fine - the gate lets it through and the caller gets a plain "there is no
    such action in this build". Keeping the two tables separate means a
    settings typo cannot invent a capability.
    """
    return {"get_time": get_time, "write_note": write_note}
