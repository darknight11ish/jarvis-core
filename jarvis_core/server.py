# ==============================================================================
# Author: James through Deepseek Harness
# Description: The HTTP server: five routes on this PC only, and a plain refusal for everything else. Exports JarvisServer, JarvisHandler, build_parser() and main(), plus MAX_BODY_BYTES, CLIENT_HEADER and PAGE_PATH.
# ==============================================================================

"""The HTTP server: five routes, and a refusal for everything else.

    GET  /                    - the one page you can type in (HTML, not JSON)
    GET  /api/status          - is the model there, and what does this build do?
    POST /api/chat            - ask the model one question
    GET  /api/card/<id>       - has the owner answered that card yet?
    POST /api/card/<id>       - answer a card: approve or deny
    (anything else)           - 404 with a plain sentence. Fails closed.

Why `http.server` from the standard library, and no web framework: the whole
job is five routes on the loopback address, four of them reading and writing
JSON. A framework would add a dependency, a version to pin, and a hundred pages
of behaviour to learn, to save maybe forty lines here. If this ever needs more
than five routes, that is the moment to reconsider - and there is a note in the
README saying so.

The page at `GET /` is the one route that answers HTML instead of JSON. It
exists because typing a `curl` command into a second window is not something a
person should have to do. It is deliberately the *only* convenience the page
adds: it is a text box that calls POST /api/chat, the same route `curl` calls,
and it can do nothing else. It cannot list cards, cannot approve one, and
cannot name an action. The card flow is unchanged, and the gate is exactly as
strict as it was. The HTML lives in `page.html` beside this file rather than in
a string here: a `.bat` launcher cannot safely quote a page with `<` and `>`
in it, so the page is one readable file that both the server and the double-
click can point at.

The shape of an `ask` action through HTTP is worth reading twice, because it is
the whole design in four steps:

  1. POST /api/chat with {"message": "...", "action": "write_note", ...}
  2. The action is tier "ask", so a card is raised. The answer comes straight
     back - HTTP 202 - with {"waiting_for_approval": "<id>", "then": "..."}.
     Nothing has run. The *card* is what waits, not this request.
  3. POST /api/card/<id> with {"decision": "approve"} runs the action and puts
     the result on the card. {"decision": "deny"} runs nothing at all.
  4. GET /api/card/<id> at any time says where the card got to: pending,
     approved, denied or expired.

Why the request does not block until the owner decides: a blocked request is a
connection held open for as long as a person takes to think, which means a
timeout somewhere and a retry that is hard to reason about. A card id that you
can poll is a plain, stateless exchange, and it lets the card expire on its own
clock rather than the caller's. The waiting still happens - cards.wait_for()
blocks a thread properly if you ever want that - it just is not tied to an open
socket.

Two deliberate choices about what this server will NOT do:

* It binds 127.0.0.1 only. Not 0.0.0.0, not the LAN address, not a tunnel.
  Rule 2. There is a test that proves the setting, and the server itself is
  written so the host comes from settings and the default is loopback.
* It logs nothing to the console. The only record is the JSONL journal, which
  is written to strip secrets. A second, unreviewed log is exactly how a token
  ends up in a file you forgot about.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from . import __version__, actions, cards, config, gate, journal, model

# A request body bigger than this is refused before it is read into memory.
MAX_BODY_BYTES = 64 * 1024

# Sent on every answer so a front end can tell it is talking to this build.
CLIENT_HEADER = "X-Jarvis-Client"

# The one page you can type in, kept as a file so it can be read on its own.
PAGE_PATH = Path(__file__).resolve().parent / "page.html"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"


class JarvisServer(ThreadingHTTPServer):
    """A threaded HTTP server. Nothing blocks any more, so this is now about
    two callers at once rather than about getting round a deadlock - but it
    costs nothing and it is the right shape for a server a phone might talk to.

    daemon_threads means a request in flight cannot keep the program alive when
    you press Ctrl+C.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], settings: dict[str, Any], settings_path: str | None):
        """Build everything a request will need, once, before listening.

        The journal path, the card store with its time limit from settings, and
        this build's table of runnable actions are all decided here rather than
        on every request. `address` is the (host, port) from settings, which is
        127.0.0.1 unless someone changed it.
        """
        super().__init__(address, JarvisHandler)
        self.settings = settings
        self.settings_path = settings_path
        self.journal_path = config.journal_path(settings, settings_path)
        ttl = int(settings["security"]["card_ttl_seconds"])
        self.card_store = cards.CardStore(ttl_seconds=ttl)
        self.action_functions = actions.registry()


