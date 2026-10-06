"""The approval gate: the one place that decides whether an action may run.

Read this file first if you want to understand the design. Everything else is
plumbing around it.

The idea is small enough to hold in your head:

* Every capability is a NAMED action. There is no "run this code" action and
  no way to call a function by name from outside. If it is not written in the
  settings table with a tier, it does not exist.
* Every name in the table has a TIER, which is one of exactly three words:
    - "never"  - refused outright, every time, with no way to approve it.
    - "ask"    - a card is raised and the caller waits for the owner.
    - "auto"   - runs straight away. Only for things that cannot touch
                 anything: reading the clock, doing arithmetic.
* A name that is NOT in the table resolves to "unclassified" and FAILS CLOSED.
  It does not run. It does not quietly become "ask", and it certainly does not
  become "auto".

Why fail closed rather than default to "ask" is the important choice here.
Defaulting to "ask" sounds safer, and for a person clicking a card it is. But
it means a typo, a renamed action or a half-written new feature produces a
*working* card that the owner can approve, and the thing behind that name has
never been reviewed. Defaulting to "unclassified" means the same mistake
produces a clear refusal, and the developer notices at once. A refusal you can
see beats a permission you did not mean to give.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The three words. Same names as config.KNOWN_TIERS; config checks the settings
# file against them so a fourth word can never reach this file.
NEVER = "never"
ASK = "ask"
AUTO = "auto"

UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class Decision:
    """What the gate decided about one call, and why.

    `reason` is shown to a person, so it is written in plain words.
    """

    action: str
    tier: str
    reason: str

    @property
    def runs_now(self) -> bool:
        """True only for a tier this build will run without asking."""
        return self.tier == AUTO

    @property
    def needs_a_card(self) -> bool:
        return self.tier == ASK

    @property
    def refused(self) -> bool:
        return self.tier in (NEVER, UNCLASSIFIED)


def tier_of(action: Any, settings: dict[str, Any]) -> str:
    """Look up an action's tier, or say it is unclassified.

    The order of these checks is deliberate. A name that is not a plain string
    is unclassified (not "coerced into a string and maybe found"). A name that
    is not in the table is unclassified. Only then do we trust the table, and
    even then we re-check the word, because the settings file is a text file a
    person can edit.
    """
    if not isinstance(action, str) or not action.strip():
        return UNCLASSIFIED
    table = settings.get("security", {}).get("tiers", {})
    if not isinstance(table, dict):
        return UNCLASSIFIED
    tier = table.get(action)
    if tier not in (NEVER, ASK, AUTO):
        return UNCLASSIFIED
    return tier


def resolve(action: Any, settings: dict[str, Any]) -> Decision:
    """Decide what should happen to this action. Decide only; do not do it."""
    tier = tier_of(action, settings)

    if tier == AUTO:
        return Decision(
            action=str(action),
            tier=AUTO,
            reason="This action cannot touch anything outside the program, "
                   "so it runs without asking.",
        )
    if tier == ASK:
        return Decision(
            action=str(action),
            tier=ASK,
            reason="This action can change something, so it waits for you.",
        )
    if tier == NEVER:
        return Decision(
            action=str(action),
            tier=NEVER,
            reason="This action is switched off for good. Nothing can approve it.",
        )
    return Decision(
        action=str(action),
        tier=UNCLASSIFIED,
        reason=(
            f"There is no action called {action!r} in the settings table. "
            "It is refused rather than guessed at. To allow it, add it to "
            "security.tiers in settings.json with a tier of auto, ask or never."
        ),
    )


def tier_table(settings: dict[str, Any]) -> dict[str, str]:
    """The table as plain words, for /api/status and for the README."""
    table = settings.get("security", {}).get("tiers", {})
    return dict(table) if isinstance(table, dict) else {}


TIER_MEANINGS: dict[str, str] = {
    AUTO: "runs without asking - only for actions that cannot touch anything",
    ASK: "raises a card and waits; nothing runs until the owner decides",
    NEVER: "refused outright; no card can approve it",
    UNCLASSIFIED: "not in the table at all, so it is refused (fails closed)",
}
