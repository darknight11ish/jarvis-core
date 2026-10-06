# jarvis-core

A small local assistant server. It runs on your own PC, answers on
`127.0.0.1` only, and talks to one model running on the same machine. It comes
with a page you can type in, and it can do exactly two things - one of which
waits for your permission first.

**It is a foundation, not a product.** The point is that every line can be read
in an evening, so the next thing built goes on top of something you understand
instead of on top of a pile.

---

## Run it

**Double-click `Start jarvis-core.bat`.** That is the whole thing.

A black window opens, starts the server, and opens the page in your browser.
Type in the box, press Send, and the answer appears. Leave the black window
open - that is what keeps Jarvis running. Close it and Jarvis stops.

There is nothing to install, and the page is one file inside this folder, so it
works on a PC with no network at all.

### The command line, if you prefer it

```powershell
py -3 -m jarvis_core
```

Then open <http://127.0.0.1:4719> yourself. That is the same page the
double-click opens.

```powershell
py -3 run_tests.py
```

The tests - 43 of them, in about three seconds, and none of them need a model
or the internet.

If the port is already taken, the program says so plainly rather than showing a
traceback - the owner runs a bigger Jarvis on 4719, so this is the likely one:

```
Port 4719 is already in use - something else is running there.
  Close it, or start this with --port 4720: py -3 -m jarvis_core --port 4720
```

The `.bat` says the same thing, before it starts anything, and keeps its window
open so you can read it.

You also need a model to chat with, and that part is not bundled:

```powershell
ollama pull qwen3:8b
```

(The default model name is in `settings.json`. If you already have a different
one, `ollama list` shows its name - put that name in the file and you are done.
`/api/status` will tell you plainly if the name is wrong.)

### Try it

```powershell
curl.exe -s http://127.0.0.1:4719/api/status
```

```powershell
curl.exe -s -X POST http://127.0.0.1:4719/api/chat -H "Content-Type: application/json" -d "{\"message\":\"hello\"}"
```

Stop it with Ctrl+C, or by closing the window.

---

## What it is NOT

This list is the point of the whole document. Every line is a thing you might
assume a "Jarvis" has, and this build deliberately does not.

- **No cloud model, no API keys, no telemetry.** No setting can point it at a
  cloud address; the program refuses to start if you try. (Rule 1)
- **No public tunnel, nothing shared off the PC.** It answers on `127.0.0.1`
  and nothing else. (Rule 2)
- **No secrets in any file it writes.** `settings.json` has no key field, and
  the log has no words in it at all - only lengths and fingerprints.
- **No memory.** It forgets everything the moment you stop it.
- **No streaming.** One complete reply per request.
- **Two actions, and neither is impressive.** See the table below.

---

## The gate: the one idea that matters

Everything the program can *do* is a **named action**. There is no "run this
code" entry point and no way to call a function by name from outside. Each name
in the settings table has a **tier**, and the tier decides what happens.

| Tier | What happens when it is called |
|---|---|
| `auto` | Runs straight away. Only ever given to actions that cannot touch anything. |
| `ask` | A **card** is raised. Nothing runs until you decide. |
| `never` | Refused outright. No card can approve it. |
| `unclassified` | **Not in the table at all.** Refused. No card either. |

The shipped table is two lines:

| Action | Tier | What it does |
|---|---|---|
| `get_time` | `auto` | Reads the clock on this PC. Cannot read a file, open a socket or change anything. |
| `write_note` | `ask` | Writes one small text file into `notes/`. Waits for you, every single time. |

### Why "not in the table" fails closed, and does not become `ask`

This is the design decision worth understanding before changing anything.

Defaulting an unknown name to `ask` *sounds* safer: a card still appears, so a
person still has to say yes. But it means a typo, a renamed action, or a
half-finished new feature produces a **working** card, and the thing behind
that name has never been reviewed by anyone. The gate would be advertising a
permission path for code nobody has read.

Failing closed means the same mistake produces a clear refusal instead, and you
find out immediately. A refusal you can see beats a permission you did not mean
to give.

There is a test for exactly this (`test_gate.py::test_unclassified_action_FAILS_CLOSED`),
and it has been proved to fail when the rule is broken.

---

## Cards: how "wait for me" works

When an `ask` action is called, the server raises a card and answers **at once**
- it does not hold the connection open:

```json
{
  "ok": true,
  "ran": false,
  "tier": "ask",
  "waiting_for_approval": "042a2d34562b",
  "then": "POST /api/card/042a2d34562b with {\"decision\": \"approve\"} ..."
}
```

