# ==============================================================================
# Author: James through Deepseek Harness
# Description: The card store: one question to the owner, held in memory until it is answered. Exports CardStore, CardError and the four state words - an approval runs the action once, a denial runs nothing, and a timed-out card cannot be approved.
# ==============================================================================

"""Cards: the thing that actually makes an `ask` action wait.

A card is one question to the owner. It has an id, it has a state, and it has
exactly two useful endings: approved or denied. There is a third ending,
expired, and it is deliberately not the same as denied - see below.

Three rules are encoded here, not just written down:

1. **An action runs only after a real approval.** The runner function is
   called from decide(), inside the lock, at the moment the state changes to
   approved, and nowhere else. There is no other path to it.
2. **A decision happens once.** The first answer wins. A second POST for the
   same card gets an honest "already decided" and changes nothing, and that
   includes approving a card that has already been denied.
3. **An expired card cannot be approved.** After the time is up the card is
   expired, and approve() refuses. Why an expiry exists at all: a card that
   stayed answerable forever would mean an action could sit half-agreed for
   days, and an old "yes" is not really a decision about the thing in front of
   you now. Expiry is checked twice - in decide() at the moment of the answer,
   and by a timer, so a card closes even if nobody ever looks at it again.

Everything lives in memory only. A card is a question about right now, not a
record to keep; the record goes in the journal (journal.py).

Nothing in here is tied to an HTTP request. Raising a card returns at once, and
the caller collects the answer by asking for the card's state (or by blocking a
thread in wait_for, if that is what is wanted). The one HTTP route that does
block is decided by the caller, not by this module.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
EXPIRED = "expired"


class CardError(Exception):
    """The card could not be raised the way it was asked for."""


def _new_card_id() -> str:
    """A short id that is random, so it cannot be guessed from the last one."""
    return uuid.uuid4().hex[:12]


class CardStore:
    """Every raised card, for as long as the program is running."""

    def __init__(self, ttl_seconds: int = 120) -> None:
        """Start empty, and remember the time limit every new card will get.

        The caller passes that limit from settings (security.card_ttl_seconds),
        so the owner can change it in the file rather than in the code. The 120
        here is only the fallback for a caller that does not care.
        """
        # The lock is what makes "the first answer wins" true. Every read and
        # write of a card's state happens while holding it.
        self._lock = threading.Lock()
        self._done = threading.Condition(self._lock)
        self._cards: dict[str, dict[str, Any]] = {}
        self._ttl = int(ttl_seconds)

    # -- raising ---------------------------------------------------------

    def raise_card(
        self,
        action: str,
        title: str,
        details: dict[str, Any] | None = None,
        runner: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Make a new card and start its clock. Returns the card as JSON.

        `runner` is what happens if the owner approves. It is stored here and
        called from decide(), never from anywhere else.
        """
        if not isinstance(action, str) or not action.strip():
            raise CardError("A card needs the name of the action it is asking about.")
        if runner is not None and not callable(runner):
            raise CardError("The thing to run after approval must be callable.")

        card = {
            "id": _new_card_id(),
            "action": action,
            "title": title,
            "details": details or {},
            "state": PENDING,
            "created_at": time.time(),
            "decided_at": None,
            "expires_at": time.time() + self._ttl,
            "ttl_seconds": self._ttl,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._cards[card["id"]] = card
            card["_runner"] = runner

        # A card with no runner still works, for tests and for future
        # read-only questions; it just does nothing when approved.
        timer = threading.Timer(self._ttl, self._expire, args=(card["id"],))
        timer.daemon = True  # never keep the program alive just for a card
        timer.start()
        return self._public(card)

    # -- reading ---------------------------------------------------------

    def get(self, card_id: Any) -> dict[str, Any] | None:
        """The card, or None if there is no card with that id."""
        with self._lock:
            card = self._cards.get(card_id) if isinstance(card_id, str) else None
            if card is None:
                return None
            self._expire_locked(card, time.time())
            return self._public(card)

    def wait_for(self, card_id: str, timeout: float | None = None) -> dict[str, Any] | None:
        """Block until the card is decided or expired. Used by tests, and by
        anything that wants to wait without doing it through HTTP."""
        deadline = None if timeout is None else time.time() + timeout
        with self._done:
            while True:
                card = self._cards.get(card_id)
                if card is None:
                    return None
                self._expire_locked(card, time.time())
                if card["state"] != PENDING:
                    return self._public(card)
                left = None if deadline is None else deadline - time.time()
                if left is not None and left <= 0:
                    return self._public(card)
                # A timer tells us when the card expires, so this wake-up is
                # only a backstop against a clock that jumps.
                self._done.wait(timeout=min(left, 1.0) if left else 1.0)

    # -- deciding --------------------------------------------------------

    def decide(self, card_id: Any, decision: Any) -> tuple[dict[str, Any] | None, str | None]:
        """Answer a card. Returns (card, error). One of the two is always None.

        The runner - the real action - is called here, and only here, and only
        when the answer is "approve" and the card was still pending.
        """
        if not isinstance(decision, str):
            return None, 'The decision must be the word "approve" or "deny".'
        wanted = decision.strip().lower()
        if wanted not in ("approve", "deny"):
            # Fail closed: a word we do not understand is not a yes.
            return None, 'The decision must be exactly "approve" or "deny".'

        with self._lock:
            card = self._cards.get(card_id) if isinstance(card_id, str) else None
            if card is None:
                return None, "Unknown card. It was never raised, or it has gone."

            self._expire_locked(card, time.time())
            if card["state"] == EXPIRED:
                return self._public(card), (
                    "This card has expired, so it can no longer be approved. "
                    "Nothing ran. Ask again to get a fresh card."
                )
            if card["state"] != PENDING:
                return self._public(card), (
                    f"Already {card['state']}. A card is answered once; "
                    "the first answer is the one that counted."
                )

            card["decided_at"] = time.time()
            if wanted == "deny":
                card["state"] = DENIED
            else:
                card["state"] = APPROVED
                runner = card.get("_runner")
                if runner is not None:
                    try:
                        card["result"] = runner()
                    except Exception as exc:  # noqa: BLE001 - a broken action
                        # must not take the server down, and must not look
                        # like a success.
                        card["error"] = f"{type(exc).__name__}: {exc}"
            self._done.notify_all()

        return self._public(card), None

    # -- internals -------------------------------------------------------

    def _expire_now_for_test(self, card_id: str) -> None:
        """Force a card past its time limit, for the tests.

        Why this exists instead of a test that sleeps for the real time: a test
        that waits two minutes is a test nobody runs. This walks the exact same
        expiry path the card's own timer walks, so what is being tested is the
        real expiry, reached early.
        """
        with self._done:
            card = self._cards.get(card_id)
            if card is not None:
                card["expires_at"] = 0.0  # long past
                self._expire_locked(card, time.time())
                self._done.notify_all()

    def _expire(self, card_id: str) -> None:
        """The timer's job: close the card, and wake anyone waiting on it."""
        with self._done:
            card = self._cards.get(card_id)
            if card is not None:
                self._expire_locked(card, time.time())
                self._done.notify_all()

    def _expire_locked(self, card: dict[str, Any], now: float) -> None:
        """Close a pending card whose time is up. Caller must hold the lock."""
        if card["state"] == PENDING and now >= card["expires_at"]:
            card["state"] = EXPIRED
            # Decided_at is left alone: an expiry is not a decision, and the
            # journal keeps that difference too.
            if card.get("_runner") is not None:
                card["_runner"] = None  # never runnable again

    def _public(self, card: dict[str, Any]) -> dict[str, Any]:
        """The card as JSON. The private "_runner" never leaves this module."""
        return {key: value for key, value in card.items() if not key.startswith("_")}