class JarvisHandler(BaseHTTPRequestHandler):
    """Handles one HTTP request, and keeps nothing that outlives it.

    Anything a request needs is read from the server object it was given. Each
    route is matched exactly, and anything else gets a 404 that says why - the
    same fail-closed habit the gate has.
    """

    server_version = f"jarvis-core/{__version__}"
    sys_version = ""  # do not hand out the Python version to anyone asking

    # -- plumbing --------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        """Stay quiet on the console. The journal is the only record."""
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        """Write one JSON answer back to the caller.

        The length header is measured on encoded bytes, so it stays right when
        the text has an accent or an emoji in it.
        """
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        """Write the one HTML answer this server has: the page at GET /.

        The only difference from _send is the content type, and it matters: with
        `application/json` on a browser's request you would get a download
        prompt instead of a page.
        """
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", HTML_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, message: str, **extra: Any) -> None:
        """Every refusal looks the same and says why in words.

        Fail closed means the default answer is no with an explanation, never a
        guess. `ok` is always present so a caller can branch on one field, and
        so is `ran` - "did anything happen" is the question a caller actually
        cares about, and the answer to a refusal is always no.
        """
        self._send(status, {"ok": False, "error": message, "ran": False, **extra})

    def _read_json(self) -> tuple[dict[str, Any] | None, str | None]:
        """Read the request body as one JSON object, or explain why not."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            return None, "The Content-Length header is not a number."
        if length <= 0:
            return None, "The request had no body. Send a JSON object."
        if length > MAX_BODY_BYTES:
            return None, f"The request body is larger than {MAX_BODY_BYTES} bytes."

        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return None, "The request body was not UTF-8 text."
        except json.JSONDecodeError as exc:
            return None, f"The request body was not valid JSON: {exc.msg}."
        if not isinstance(parsed, dict):
            return None, "The request body must be a JSON object, like {\"message\": \"hi\"}."
        return parsed, None

    # -- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - the name is fixed by http.server
        """Serve the three routes that only read: the page, /api/status and
        /api/card/<id>.

        None of them can change anything, so none needs an approval. Anything
        else gets a 404 listing the five routes this build does answer, which
        is more use to a beginner than a bare "not found".
        """
        route = urlparse(self.path).path
        if route == "/":
            self._page()
            return
        if route == "/api/status":
            self._status()
            return
        if route.startswith("/api/card/"):
            self._card_get(unquote(route[len("/api/card/"):]))
            return
        self._fail(
            404,
            f"There is no route called {route!r}. This build answers GET /, "
            "GET /api/status, GET /api/card/<id>, POST /api/chat and "
            "POST /api/card/<id> - and nothing else.",
        )

    def do_POST(self) -> None:  # noqa: N802
        """Serve the two routes that can do something: /api/chat and
        /api/card/<id>.

        "Can do something" is not the same as "does something". A chat runs
        nothing unless the caller names an action, and a card runs nothing
        unless the decision is an approval. Any other path is a 404, refused
        rather than guessed at.
        """
        route = urlparse(self.path).path
        if route == "/api/chat":
            self._chat()
            return
        if route.startswith("/api/card/"):
            self._card_post(unquote(route[len("/api/card/"):]))
            return
        self._fail(
            404,
            f"There is no route called {route!r}. Refusing rather than "
            "guessing what you meant.",
        )

    # -- handlers --------------------------------------------------------

    def _page(self) -> None:
        """GET /. The one page you can type in, and the only HTML here.

        It is served from a file and never built from anything a caller sent,
        so there is nothing here to inject into and no setting of yours in it.
        The page does nothing the command line could not do: it POSTs to
        /api/chat with {"message": "..."} and prints the reply. Notably absent,
        and deliberately so: no route that lists cards, none that approves one,
        and none that names an action.

        A missing page.html would be a real fault, so it is refused in plain
        words rather than answered with a blank 500.
        """
        try:
            page = PAGE_PATH.read_text(encoding="utf-8")
        except OSError as exc:
            self._fail(500, f"The page file {PAGE_PATH.name} could not be read: {exc}")
            return
        self._send_html(page)

    def _status(self) -> None:
        """GET /api/status. Always 200, and never a guess.

        It reports what the model layer actually found - reachable, installed,
        or a sentence saying what is wrong - plus the tier table as it stands,
        and two honest lists: what this build does, and what it does not.
        """
        settings = self.server.settings
        state = model.check(settings)
        tiers = gate.tier_table(settings)
        self._send(
            200,
            {
                "ok": True,
                "version": __version__,
                "model": {
                    "name": state["model"],
                    "local_only": True,
                    "reachable": bool(state["reachable"]),
                    "model_present": bool(state["model_present"]),
                    "detail": state["detail"],
                },
                "actions": {
                    name: {
                        "tier": tier,
                        "meaning": gate.TIER_MEANINGS.get(tier, tier),
                        "title": actions.ACTION_INFO.get(name, {}).get("title", ""),
                    }
                    for name, tier in sorted(tiers.items())
                },
                "card_ttl_seconds": int(settings["security"]["card_ttl_seconds"]),
                "does": [
                    "answers on 127.0.0.1 only, so nothing outside this PC can reach it",
                    "talks to a local model (Ollama) and to nothing else",
                    "runs named actions only when its tier allows it",
                    "asks with a card before anything that can change something",
                    "writes one JSONL log that never contains your words",
                ],
                "does_not": [
                    "no cloud model, no API keys, no telemetry (rule 1)",
                    "no public tunnel, nothing shared off this PC (rule 2)",
                    "no email, calendar, files outside notes/, web search, voice or screen reading",
                    "no memory, no plugins, no MCP servers (not built yet - see README)",
                    "no streaming answers: one complete reply per request",
                ],
            },
        )

    def _card_get(self, card_id: str) -> None:
        """GET /api/card/<id>: has the owner answered that card yet?

        200 with the card, or 404 if no card has that id. Polling this is how a
        caller waits for a person to decide without holding a connection open.
        """
        card = self.server.card_store.get(card_id)
        if card is None:
            self._fail(404, f"There is no card with id {card_id!r}.")
            return
        self._send(200, {"ok": True, "card": card})

    def _card_post(self, card_id: str) -> None:
        """POST /api/card/<id>: the owner's answer, approve or deny.

        It refuses a body with no "decision", a decision that is not exactly
        "approve" or "deny", and a card that is unknown, already answered or
        expired. Only an approval on a card that was still pending runs
        anything: a late "yes" answers 409 and runs nothing, and the journal
        still records it, because a late approval is worth a record.
        """
        body, problem = self._read_json()
        if problem:
            self._fail(400, problem)
            return
        if "decision" not in body:
            self._fail(400, 'The body needs a "decision" field, "approve" or "deny".')
            return

        card, error = self.server.card_store.decide(card_id, body["decision"])
        if card is None:
            self._fail(404 if "Unknown card" in (error or "") else 400, error or "Refused.")
            return

        # The journal is written for every real answer, including the ones
        # that were refused for being late - a refused approval is exactly the
        # kind of thing you want a record of.
        journal.card_decision(
            self.server.journal_path,
            card_id,
            card.get("action"),
            body["decision"],
            card.get("state") == cards.APPROVED,
        )
        payload: dict[str, Any] = {"ok": error is None, "card": card}
        if error:
            payload["error"] = error
        self._send(200 if error is None else 409, payload)

    def _chat(self) -> None:
        """POST /api/chat: ask the model one question, or name one action.

        Every body needs a "message" - the caller's own words, and what the
        journal fingerprints. With an "action" the request goes through the
        gate instead of the model. "args" with no "action" is refused, because
        a caller who sent arguments expected something to happen. A plain chat
        answers 200, or 503 with the model layer's own sentence.
        """
        body, problem = self._read_json()
        if problem:
            self._fail(400, problem)
            return
        if "message" not in body:
            self._fail(400, 'The body needs a "message" field with your question in it.')
            return

        settings = self.server.settings
        message = body["message"]

        # The optional action path. The model cannot ask for this: it is the
        # caller, and only the caller, that names an action. Kept in this
        # build because it is what proves the gate end to end over HTTP.
        if "action" in body:
            self._run_action(body["action"], body.get("args") or {}, message)
            return
        if "args" in body:
            # Fail closed rather than ignore it. An "args" with no "action" is
            # a caller who thinks something is going to happen; silently
            # treating it as a plain chat would be the worst of both worlds.
            self._fail(400, 'The body has "args" but no "action" to use them with.')
            return

        if not isinstance(message, str) or not message.strip():
            self._fail(400, 'The "message" must be a non-empty piece of text.')
            return

        answer = model.chat(message, settings)
        # One line per turn. Note what is passed and what is not: the journal
        # gets the lengths and fingerprints, never `message` or `reply`.
        journal.turn(self.server.journal_path, message, answer.get("reply"), answer["ok"])

        if not answer["ok"]:
            # Honest bad news, with the same sentence the model layer wrote -
            # "Ollama is not running" and not a stack trace.
            self._fail(503, answer["error"], model=answer["model"])
            return
        self._send(200, {"ok": True, "reply": answer["reply"], "model": answer["model"]})

    def _run_action(self, action: Any, args: Any, message: Any) -> None:
        """Walk one action through the gate. This is the heart of the design."""
        if not isinstance(args, dict):
            self._fail(400, 'The "args" field must be a JSON object, like {"text": "hi"}.')
            return

        decision = gate.resolve(action, self.server.settings)

        if decision.tier == gate.NEVER:
            self._fail(403, f"Refused: {decision.reason}", action=decision.action, tier=decision.tier)
            return
        if decision.tier == gate.UNCLASSIFIED:
            # The fail-closed case. No card, no run - a clear no.
            self._fail(403, f"Refused: {decision.reason}", action=decision.action, tier=decision.tier)
            return
        if decision.tier == gate.AUTO:
            self._send(200, {"ok": True, "ran": True, "tier": decision.tier,
                             "result": self._call_action(decision.action, args)})
            return

        # tier == "ask". Raise a card and answer the caller straight away with
        # the card's id. The *card* is what waits, not this HTTP request.
        runner, shows = self._make_runner(decision.action, args)
        if runner is None:
            self._fail(400, shows or "That action cannot be run.")
            return

        paused: list[dict[str, Any]] = []
        card = self.server.card_store.raise_card(
            action=decision.action,
            title=actions.ACTION_INFO.get(decision.action, {}).get("title", decision.action),
            details={"shows": shows, "asked_with": message if isinstance(message, str) else ""},
            runner=lambda: paused.append(_run_guarded(runner)) or paused[0],
        )
        self._send(202, {
            "ok": True,
            "ran": False,  # nothing has happened yet, and saying so is the point
            "tier": decision.tier,
            "waiting_for_approval": card["id"],
            "then": f'POST /api/card/{card["id"]} with {{"decision": "approve"}} '
                    f'to let it run, or {{"decision": "deny"}} to stop it. '
                    f'GET /api/card/{card["id"]} says where it got to.',
            "card": card,
        })

    def _make_runner(
        self, action: str, args: dict[str, Any]
    ) -> tuple[Callable[[], dict[str, Any]] | None, str]:
        """Build a no-argument function that runs the action, plus the text to
        show on the card. Returns (None, message) if the action does not exist
        in this build."""
        server = self.server
        function = server.action_functions.get(action)
        if function is None:
            return None, (
                f"There is no action called {action!r} in this build, even "
                "though settings.json lists it. Nothing ran."
            )

        def runner() -> dict[str, Any]:
            """Run this action, handing settings only to the one that needs them."""
            # write_note needs to know where the notes folder is. Rather than
            # teach every action about settings, only the one that needs it is
            # handed them - so a new action cannot quietly pick up the paths.
            if action == "write_note":
                return function(args, settings=server.settings,
                                settings_path=server.settings_path)
            return function(args)

        return runner, _preview(args)

    def _call_action(self, action: str, args: dict[str, Any]) -> Any:
        """Run an "auto" action straight away, and turn any failure into a value.

        Failures come back as {"error": "..."} rather than being raised: this
        runs inside a POST, where an exception would become a blank 500. A name
        settings lists but this build lacks arrives the same way.
        """
        runner, failure = self._make_runner(action, args)
        if runner is None:
            return {"error": failure}
        try:
            return runner()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}


def _run_guarded(runner: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run an action and turn any failure into a value instead of an exception.

    A broken action must not take the server down, and it must not look like a
    success either. The message goes on the card, where whoever asked can see
    it. (The card layer catches exceptions too; this exists so the error is
    already in the shape the card expects.)
    """
    try:
        return runner()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _preview(args: dict[str, Any], limit: int = 300) -> str:
    """The card's preview of what is about to happen, cut to a readable length.

    Truncating is safe here, unlike in actions.py: the card is a summary for a
    person, and the action itself is given the whole argument.
    """
    try:
        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(args)
    return text if len(text) <= limit else text[:limit] + " ..."


