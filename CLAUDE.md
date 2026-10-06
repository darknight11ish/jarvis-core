# Working rules for jarvis-core

This is the short version. The long one - the owner's full working rules, the
project's decisions, and the five rules in full - lives in the Epic-Jarvis repo
at `..\Jarvis github\Epic-Jarvis-main\CLAUDE.md`. **Read that one before making
a decision that changes what this program can touch.** This file says only what
is specific to this repository.

## The five rules that are not negotiable

1. **Anything touching email, files, credentials or stored memory stays on the
   local model.** The program sends none of it anywhere. In this repo that is
   enforced, not just written down: `config.py` refuses to start if the model
   address is not `127.0.0.1`, and `test_journal.py` proves a token-shaped
   string cannot reach the log.
2. **Never open a public tunnel.** No ngrok, no Cloudflare Tunnel, no Tailscale
   Funnel, no "share my Jarvis". The server binds `127.0.0.1`; `test_server.py`
   proves it can never default to `0.0.0.0`.
3. **API keys are allowed, but never logged and never written to a file in
   plain text.** This build has no key anywhere. If one is ever added it goes in
   an environment variable, never in `settings.json` - which is a tracked-able
   file, and which `test_config.py` already guards.
4. **Never auto-approve anything.** The gate's tiers are the whole of this:
   `auto` only for actions that cannot touch anything, `ask` for the rest,
   `never` for the things that should not happen at all, and **an action that is
   not in the table fails closed** rather than borrowing a tier.
5. **Non-commercial build.** The owner said EpicJarvis will never be
   commercialized, so a non-commercial licence is no reason to avoid a part.

## How to work in this repo

- **Keep it readable in one evening.** This is the constraint that beats every
  other one. If a change makes the whole program take two evenings to read,
  it is the wrong change, however good it is.
- **A new feature is a new named action with a tier** - and if it can touch
  anything outside the program, the tier is `ask`. If you are tempted to add a
  capability without a tier, that is the moment to write it in the README's
  "not built yet" list instead.
- **Fail closed.** Unknown route, unknown action, missing setting, malformed
  body: refuse with a plain sentence. Never guess, never default to something
  more permissive than what was written.
- **A rule becomes a test where it can.** Prose is the fallback, not the first
  choice. `tests/` is where the rules actually live.
- **Say what went wrong in plain words.** The owner is a beginner developer and
  a stack trace is not an error message. Every failure here is a sentence that
  says what happened and what to do about it.
- **No dependency without a reason in the file.** `requirements.txt` is empty
  on purpose; a new line there needs a one-line justification beside it.
- **Never commit `settings.json` or `logs/`.** A secret in a commit is a secret
  forever. `test_config.py` checks the real repository with the real git.
- **Run `py -3 run_tests.py` before you commit.** If you add a rule, break the
  code on purpose once and watch the new test fail - a test that cannot fail is
  worse than no test.
