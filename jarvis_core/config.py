# ==============================================================================
# Author: James through Deepseek Harness
# Description: The settings: the few numbers and switches this program needs, and where they live. Exports DEFAULTS, KNOWN_TIERS, load() and the path helpers journal_path() and data_path().
# ==============================================================================

"""Settings: the few numbers and switches this program needs, and where they live.

Two things this file deliberately does NOT do:

1. It does not ship a settings file. The repository has no settings.json, and
   must never gain one. The file is written the first time you run the program,
   beside it, and .gitignore keeps it out of git. Why: a settings file that is
   tracked by git is a settings file that someone will eventually put a key in,
   and then the key is in the history forever. Rule 3 says keys stay out of
   anything the program writes to disk in plain text.

2. It does not guess. A settings.json that exists but is damaged (not JSON
   text, or not an object) stops the program with a plain message. It does not
   quietly fall back to the defaults, because "quietly" is how a security
   setting gets lost without anyone noticing.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

# These are the safe defaults, and they are the whole settings file to start
# with. Every one of them is chosen so that the wrong answer is the quiet one:
# the server listens on this PC only, the model is a local one, and the gate
# asks before anything that could touch a file.
DEFAULTS: dict[str, Any] = {
    "server": {
        # 127.0.0.1 means "this PC only". Never change this to 0.0.0.0:
        # 0.0.0.0 would also answer the home Wi-Fi and anything else that can
        # reach this machine. Rule 2 - no public tunnel, nothing shared out.
        "host": "127.0.0.1",
        "port": 4719,
    },
    "model": {
        "provider": "ollama",
        # A local address with no key. If a cloud address ever appears here,
        # the program refuses to start (see _check_local_only below).
        "base_url": "http://127.0.0.1:11434",
        "name": "qwen3:8b",
        "timeout_seconds": 120,
    },
    # What the program is allowed to do. One line per action, one of three
    # words. Anything not written down here FAILS CLOSED - see gate.py.
    "security": {
        "tiers": {
            "get_time": "auto",  # reads the clock; can touch nothing
            "write_note": "ask",  # writes a file; must be approved first
        },
        "card_ttl_seconds": 120,  # how long an approval card stays answerable
    },
    "storage": {
        # Where a note goes when the owner approves write_note. This lives
        # beside the program and is git-ignored, like settings.json itself.
        "notes_dir": "notes",
    },
    "journal": {"path": "logs/jarvis.jsonl"},
}

# The three words a tier may be. Kept here as well as in gate.py so a
# settings.json cannot invent a fourth word and have it silently mean "allow".
KNOWN_TIERS = ("never", "ask", "auto")


class ConfigError(Exception):
    """The settings could not be trusted, so the program stopped."""


def default_settings_path() -> Path:
    """Where settings.json goes the first time.

    The working directory if that looks like the program folder (that is what
    you get when you run `py -3 -m jarvis_core` from the repo root), otherwise
    next to the code. Either way .gitignore covers both places.
    """
    here = Path.cwd() / "settings.json"
    if (Path.cwd() / "jarvis_core").is_dir():
        return here
    return Path(__file__).resolve().parent.parent / "settings.json"


def _deep_fill(raw: Any, base: dict[str, Any]) -> Any:
    """Return `raw` with any missing keys filled in from `base`.

    This matters for a settings file written by an older version, or edited by
    hand until a section was deleted: a missing section must not become an
    empty one, because an empty "security" section would mean a gate with no
    actions in it - which is not dangerous here (unknown means refused), but it
    would also silently throw away settings the owner never meant to remove.
    """
    if not isinstance(raw, dict):
        return copy.deepcopy(raw)
    filled = copy.deepcopy(base)
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(filled.get(key), dict):
            filled[key] = _deep_fill(value, filled[key])
        else:
            filled[key] = value
    return filled


def _check_local_only(settings: dict[str, Any], path: Path) -> None:
    """Refuse any model address that is not this PC. Rule 1, enforced.

    Rule 1 says anything private stays on the local model. A settings file is
    easy to edit, so the check is here in code rather than only in prose: a
    name that is not 127.0.0.1, localhost or ::1 stops the program with a
    message that says what to change.
    """
    provider = str(settings["model"].get("provider", ""))
    if provider != "ollama":
        raise ConfigError(
            f"settings.json ({path}) asks for model provider {provider!r}. "
            "This build only speaks to Ollama on this PC. "
            'Set model.provider to "ollama".'
        )
    base = str(settings["model"].get("base_url", ""))
    allowed = ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")
    if not base.startswith(allowed):
        raise ConfigError(
            f"settings.json ({path}) points the model at {base!r}. "
            "This build refuses anything but this PC, because private things "
            "must never leave it (rule 1). Use http://127.0.0.1:11434."
        )


def load(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read settings, writing a fresh safe file first if none exists yet."""
    settings_path = Path(path) if path is not None else default_settings_path()

    if not settings_path.exists():
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8"
        )

    text = settings_path.read_text(encoding="utf-8").strip()
    try:
        raw = json.loads(text) if text else None
    except json.JSONDecodeError as exc:
        # Stopping is the point. A half-read settings file could mean a
        # security switch quietly defaulted back to something looser.
        raise ConfigError(
            f"settings.json ({settings_path}) is not valid JSON: {exc}. "
            "Fix it or delete it - deleting it makes a fresh safe one."
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigError(
            f"settings.json ({settings_path}) is empty or not a JSON object. "
            "Delete it and the program will write a fresh safe one."
        )

    settings = _deep_fill(raw, DEFAULTS)

    tiers = settings["security"].get("tiers")
    if not isinstance(tiers, dict):
        raise ConfigError(
            f"settings.json ({settings_path}) has security.tiers that is not a "
            "list of actions. Delete that line and a fresh one is written."
        )
    for action, tier in tiers.items():
        if tier not in KNOWN_TIERS:
            raise ConfigError(
                f"settings.json ({settings_path}) gives {action!r} the tier "
                f"{tier!r}. The only allowed words are {', '.join(KNOWN_TIERS)}."
            )

    _check_local_only(settings, settings_path)
    return settings


def journal_path(settings: dict[str, Any], settings_path: str | os.PathLike[str] | None = None) -> Path:
    """Where the one log file goes: beside settings.json, not in the repo."""
    base = Path(settings_path).parent if settings_path else default_settings_path().parent
    return base / str(settings["journal"]["path"])


def data_path(relative: str, settings_path: str | os.PathLike[str] | None = None) -> Path:
    """Turn a settings value like "notes" into a real path beside settings.json."""
    base = Path(settings_path).parent if settings_path else default_settings_path().parent
    return base / relative
