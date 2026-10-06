"""The log, and the promise that it never holds a secret.

This is rule 1 as a test. The interesting one is the first test: a token-shaped
string goes in as a message, the model echoes it back, and neither string is
anywhere in the file afterwards.

Break it on purpose to see it fail: in journal.turn, add `"message": message,`
to the entry. The test goes red immediately, which is the whole point - the
test is the thing that stops a later edit from quietly starting to log your
words.
"""

from __future__ import annotations

from _helpers import check, check_equal, check_in, sandbox

from jarvis_core import journal

# Shaped like a real token, and deliberately not one.
FAKE_TOKEN = "sk-jarvis-test-9f4c2a71b8de"


def test_a_token_shaped_string_never_reaches_the_log():
    """The test this file exists for."""
    with sandbox() as box:
        path = box["journal_path"]
        question = f"Please remember this key: {FAKE_TOKEN}"
        # The model echoing it back is the worst case: the token is now in the
        # reply too, so the journal must not be given either string.
        answer = f"Noted, your key is {FAKE_TOKEN}"

        journal.turn(path, question, answer, ok=True)

        written = open(path, encoding="utf-8").read()
        check(FAKE_TOKEN not in written, "the token is in the log file - it must never be")
        check("Please remember this key" not in written,
              "the owner's message text is in the log - it must never be")
        check("Noted, your key is" not in written,
              "the model's reply text is in the log - it must never be")

        entries = journal.read(path)
        check_equal(len(entries), 1, "how many lines were written")
        entry = entries[0]
        check_equal(entry["kind"], "turn", "the kind of entry")
        check_equal(entry["ok"], True, "the outcome")
        check("message" not in entry, "the entry should not have a message field")
        check("reply" not in entry, "the entry should not have a reply field")


def test_the_log_remembers_the_length_and_a_fingerprint():
    """So a turn is still useful later, without keeping the words: you can see
    how long it was, and prove two turns were the same."""
    with sandbox() as box:
        path = box["journal_path"]
        journal.turn(path, "hello there", "hi", ok=True)
        journal.turn(path, "hello there", "hi", ok=True)
        journal.turn(path, "something else", "hi", ok=True)

        entries = journal.read(path)
        check_equal(len(entries), 3, "how many lines were written")
        check_equal(entries[0]["message_chars"], len("hello there"), "the message length")
        check_equal(entries[0]["message_fingerprint"], entries[1]["message_fingerprint"],
                    "the fingerprint of two identical messages")
        check(entries[0]["message_fingerprint"] != entries[2]["message_fingerprint"],
              "two different messages should have different fingerprints")
        check(entries[0]["message_fingerprint"] != "-",
              "a real message should get a real fingerprint")


def test_a_card_decision_is_written_down():
    """Every card decision gets a line - including a denial, which is exactly
    the kind of thing you would want to be able to look up later."""
    with sandbox() as box:
        path = box["journal_path"]
        journal.card_decision(path, "abc123", "write_note", "deny", approved=False)

        entries = journal.read(path)
        check_equal(len(entries), 1, "how many lines were written")
        check_equal(entries[0]["kind"], "card", "the kind of entry")
        check_equal(entries[0]["card"], "abc123", "the card id")
        check_equal(entries[0]["action"], "write_note", "the action name")
        check_equal(entries[0]["decision"], "deny", "the decision")
        check_equal(entries[0]["approved"], False, "whether it was approved")


def test_the_log_is_jsonl_one_object_per_line():
    """One object per line, so a half-written last line cannot damage the lines
    before it and the file can be read a line at a time."""
    import json

    with sandbox() as box:
        path = box["journal_path"]
        journal.turn(path, "one", "a", ok=True)
        journal.card_decision(path, "c1", "get_time", "approve", approved=True)

        lines = [line for line in open(path, encoding="utf-8").read().splitlines() if line.strip()]
        check_equal(len(lines), 2, "how many lines were written")
        for line in lines:
            parsed = json.loads(line)  # raises if a line is not one JSON object
            check(isinstance(parsed, dict), "every line should be a JSON object")
            check_in("at", parsed, "every entry")
            check_in("kind", parsed, "every entry")


def test_a_secret_shaped_value_is_redacted_even_in_the_backstop_layer():
    """The second layer. The first layer is that the text is never passed in;
    this layer catches a field someone adds later without reading the file."""
    check_equal(journal.scrub(f"key={FAKE_TOKEN}"), "key=[redacted]", "a token-shaped string")
    check_equal(journal.scrub("ghp_abcdefghijklmnop"), "[redacted]", "a GitHub-shaped token")
    check_equal(journal.scrub("Bearer abcdefghijklmnop"), "[redacted]", "a bearer header")
    check_equal(journal.scrub("just a normal sentence"), "just a normal sentence",
                "an ordinary sentence should be left alone")
    check_equal(journal.scrub({"a": [f"x {FAKE_TOKEN} y"]}), {"a": ["x [redacted] y"]},
                "a token nested in a list inside an object")


def test_a_missing_log_folder_is_made_not_fatal():
    """The log is a record, not the work. If it cannot be written, the turn
    still happened, and the program carries on."""
    with sandbox() as box:
        deep = box["base"] / "sub" / "folder" / "jarvis.jsonl"
        journal.turn(deep, "hi", "hello", ok=True)
        check(deep.exists(), "the log folder should have been created")
        check_equal(len(journal.read(deep)), 1, "how many lines were written")
