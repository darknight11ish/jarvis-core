"""The journal: one file, one JSON object per line, and no secrets in it.

Every turn and every card decision adds exactly one line to
`logs/jarvis.jsonl`. JSONL (JSON Lines) means each line is a complete little
JSON object on its own, so you can read it with your eyes, and a half-written
last line cannot corrupt the lines before it.

**How secrets are kept out, and why it is done this way.** There are two
layers, and the first one is the one that matters:

1. The entry is built from a fixed list of fields. The message and the reply
   are never written. What is written is their *length* and a *fingerprint*
   (a SHA-256 hash, cut short). A fingerprint lets you prove two turns used the
   same words without the log containing the words. This is why the log cannot
   leak a token: the text is not in the entry to begin with.
2. As a backstop, any string value that still somehow looks like a token
   (`sk-...`, `ghp_...`, `Bearer ...` and a few more) is replaced with
   "[redacted]". This exists for fields added later by someone who did not read
   this file first.

Layer 2 is not the safety net for layer 1. If someone changes `_turn` to log
the message, `test_journal.py` fails - which is the point of that test.

The log path is git-ignored. Nothing in this file ever raises: a journal that
can crash the server is a journal that gets switched off.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

# Patterns that mean "this is probably a credential". Kept short and boring on
# purpose: a clever regex here would be a second thing to get wrong.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{8,}"),
    re.compile(r"gho_[A-Za-z0-9]{8,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"hf_[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}"),
)


def fingerprint(text: Any) -> str:
    """A short, one-way fingerprint of some text. Empty text gives "-"."""
    if not isinstance(text, str) or not text:
        return "-"
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def scrub(value: Any) -> Any:
    """Replace anything token-shaped in a string, and walk that through lists
    and dicts so a nested value cannot slip past."""
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub("[redacted]", value)
        return value
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def _write(path: str | Path, entry: dict[str, Any]) -> Path | None:
    """Append one line. Returns where it went, or None if it could not be written."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(scrub(entry), ensure_ascii=False, sort_keys=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return target
    except OSError:
        # The journal is a record, not the work itself. If the disk is full or
        # the folder is read-only, the turn still happened - say nothing and
        # carry on rather than failing the request.
        return None


def turn(path: str | Path, message: Any, reply: Any, ok: bool) -> Path | None:
    """One line for one chat turn: what happened, never what was said."""
    return _write(
        path,
        {
            "kind": "turn",
            "at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "ok": bool(ok),
            # Lengths and fingerprints, not text. See the module docstring.
            "message_chars": len(message) if isinstance(message, str) else 0,
            "message_fingerprint": fingerprint(message),
            "reply_chars": len(reply) if isinstance(reply, str) else 0,
            "reply_fingerprint": fingerprint(reply),
        },
    )


def card_decision(
    path: str | Path,
    card_id: Any,
    action: Any,
    decision: Any,
    approved: bool,
) -> Path | None:
    """One line for one card decision. The action name is a name from the
    settings table, never the owner's text, so it is safe to write down."""
    return _write(
        path,
        {
            "kind": "card",
            "at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "card": str(card_id),
            "action": str(action),
            "decision": str(decision),
            "approved": bool(approved),
        },
    )


def read(path: str | Path) -> list[dict[str, Any]]:
    """Read the journal back. Used by the tests, and handy by hand."""
    target = Path(path)
    if not target.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue  # one damaged line must not hide the good ones
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries
