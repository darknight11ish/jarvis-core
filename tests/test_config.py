"""Settings on first run, and the rule that no secret is ever in a file git tracks.

Two halves:

  * Running with no settings.json writes one, with safe defaults, and writes it
    only once - running again must not overwrite the owner's edits.
  * The settings file is git-ignored, its keys are all safe-because-there-are-
    no-secrets, and the program refuses a model address that is not this PC.

The last test is the interesting one. It checks the real repository, not a
temporary copy: if `git ls-files` ever shows settings.json or anything under
logs/, the test goes red. Rule 3 as a test rather than a paragraph.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import _helpers
from _helpers import CheckFailed, check, check_equal, check_in, sandbox

from jarvis_core import config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_first_run_writes_a_settings_file():
    with sandbox() as box:
        path = Path(box["settings_path"])
        check(path.exists(), "settings.json should exist after the first load")
        written = json.loads(path.read_text(encoding="utf-8"))
        check_equal(written, config.DEFAULTS, "the file written on first run")


def test_the_defaults_are_the_safe_ones():
    """If someone changes a default to something looser, this fails loudly."""
    defaults = config.DEFAULTS
    check_equal(defaults["server"]["host"], "127.0.0.1", "the default host")
    check_equal(defaults["server"]["port"], 4719, "the default port")
    check_equal(defaults["model"]["provider"], "ollama", "the default provider")
    check(defaults["model"]["base_url"].startswith("http://127.0.0.1:"),
          "the default model address must be on this PC")
    check_equal(defaults["security"]["tiers"]["get_time"], "auto", "get_time's tier")
    check_equal(defaults["security"]["tiers"]["write_note"], "ask", "write_note's tier")
    check(defaults["security"]["card_ttl_seconds"] > 0, "cards need a real time limit")


def test_a_second_run_keeps_the_owners_edits():
    with sandbox() as box:
        path = Path(box["settings_path"])
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["model"]["name"] = "some-other-local-model"
        path.write_text(json.dumps(edited), encoding="utf-8")

        again = config.load(path)

        check_equal(again["model"]["name"], "some-other-local-model", "the model name")
        check_equal(json.loads(path.read_text(encoding="utf-8")), edited,
                    "the file on disk after a second load")


def test_a_partly_deleted_settings_file_is_filled_back_in():
    """A menu of settings that lost a whole section must not lose the
    security section with it."""
    with sandbox() as box:
        path = Path(box["settings_path"])
        path.write_text(json.dumps({"server": {"port": 5000}}), encoding="utf-8")

        fixed = config.load(path)

        check_equal(fixed["server"]["port"], 5000, "the setting that was kept")
        check_equal(fixed["server"]["host"], "127.0.0.1", "the setting filled back in")
        check_equal(fixed["security"]["tiers"]["write_note"], "ask", "the gate's table")


def test_a_damaged_settings_file_stops_instead_of_guessing():
    """Stopping is the safe answer. Quietly using defaults could mean quietly
    using a looser gate than the owner wrote."""
    with sandbox() as box:
        path = Path(box["settings_path"])
        for broken in ("{not json", "", "[]", "null"):
            path.write_text(broken, encoding="utf-8")
            try:
                config.load(path)
            except config.ConfigError:
                continue
            raise CheckFailed(f"settings.json containing {broken!r} should stop the program")


def test_a_cloud_model_address_is_refused():
    """Rule 1, enforced in code: nothing private leaves the PC."""
    with sandbox() as box:
        path = Path(box["settings_path"])
        original = json.loads(path.read_text(encoding="utf-8"))

        for address in ("https://api.openai.com", "http://192.168.1.50:11434",
                        "http://example.com:11434"):
            changed = dict(original)
            changed["model"] = dict(original["model"], base_url=address)
            path.write_text(json.dumps(changed), encoding="utf-8")
            try:
                config.load(path)
            except config.ConfigError:
                continue
            raise CheckFailed(f"the model address {address} should be refused")

        changed = dict(original)
        changed["model"] = dict(original["model"], provider="openai")
        path.write_text(json.dumps(changed), encoding="utf-8")
        try:
            config.load(path)
        except config.ConfigError:
            pass
        else:
            raise CheckFailed("a non-Ollama provider should be refused")


def test_no_settings_key_is_a_secret():
    """Every key in the settings file is known, and none of them is a place a
    password would go. A secret has no home in this file, which is why none is
    ever written into it."""
    suspicious = ("key", "token", "secret", "password", "passwd", "credential", "auth")

    def walk(section: object, prefix: str = "") -> None:
        if isinstance(section, dict):
            for name, value in section.items():
                where = f"{prefix}.{name}" if prefix else str(name)
                lowered = str(name).lower()
                for word in suspicious:
                    check(word not in lowered,
                          f"settings key {where!r} looks like a secret would live there. "
                          "Secrets belong in the environment, never in settings.json.")
                walk(value, where)

    walk(config.DEFAULTS)


def test_nothing_secret_can_be_tracked_by_git():
    """The real repository, checked with the real git.

    If this fails, a settings.json or a log has been committed - and a secret
    in a commit is a secret forever, because git keeps the history.
    """
    check((REPO_ROOT / ".git").is_dir(), "this test expects to run inside the git repository")

    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("settings.json", "logs/", "*.key", ".env"):
        check_in(pattern, gitignore, "the .gitignore file")

    answer = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    tracked = [line.strip() for line in answer.stdout.splitlines() if line.strip()]

    for name in tracked:
        lowered = name.lower()
        check(not lowered.endswith("settings.json"),
              f"{name} is tracked by git - the settings file must never be committed")
        check(not lowered.startswith("logs/"),
              f"{name} is tracked by git - the log folder must never be committed")
        check(not lowered.endswith(".key") and not lowered.endswith(".env"),
              f"{name} is tracked by git - secrets must never be committed")
        check("__pycache__" not in lowered and not lowered.endswith(".pyc"),
              f"{name} is tracked by git - build leftovers should not be")
