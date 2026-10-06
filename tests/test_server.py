# ==============================================================================
# Author: James through Deepseek Harness
# Description: Checks the routes that matter over real HTTP on a real socket, with a fake model standing in for Ollama. Exports the test functions only - the whole design end to end, including an ask action that runs once its card is approved.
# ==============================================================================

"""The two routes that matter, over real HTTP, on a real socket.

The server is started on port 0, which means "any free port", and then asked
for its own port number. Why go to that trouble instead of calling the handler
functions directly: because the things most likely to be wrong here are the
HTTP things - a missing Content-Length, a route that quietly 500s, a body that
is not read. Calling the functions directly would test none of that.

The model is a fake. Nothing in this file needs Ollama to be installed or
running, and nothing in it can reach the internet.
"""

from __future__ import annotations

import json
import http.client
import threading
from pathlib import Path

import _helpers
from _helpers import FakeOllama, check, check_equal, check_in, install_fake_ollama, sandbox

from jarvis_core import __version__, config, server


def _start(settings: dict, settings_path: str):
    """Start a real server on a free port, and give a way to stop it."""
    httpd = server.JarvisServer(("127.0.0.1", 0), settings, settings_path)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


def _request(port: int, method: str, path: str, body: dict | None = None):
    """One request. Returns (status, parsed JSON)."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode("utf-8")
    connection.close()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"_raw": raw}
    return response.status, parsed


def test_status_answers_json_and_says_what_this_build_does():
    fake = FakeOllama(models=["qwen3:8b"])
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                status, answer = _request(port, "GET", "/api/status")
            finally:
                httpd.shutdown()
                httpd.server_close()
    finally:
        restore()

    check_equal(status, 200, "the HTTP status")
    check_equal(answer["ok"], True, "the ok field")
    check_equal(answer["version"], __version__, "the version")
    check_equal(answer["model"]["reachable"], True, "whether the model is reachable")
    check_equal(answer["model"]["local_only"], True, "the local-only promise")
    check_equal(answer["model"]["name"], "qwen3:8b", "the model's name")
    check_in("get_time", answer["actions"], "the action table")
    check_equal(answer["actions"]["get_time"]["tier"], "auto", "get_time's tier")
    check_equal(answer["actions"]["write_note"]["tier"], "ask", "write_note's tier")
    check(isinstance(answer["does"], list) and answer["does"], "the does list")
    check(isinstance(answer["does_not"], list) and answer["does_not"], "the does_not list")


def test_status_says_plainly_when_the_model_is_absent():
    """The honest bad news. No crash, no pretending."""
    fake = FakeOllama(reachable=False)
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                status, answer = _request(port, "GET", "/api/status")
            finally:
                httpd.shutdown()
                httpd.server_close()
    finally:
        restore()

    check_equal(status, 200, "the HTTP status")
    check_equal(answer["model"]["reachable"], False, "whether the model is reachable")
    check_equal(answer["model"]["model_present"], False, "whether the model is installed")
    check_in("Could not reach the model", answer["model"]["detail"], "the plain explanation")


def test_status_says_plainly_when_the_model_is_not_installed():
    fake = FakeOllama(models=["some-other-model:1b"])
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                _, answer = _request(port, "GET", "/api/status")
            finally:
                httpd.shutdown()
                httpd.server_close()
    finally:
        restore()

    check_equal(answer["model"]["reachable"], True, "whether Ollama is running")
    check_equal(answer["model"]["model_present"], False, "whether our model is installed")
    check_in("not installed", answer["model"]["detail"], "the plain explanation")
    check_in("ollama pull", answer["model"]["detail"], "the fix the message suggests")


def test_chat_answers_and_writes_one_journal_line():
    fake = FakeOllama(reply="It is a test answer.")
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                status, answer = _request(port, "POST", "/api/chat", {"message": "hello"})
            finally:
                httpd.shutdown()
                httpd.server_close()
            lines = open(box["journal_path"], encoding="utf-8").read().splitlines()
    finally:
        restore()

    check_equal(status, 200, "the HTTP status")
    check_equal(answer["ok"], True, "the ok field")
    check_equal(answer["reply"], "It is a test answer.", "the answer")
    check_equal(answer["model"], "qwen3:8b", "the model that answered")
    check_equal(len(lines), 1, "how many journal lines were written")
    check("hello" not in lines[0], "the journal line must not contain the message text")


def test_chat_gives_a_plain_error_when_the_model_is_down():
    fake = FakeOllama(reachable=False)
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                status, answer = _request(port, "POST", "/api/chat", {"message": "hello"})
            finally:
                httpd.shutdown()
                httpd.server_close()
    finally:
        restore()

    check_equal(status, 503, "the HTTP status")
    check_equal(answer["ok"], False, "the ok field")
    check_in("Could not reach the model", answer["error"], "the plain explanation")


def test_a_malformed_request_is_refused_not_guessed_at():
    fake = FakeOllama()
    restore = install_fake_ollama(fake)
    try:
        with sandbox() as box:
            httpd, port = _start(box["settings"], box["settings_path"])
            try:
                cases = [
                    ("POST", "/api/chat", {}, 400),               # no message
                    ("POST", "/api/chat", {"message": "   "}, 400),  # empty message
                    ("POST", "/api/chat", {"message": 17}, 400),  # not text
                    ("POST", "/api/chat", {"message": "hi", "args": "not an object"}, 400),
                    ("POST", "/api/chat", {"message": "hi", "args": {}}, 400),  # args with no action
                    ("POST", "/api/card/abc", {}, 400),           # no decision
                    ("POST", "/api/card/abc", {"decision": "maybe"}, 400),  # not a real word
                    ("POST", "/api/card/abc", {"decision": "approve"}, 404),  # no such card
                ]
                seen = []
                for method, path, body, expected in cases:
                    status, answer = _request(port, method, path, body)
                    seen.append((path, body, status, expected))
                    check_equal(status, expected, f"{path} with {body} - the HTTP status")
                    check_equal(answer["ok"], False, f"{path} with {body} - the ok field")
                    check(answer.get("error"), f"{path} with {body} - a plain explanation")
            finally:
                httpd.shutdown()
                httpd.server_close()
    finally:
        restore()


def test_an_unknown_route_is_refused():
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        try:
            for method, path in (("GET", "/api/nope"), ("GET", "/"), ("POST", "/api/secret")):
                status, answer = _request(port, method, path)
                check_equal(status, 404, f"{method} {path} - the HTTP status")
                check_in("no route", answer["error"], "the refusal message")
        finally:
            httpd.shutdown()
            httpd.server_close()


def test_the_unknown_action_fails_closed_over_http():
    """The gate, through a real socket. No card is raised, so there is nothing
    to approve - the answer is simply no."""
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        try:
            status, answer = _request(
                port, "POST", "/api/chat",
                {"message": "please do it", "action": "delete_everything"},
            )
        finally:
            httpd.shutdown()
            httpd.server_close()

    check_equal(status, 403, "the HTTP status")
    check_equal(answer["ran"], False, "an unknown action must not run")
    check_equal(answer["tier"], "unclassified", "the tier that was resolved")
    check_in("no action called", answer["error"], "the refusal message")


def test_an_auto_action_runs_straight_away_over_http():
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        try:
            status, answer = _request(
                port, "POST", "/api/chat",
                {"message": "what time is it", "action": "get_time"},
            )
        finally:
            httpd.shutdown()
            httpd.server_close()

    check_equal(status, 200, "the HTTP status")
    check_equal(answer["ran"], True, "whether the action ran")
    check_equal(answer["tier"], "auto", "the tier that was resolved")
    check_in("time", answer["result"], "the clock result")


def test_an_ask_action_waits_and_then_runs_once_the_card_is_approved():
    """The whole design, over HTTP, end to end.

    Step 1 asks for a write_note. Nothing is written and nothing has run - the
    answer is a card id. Step 2 approves the card, and only then does the note
    appear on disk.
    """
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        notes = box["base"] / "notes"
        try:
            status, asked = _request(
                port, "POST", "/api/chat",
                {"message": "note this", "action": "write_note",
                 "args": {"text": "buy milk"}},
            )
            check_equal(status, 202, "the status of a request that is waiting")
            check_equal(asked["ran"], False, "nothing should have run yet")
            check_in("waiting_for_approval", asked, "the reply")
            check_in("then", asked, "the reply")
            check_in("/api/card/", asked["then"], "the instructions for what to do next")
            card_id = asked["waiting_for_approval"]
            check_equal(len(list(notes.glob("*.txt"))) if notes.is_dir() else 0, 0,
                        "note files written before any approval")

            status, waiting = _request(port, "GET", f"/api/card/{card_id}")
            check_equal(status, 200, "reading the card")
            check_equal(waiting["card"]["state"], "pending", "the card's state while it waits")
            check_in("buy milk", json.dumps(waiting["card"]), "the card's preview of the change")
            check_equal(waiting["card"]["action"], "write_note", "the card's action")
            check_in("Write a note", waiting["card"]["title"], "the card's title")

            status, decided = _request(port, "POST", f"/api/card/{card_id}",
                                       {"decision": "approve"})
            check_equal(status, 200, "approving the card")
            check_equal(decided["card"]["state"], "approved", "the card's state after approval")
            check_equal(decided["card"]["result"]["chars"], len("buy milk"),
                        "the result the action reported")

            note_files = sorted(notes.glob("*.txt")) if notes.is_dir() else []
            note_text = note_files[0].read_text(encoding="utf-8").strip() if note_files else ""
            _, after = _request(port, "GET", f"/api/card/{card_id}")
            journal_lines = open(box["journal_path"], encoding="utf-8").read().splitlines()
        finally:
            httpd.shutdown()
            httpd.server_close()

    check_equal(len(note_files), 1, "how many note files were written")
    check_equal(note_text, "buy milk", "what the note file says")
    check_equal(after["card"]["state"], "approved", "the card's state when asked again")
    check_equal(len(journal_lines), 1, "how many journal lines were written")
    check_in("approve", journal_lines[0], "the recorded decision")


def test_an_ask_action_writes_nothing_when_the_card_is_denied():
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        notes = box["base"] / "notes"
        try:
            status, asked = _request(
                port, "POST", "/api/chat",
                {"message": "note this", "action": "write_note",
                 "args": {"text": "do not write me"}},
            )
            check_equal(status, 202, "the status of a request that is waiting")
            card_id = asked["waiting_for_approval"]

            status, decided = _request(port, "POST", f"/api/card/{card_id}",
                                       {"decision": "deny"})
            check_equal(status, 200, "denying the card")
            check_equal(decided["card"]["state"], "denied", "the card's state after denial")
            check_equal(decided["card"]["result"], None, "the result of a denied card")
            notes_left = list(notes.glob("*.txt")) if notes.is_dir() else []
            journal_lines = open(box["journal_path"], encoding="utf-8").read().splitlines()
        finally:
            httpd.shutdown()
            httpd.server_close()

    check_equal(notes_left, [], "the note files left on disk after a denial")
    check_equal(len(journal_lines), 1, "how many journal lines were written")
    check_in("deny", journal_lines[0], "the recorded decision")


def test_an_expired_card_cannot_be_approved_over_http():
    """The time limit, through the real routes. The card is forced past its
    time rather than waiting for it, so the test is instant."""
    with sandbox() as box:
        httpd, port = _start(box["settings"], box["settings_path"])
        notes = box["base"] / "notes"
        try:
            _, asked = _request(
                port, "POST", "/api/chat",
                {"message": "note this", "action": "write_note",
                 "args": {"text": "too late"}},
            )
            card_id = asked["waiting_for_approval"]
            httpd.card_store._expire_now_for_test(card_id)  # noqa: SLF001

            status, refused = _request(port, "POST", f"/api/card/{card_id}",
                                       {"decision": "approve"})
            notes_left = list(notes.glob("*.txt")) if notes.is_dir() else []
        finally:
            httpd.shutdown()
            httpd.server_close()

    check_equal(status, 409, "the status of a late approval")
    check_equal(refused["ok"], False, "the ok field")
    check_in("expired", refused["error"], "the refusal message")
    check_equal(refused["card"]["state"], "expired", "the card's state")
    check_equal(notes_left, [], "the note files left on disk after a late approval")


def test_the_default_settings_cannot_reach_the_lan():
    """Rule 2 as a test. 127.0.0.1 is this PC only; 0.0.0.0 would answer the
    whole home network and anything else that can route here."""
    defaults = config.DEFAULTS["server"]["host"]
    check_equal(defaults, "127.0.0.1", "the host the server binds by default")
    check(defaults not in ("0.0.0.0", "::", ""), "the server must never bind every address")

    root = Path(__file__).resolve().parent.parent
    check_in("logs/", (root / ".gitignore").read_text(encoding="utf-8"), "the .gitignore file")
