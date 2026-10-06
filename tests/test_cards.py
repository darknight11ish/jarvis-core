"""Cards: the waiting, the decision, and the time limit.

The three promises this file checks, in the owner's words:

  * "yes" runs it once, and only once;
  * "no" runs nothing, ever;
  * a card that timed out cannot be approved afterwards.
"""

from __future__ import annotations

import _helpers
from _helpers import check, check_equal, check_in, sandbox

from jarvis_core import cards


def _card_with_a_counter():
    """A card whose action is "count up by one". The list is the evidence."""
    ran: list[int] = []
    store = cards.CardStore(ttl_seconds=30)
    card = store.raise_card(
        action="write_note",
        title="Write a note file on this PC",
        details={"shows": '{"text": "hello"}'},
        runner=lambda: (ran.append(1), {"written": "note.txt"})[1],
    )
    return store, card, ran


def test_approving_runs_the_action_exactly_once():
    store, card, ran = _card_with_a_counter()
    check_equal(card["state"], cards.PENDING, "a new card's state")

    answered, error = store.decide(card["id"], "approve")

    check_equal(error, None, "the error from a first approval")
    check_equal(answered["state"], cards.APPROVED, "state after approval")
    check_equal(len(ran), 1, "how many times the action ran")
    check_equal(answered["result"], {"written": "note.txt"}, "the action's result")


def test_denying_runs_nothing():
    store, card, ran = _card_with_a_counter()
    answered, error = store.decide(card["id"], "deny")

    check_equal(error, None, "the error from a denial")
    check_equal(answered["state"], cards.DENIED, "state after denial")
    check_equal(len(ran), 0, "how many times a denied action ran")
    check_equal(answered["result"], None, "the result of a denied card")


def test_an_expired_card_cannot_be_approved():
    """The clock runs out, and after that the approval is refused.

    The expiry is forced with the test-only hook rather than by sleeping for
    the full time, so this test is instant and not flaky. Everything after that
    hook is the real expiry code - the same `_expire` the card's timer calls.
    """
    store, card, ran = _card_with_a_counter()
    store._expire_now_for_test(card["id"])

    answered, error = store.decide(card["id"], "approve")

    check(error is not None, "approving an expired card should be refused")
    check_in("expired", error, "the refusal message")
    check_equal(answered["state"], cards.EXPIRED, "state after trying to approve it")
    check_equal(len(ran), 0, "how many times an expired card's action ran")


def test_the_second_answer_changes_nothing():
    """First answer wins - including a second, opposite one. There is no path
    from a denial to a run."""
    store, card, ran = _card_with_a_counter()
    store.decide(card["id"], "deny")

    answered, error = store.decide(card["id"], "approve")

    check(error is not None, "a second decision should be refused")
    check_in("Already denied", error, "the refusal message")
    check_equal(answered["state"], cards.DENIED, "state after the second answer")
    check_equal(len(ran), 0, "how many times the action ran in the end")


def test_a_word_we_do_not_understand_is_not_a_yes():
    """Fail closed: only the exact words approve and deny count."""
    store, card, ran = _card_with_a_counter()
    for word in ("yes", "ok", "APPROVE ME", "", None, 1, True, "approved"):
        answered, error = store.decide(card["id"], word)
        check(error is not None, f"{word!r} should not be accepted as a decision")
        check(answered is None or answered["state"] == cards.PENDING,
              f"{word!r} should leave the card pending")
    check_equal(len(ran), 0, "how many times the action ran")

    # The real words, in either case and with stray spaces, do work.
    answered, error = store.decide(card["id"], "  Approve ")
    check_equal(error, None, "the error from a messy but valid approval")
    check_equal(len(ran), 1, "how many times the action ran")


def test_waiting_returns_as_soon_as_the_owner_answers():
    """The blocking half. The card is answered from another thread, exactly as
    a real POST /api/card would, and the waiter comes back."""
    import threading

    store, card, ran = _card_with_a_counter()

    def answer_soon() -> None:
        store.decide(card["id"], "approve")

    threading.Timer(0.05, answer_soon).start()
    answered = store.wait_for(card["id"], timeout=5)

    check(answered is not None, "wait_for should return the card")
    check_equal(answered["state"], cards.APPROVED, "state the waiter saw")
    check_equal(len(ran), 1, "how many times the action ran")


def test_an_unknown_card_is_a_plain_no():
    store = cards.CardStore(ttl_seconds=5)
    check_equal(store.get("nope"), None, "get() for a card that was never raised")
    answered, error = store.decide("nope", "approve")
    check_equal(answered, None, "decide() for a card that was never raised")
    check_in("Unknown card", error, "the refusal message")


def test_the_card_ttl_comes_from_settings():
    """The time limit is a setting, not a buried number."""
    with sandbox() as box:
        box["settings"]["security"]["card_ttl_seconds"] = 7
        store = cards.CardStore(ttl_seconds=int(box["settings"]["security"]["card_ttl_seconds"]))
        card = store.raise_card(action="write_note", title="t", runner=None)
        check_equal(card["ttl_seconds"], 7, "the card's time limit")