`ran: false` is the important field. Nothing has happened yet.

Then you answer it:

```powershell
curl.exe -s -X POST http://127.0.0.1:4719/api/card/<id> -H "Content-Type: application/json" -d "{\"decision\":\"approve\"}"
```

- **`approve`** runs the action and puts the result on the card.
- **`deny`** runs nothing, ever.
- **A second answer** is refused. The first answer is the one that counted,
  including approving something you already denied.
- **After the time limit** (120 seconds by default, `card_ttl_seconds` in
  settings) the card is `expired`, and approving it is refused. An old "yes" is
  not a decision about the thing in front of you now.

`GET /api/card/<id>` says where a card got to at any point.

---

## The five routes

| Route | What it does |
|---|---|
| `GET /` | The page you type in: a text box and a Send button. HTML, not JSON. It calls `POST /api/chat` and prints the reply, and that is all it can do. |
| `GET /api/status` | Version, whether the local model is reachable, what this build does and does not do, and the whole tier table. |
| `POST /api/chat` | `{"message": "..."}` - one question to the local model, one answer. |
| `POST /api/chat` with `"action"` | Runs a named action instead of chatting. `get_time` runs; `write_note` raises a card. Also used for `{"action": "get_time", "args": {}}`. |
| `GET /api/card/<id>` | The card's state: pending, approved, denied or expired. |
| `POST /api/card/<id>` | `{"decision": "approve"}` or `{"decision": "deny"}`. |

**The page adds no power.** It is a text box that calls the same route `curl`
calls, and it cannot list a card, approve one, or name an action - this build
has no route that could. Everything the gate does still happens on the server,
exactly as before, and the HTML has every style and every line of script inside
it, with nothing loaded from the internet (rules 1 and 2). There is a test that
fails if the page ever mentions an address, so it cannot quietly grow a
downloaded font or a CDN script.

**Anything else is a 404 with a plain sentence.** Unknown route, unknown action,
malformed body, missing setting: refuse clearly rather than guess.

---

## If the model is not there

It says so, plainly, and does not crash.

If Ollama is not running, `/api/status` reports `reachable: false` with the
sentence *"Could not reach the model: ... Is Ollama running?"*, and `/api/chat`
answers HTTP 503 with that same sentence. If Ollama is running but the model in
`settings.json` is not installed, the message names the model you do have
installed and tells you the `ollama pull` line to fix it.

The program never pretends an answer happened, and never invents one.

---

## Settings and the log

**`settings.json` is created the first time you run the program, beside it.**
It is not in this repository, and it must never be - there is a test that fails
if it ever is. A settings file that git tracks is a settings file that will
eventually hold a key, and then that key is in the history forever.

**`logs/jarvis.jsonl` is the only log.** One JSON object per line - one line per
chat turn, one line per card decision. It never contains your words. A turn
records the *length* of the message and a *fingerprint* (a short one-way hash
of it), which is enough to look things up later and not enough to leak
anything. Card decisions record the action's name and the decision, which is
how you would want to audit it.

Both files are git-ignored. Delete them any time; they are rebuilt.

---

## The files

```
jarvis-core/
  README.md          this file
  CLAUDE.md          the short working rules, and a pointer to the long one
  Start jarvis-core.bat  double-click this: starts the server and opens the page
  run_tests.py       runs every test file in tests/, in order, one at a time
  requirements.txt   deliberately empty - nothing to install
  .gitignore         settings.json, logs/, __pycache__, *.pyc, .env, *.key
  jarvis_core/
    __init__.py      the version number, in one place
    __main__.py      `py -3 -m jarvis_core` starts the server
    server.py        the HTTP routes
    page.html        the page at GET / - one file, no CDN, no build step
    gate.py          the action table, the tiers, the fail-closed rule
    cards.py         raise, wait for, decide, expire
    actions.py       the two example actions
    model.py         the Ollama client
    config.py        settings, created on first run
    journal.py       the JSONL log
  tests/
    test_gate.py     a denied action never runs; an unclassified one FAILS CLOSED
    test_cards.py    approve runs it; deny does not; an expired card cannot be approved
    test_config.py   first run creates settings; nothing secret is tracked by git
    test_server.py   /api/status and /api/chat answer, over a real socket, and
                     GET / serves the page that only calls /api/chat
    test_journal.py  a token-shaped string never reaches the log
    _helpers.py      a temporary folder and a fake model (not a test itself)
```

