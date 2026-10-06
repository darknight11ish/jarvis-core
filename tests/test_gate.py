"""Rule 4 as a test: nothing is ever approved on the owner's behalf.

Read this file with gate.py open next to it.

The case that matters most is the last one - an action that is not in the table
must FAIL CLOSED. "Fails closed" means it does not run, and it does not quietly
become "ask" either: there is no card to approve, because a card would mean a
permission path exists for something nobody reviewed.
"""

from __future__ import annotations

from _helpers import check, check_equal, check_in, sandbox

from jarvis_core import actions, gate


def test_auto_tier_runs_without_a_card():
    """get_time reads a clock. It cannot touch anything, so it runs."""
    with sandbox() as box:
        decision = gate.resolve("get_time", box["settings"])
        check_equal(decision.tier, gate.AUTO, "tier")
        check(decision.runs_now, "an auto action should be allowed to run")
        check(not decision.needs_a_card, "an auto action should not raise a card")

        result = actions.get_time({})
        check_in("time", result, "the clock result")


def test_ask_tier_needs_a_card_and_does_not_run_by_itself():
    """write_note writes a file. It must wait, and it must not be runnable
    from the gate itself."""
    with sandbox() as box:
        decision = gate.resolve("write_note", box["settings"])
        check_equal(decision.tier, gate.ASK, "tier")
        check(decision.needs_a_card, "an ask action should raise a card")
        check(not decision.runs_now, "an ask action must never run on its own")
        check("wait" in decision.reason.lower(), "the reason should say it waits")


def test_unclassified_action_FAILS_CLOSED():
    """THE important one. A name that is not in the table is refused.

    Breaking this on purpose makes this test fail: change gate.tier_of to
    return ASK instead of UNCLASSIFIED for an unknown name, and the two checks
    below go red.
    """
    with sandbox() as box:
        decision = gate.resolve("launch_the_missiles", box["settings"])

        check_equal(decision.tier, gate.UNCLASSIFIED, "tier of an unknown action")
        check(decision.refused, "an unknown action must be refused")
        check(not decision.runs_now, "an unknown action must not run")
        check(
            not decision.needs_a_card,
            "an unknown action must NOT become 'ask' - a card would mean an "
            "unreviewed thing can be approved",
        )
        check_in("no action called", decision.reason, "the refusal message")

        # And a name that is not even a string is refused the same way.
        for nonsense in (None, "", "   ", 17, ["get_time"]):
            check_equal(
                gate.tier_of(nonsense, box["settings"]),
                gate.UNCLASSIFIED,
                f"tier of {nonsense!r}",
            )


def test_never_tier_is_refused_and_cannot_be_approved():
    """A 'never' action has no path to running at all - no card, no auto."""
    with sandbox() as box:
        box["settings"]["security"]["tiers"]["delete_everything"] = gate.NEVER
        decision = gate.resolve("delete_everything", box["settings"])

        check_equal(decision.tier, gate.NEVER, "tier")
        check(decision.refused, "a never action must be refused")
        check(not decision.runs_now, "a never action must not run")
        check(not decision.needs_a_card, "a never action must not raise a card")
        check_in("switched off for good", decision.reason, "the refusal message")


def test_a_tier_word_that_is_not_real_is_refused():
    """settings.json is a text file. If someone types "yes" or "allow", that is
    not a tier, and it must not be read as permission."""
    with sandbox() as box:
        for word in ("yes", "allow", "AUTO", "always", "", True, 1):
            box["settings"]["security"]["tiers"]["get_time"] = word
            check_equal(
                gate.tier_of("get_time", box["settings"]),
                gate.UNCLASSIFIED,
                f"tier when settings say {word!r}",
            )


def test_every_action_in_the_build_has_a_tier_in_the_table():
    """A function nobody gave a tier to is a function nobody can call - which
    is safe, but it is usually a mistake worth catching now rather than when
    someone asks for it and gets a refusal."""
    with sandbox() as box:
        table = gate.tier_table(box["settings"])
        for name in actions.registry():
            check_in(name, table, "the tier table")
            check_equal(gate.tier_of(name, box["settings"]), table[name], f"tier of {name}")
