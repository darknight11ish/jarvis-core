"""The Ollama client. The only part of this program that talks to anything.

Two design notes worth reading:

**Why urllib, and no new library.** `requirements.txt` is empty, and that is a
feature here, not laziness. urllib comes with Python, so there is nothing to
install, nothing to pin, nothing to update, and nothing that could one day
start sending data somewhere else on its own. A one-line `requests` call would
be tidier to read, but the entire job here is "POST a small JSON object to
127.0.0.1 and read a JSON object back" - about twenty lines with urllib, and
zero bytes of dependency. The test suite also replaces urlopen with a fake, so
the tests never need a running model.

**Why it never raises.** Every function in this file returns either a result or
a plain sentence saying what is wrong. Nothing here throws. Why: the caller is
an HTTP handler, and a raised exception in a handler turns into an unhelpful
500 with no explanation. A beginner running this should be told "Ollama is not
answering on http://127.0.0.1:11434 - start it with `ollama serve`", not
handed a stack trace.

Rule 1 lives here too: the address is checked, and only ever points at this PC.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

# A question longer than this is refused with a plain message rather than sent.
MAX_MESSAGE_CHARS = 4000

# This is sent as the first message of every chat. It says plainly that this
# build has no tools and cannot act, so a model does not invent an action it
# cannot take. A foundation that lets the model pretend to send an email is
# worse than one with no email feature at all.
SYSTEM_PROMPT = (
    "You are Jarvis, a private assistant running on the owner's own PC. "
    "You answer in plain, short sentences for a beginner: say what a thing is "
    "before using its name. This build can only talk. It has no tools, cannot "
    "read files, cannot send email, cannot search the web and cannot change "
    "anything on this PC. If you are asked to do one of those things, say "
    "plainly that this build cannot do it yet rather than pretending you did."
)


def _base_url(settings: dict[str, Any]) -> str:
    return str(settings["model"]["base_url"]).rstrip("/")


def _local_only(settings: dict[str, Any]) -> str | None:
    """Return a plain refusal if the model address is not this PC, else None."""
    host = (urlparse(_base_url(settings)).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return (
            f"The model address ({_base_url(settings)}) is not on this PC, so "
            "this build will not use it. Private things stay local (rule 1)."
        )
    return None


def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any] | str:
    """POST JSON and read JSON back. Returns a dict, or a sentence on failure."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        path,
        data=body,
        # A fixed method and a JSON content type. Nothing else is sent: no
        # cookies, no auth header, no user agent string worth reading.
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        # The response is read inside the `with` so the socket is closed even
        # if the JSON below turns out to be nonsense.
        with urllib.request.urlopen(request, timeout=timeout) as handle:
            text = handle.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return f"The model refused the request (HTTP {exc.code} {exc.reason})."
    except urllib.error.URLError as exc:
        return f"Could not reach the model: {exc.reason}. Is Ollama running?"
    except OSError as exc:
        return f"Could not reach the model: {exc}. Is Ollama running?"
    except TimeoutError:
        return f"The model did not answer within {timeout:g} seconds."

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return "The model sent back something that was not JSON."
    if not isinstance(parsed, dict):
        return "The model sent back JSON that was not an object."
    return parsed


def _get(url: str, timeout: float) -> dict[str, Any] | str:
    """GET JSON. Same error handling as _post, for the same reason."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as handle:
            text = handle.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return f"Could not reach the model: {exc.reason}. Is Ollama running?"
    except OSError as exc:
        return f"Could not reach the model: {exc}. Is Ollama running?"
    except TimeoutError:
        return f"The model did not answer within {timeout:g} seconds."
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return "The model list was not JSON."
    return parsed if isinstance(parsed, dict) else "The model list was not an object."


def check(settings: dict[str, Any]) -> dict[str, Any]:
    """Say honestly whether the model is there, and which names it has.

    This is what /api/status answers with. It never guesses and never pretends:
    if Ollama is not running you get reachable=False and a sentence saying so.
    """
    name = str(settings["model"]["name"])
    refusal = _local_only(settings)
    if refusal:
        return {"reachable": False, "model": name, "model_present": False, "detail": refusal}

    timeout = min(float(settings["model"]["timeout_seconds"]), 5.0)
    answer = _get(f"{_base_url(settings)}/api/tags", timeout)
    if isinstance(answer, str):
        return {"reachable": False, "model": name, "model_present": False, "detail": answer}

    models = answer.get("models")
    names = []
    if isinstance(models, list):
        for entry in models:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.append(entry["name"])

    if not names:
        return {
            "reachable": True,
            "model": name,
            "model_present": False,
            "detail": "Ollama is running but has no models yet. "
                      f"Install one with: ollama pull {name}",
        }
    if name not in names:
        return {
            "reachable": True,
            "model": name,
            "model_present": False,
            "detail": f"Ollama is running, but {name} is not installed. "
                      f"Either run: ollama pull {name} "
                      f"- or put a name you do have into settings.json. "
                      f"Installed: {', '.join(sorted(names))}",
        }
    return {
        "reachable": True,
        "model": name,
        "model_present": True,
        "detail": f"{name} is installed and ready.",
        "installed": sorted(names),
    }


def chat(message: Any, settings: dict[str, Any]) -> dict[str, Any]:
    """Ask the local model one question. Returns {"ok", "reply"/"error", "model"}.

    Note what is NOT sent: no conversation history, no file contents, no
    remembered facts. Just the system line above and the one message. There is
    nothing to leak because nothing else is collected in the first place.
    """
    name = str(settings["model"]["name"])

    if not isinstance(message, str) or not message.strip():
        return {"ok": False, "error": "The message must be a non-empty string.", "model": name}
    if len(message) > MAX_MESSAGE_CHARS:
        return {
            "ok": False,
            "model": name,
            "error": f"That message is {len(message)} characters. The limit is "
                     f"{MAX_MESSAGE_CHARS} - please send a shorter one.",
        }

    refusal = _local_only(settings)
    if refusal:
        return {"ok": False, "error": refusal, "model": name}

    answer = _post(
        f"{_base_url(settings)}/api/chat",
        {
            "model": name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            # stream:false means one complete JSON answer instead of a dribble
            # of fragments. Simpler to read and to test; streaming can come
            # later if it is ever wanted.
            "stream": False,
        },
        float(settings["model"]["timeout_seconds"]),
    )
    if isinstance(answer, str):
        return {"ok": False, "error": answer, "model": name}

    reply = answer.get("message", {}).get("content") if isinstance(answer.get("message"), dict) else None
    if not isinstance(reply, str) or not reply.strip():
        return {
            "ok": False,
            "model": name,
            "error": "The model answered, but there was no text in the answer.",
        }
    return {"ok": True, "reply": reply, "model": name}