---

## Rules are structure, not prose

Where a rule could be enforced by code, it is. Where it could not, it is a test
instead of a sentence.

| Rule | How it is enforced |
|---|---|
| 1. Private things stay on the local model | `test_journal.py` - a token goes in, and is provably not in the log. Plus `config.py`, which refuses to start on a non-loopback model address. |
| 2. Never open a public tunnel | The server binds `127.0.0.1`; `test_server.py` proves the default can never be `0.0.0.0`. |
| 3. Keys are never logged or written in plain text | `test_config.py` - the settings keys are checked, and `git ls-files` is checked for `settings.json`, `logs/`, `*.key`, `.env`. |
| 4. Never auto-approve anything | `test_gate.py` and `test_cards.py` - the whole of both files. |
| 5. Non-commercial build | Not a rule code can enforce. See `CLAUDE.md`; the licence is yours to pick, and this build ships without one on purpose. |

---

## Why `urllib` and `http.server` and no library

`requirements.txt` is empty, and that is a decision, not an oversight.

`urllib` (Python's built-in web client) and `http.server` (Python's built-in
web server) come with Python. That means: nothing to install, nothing to pin,
nothing to update, and nothing that could one day start sending data somewhere
on its own. The whole job here is "POST a small JSON object to `127.0.0.1` and
read a JSON object back" - about twenty lines of `urllib`.

A web framework would save maybe forty lines and add a dependency, a version to
worry about, and a hundred pages of behaviour to learn. **If this ever needs
more than these five routes, that is the moment to reconsider** - not before.

The page at `GET /` follows the same rule. It is hand-written HTML in one file
that Python serves as-is: no framework, no npm, no build step, and nothing
fetched from anywhere. It is here because typing a `curl` command into a second
window is not something a person should have to do - not because this build
wants to become a front end.

The same reasoning covers the tests: no pytest, because `run_tests.py` is about
sixty lines and keeps "clone it and run it" literally true.

---

## Not built yet, and what each one would need

This is the roadmap. It is not a promise and not a wish list - each line says
what the thing would need before it could exist, so the honest answer to "can
it do X" is always available.

Nothing in this list is started. Adding any of them breaks no rule from
`CLAUDE.md` by itself, but each one changes what the program can touch, so each
one needs its own named action and its own tier in the gate.

**Touching the PC**

- *Reading files the owner picks* - a new action per kind of file, tier `ask`,
  and a real answer to "which folder is allowed".
- *Writing files outside `notes/`* - tier `ask` (already the pattern), plus a
  path check so an approved note cannot be aimed at a system file.
- *Running a shell command* - tier `never` until there is a sandbox, and
  honestly, probably after that too.
- *Screen reading* - a screen-capture library, a model that understands
  pictures, and tier `ask` every single time.
- *Mouse and keyboard control* - needs a way to stop it mid-action, and a
  visible "Jarvis is on the keyboard" sign.

**Leaving the PC** (each of these is a new named way out, and rule 1 applies to
all of them)

- *Web search* - picks a provider, sends the search words somewhere. Needs a
  card showing the exact words, and a rule for when private things could slip in.
- *Email* - needs an account, a credential (which then needs rule 3 care), and
  one card per email showing every recipient and the whole text.
- *Calendar* - read-only first, via a private link treated like a password.
- *Weather and news* - the same shape as web search, and probably the same card.

**Talking and listening**

- *Voice in and out* - a speech library, a microphone, and a decision about
  whether a spoken "yes" counts as an approval (this build says no: cards are
  decided by a deliberate act, not by a word in the room).
- *Wake word ("Hey Jarvis")* - always-on listening is a large new surface, and
  it needs its own off switch that starts off.

**Remembering**

- *Memory* - a file or database, an encryption decision, a "forget" that really
  forgets, and a rule for what is learned from the owner's own words only.
- *Chat history* - the same, plus an answer to where it is stored and who can
  read it.

**Being reached**

- *A phone app* - the server would need a second reachable address, which means
  a private network (Tailscale or similar), never a public tunnel. Rule 2.
- *Plugins and MCP servers* - a card to add one, a card when it changes, and a
  rule that every call still goes through the gate.

**The model itself**

- *Streaming answers* - Server-Sent Events, and a way to cancel one.
- *Switching models* - a route that lists what is installed, and a card per
  switch (the model is a thing that changes behaviour, so it waits).
- *More than one model at once* - a second card, and a measurement to prove it
  helps before it is built.