def build_parser() -> argparse.ArgumentParser:
    """The two switches this program takes: --port and --settings.

    It exists so `py -3 -m jarvis_core --help` explains itself, and so there is
    one place to change when a third switch is wanted.
    """
    parser = argparse.ArgumentParser(
        prog="py -3 -m jarvis_core",
        description="Start the local Jarvis foundation. It only ever listens on this PC.",
    )
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default comes from settings.json: 4719).")
    parser.add_argument("--settings", default=None,
                        help="Path to a settings.json to use instead of the usual one.")
    return parser


def _port_is_answering(host: str, port: int, timeout: float = 0.3) -> bool:
    """Is something already listening on this address?

    This exists because the `except OSError` below is not enough on Windows.
    JarvisServer sets `allow_reuse_address` (SO_REUSEADDR), and Windows lets a
    second socket with that flag bind an address another program is already
    using - no error is raised at all. Without this probe, starting jarvis-core
    while the owner's bigger Jarvis holds 4719 would appear to work and then
    quietly share the port between two programs. Probing first means the plain
    sentence below is what a person actually sees, on every platform.

    It only ever returns True for a definite answer: a refused or timed-out
    connection means "probably free", and the normal OSError path still covers
    the rest.
    """
    probe = socket.socket()
    probe.settimeout(timeout)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _port_busy_message(host: str, port: int) -> str:
    """The one sentence to show when the port is taken, before and after bind."""
    return (
        f"Port {port} is already in use - something else is running there.\n"
        f"  Close it, or start this with --port {port + 1}: "
        f"py -3 -m jarvis_core --port {port + 1}"
    )


def main(argv: list[str] | None = None) -> int:
    """Start the server. Returns the exit code, so __main__ can just pass it on."""
    args = build_parser().parse_args(argv)

    try:
        settings = config.load(args.settings)
    except config.ConfigError as exc:
        # Plain message, no traceback. This is a beginner's first run, and the
        # fix is nearly always "edit that line" or "delete the file".
        print(f"Jarvis will not start: {exc}", file=sys.stderr)
        return 2

    host = str(settings["server"]["host"])
    port = int(args.port if args.port is not None else settings["server"]["port"])

    # The most likely thing to go wrong for this owner, who runs a bigger
    # Jarvis on the same port: say so plainly, and say the way round it. The
    # common cause is named because a beginner cannot guess it.
    if _port_is_answering(host, port):
        print(_port_busy_message(host, port), file=sys.stderr)
        return 2

    try:
        server = JarvisServer((host, port), settings, args.settings)
    except OSError as exc:
        # The same message if the probe somehow missed it and the bind still
        # failed. Never a traceback for this.
        print(_port_busy_message(host, port), file=sys.stderr)
        print(f"  ({host}:{port}: {exc})", file=sys.stderr)
        return 2

    # What a beginner sees, and it is the whole instruction: open this address,
    # and leave the window alone. Nothing in this program is logged to the
    # console, so these lines are all that will ever appear here.
    print(f"jarvis-core {__version__} is running.")
    print()
    print(f"  Open this in your browser:  http://{host}:{port}")
    print()
    print("  Leave this window open - that is what keeps it running.")
    print("  To stop it, close this window or press Ctrl+C.")
    print()
    print(f"  model:    {settings['model']['name']} at {settings['model']['base_url']}")
    print(f"  journal:  {config.journal_path(settings, args.settings)}")
    print("  it only answers on this PC, so no other computer can reach it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0
