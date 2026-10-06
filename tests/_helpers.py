# ==============================================================================
# Author: James through Deepseek Harness
# Description: A tiny test helper - not a test itself, the runner skips this file. Exports sandbox(), the throwaway folder and settings every file test uses, FakeOllama, the stand-in for the model, and the check() family of assertions.
# ==============================================================================

"""A tiny test helper. Not a test itself - the runner skips this file.

Two things live here:

1. `sandbox()` - a throwaway folder and a settings.json inside it. Every test
   that touches a file uses one, so the tests never write to the real
   `logs/` or `notes/` and can never leave a `settings.json` behind in the
   repository. (If a test wrote one, `test_config.py` would fail - which is
   the point of that test.)

2. `FakeOllama` - a stand-in for the local model. It is swapped in for
   `urllib.request.urlopen`, so the tests run in a fraction of a second, need
   no model at all, and give the same answer on any PC.

There is deliberately no test framework here. `run_tests.py` finds functions
whose names start with `test_` and calls them, and a test passes by not
raising. That is about twenty lines in the runner instead of a dependency in
requirements.txt.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from jarvis_core import config


class CheckFailed(Exception):
    """Raised when a test's expectation is not met."""


def check(condition: Any, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def check_equal(got: Any, want: Any, what: str = "value") -> None:
    if got != want:
        raise CheckFailed(f"{what}: expected {want!r}, got {got!r}")


def check_in(needle: Any, haystack: Any, what: str = "text") -> None:
    if needle not in haystack:
        raise CheckFailed(f"{what}: expected to find {needle!r} in {haystack!r}")


@contextmanager
def sandbox() -> Iterator[dict[str, Any]]:
    """A temporary folder that holds a fresh settings.json and nothing else."""
    with tempfile.TemporaryDirectory(prefix="jarvis-test-") as folder:
        base = Path(folder)
        settings_path = base / "settings.json"
        settings = config.load(settings_path)  # first run: writes the defaults
        yield {
            "base": base,
            "settings": settings,
            "settings_path": str(settings_path),
            "journal_path": str(config.journal_path(settings, settings_path)),
        }


class FakeHTTPResponse:
    """The little bit of an HTTP response our code actually uses."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers: dict[str, str] = {"Content-Type": "application/json"}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class FakeOllama:
    """Stands in for Ollama. Records what was asked, and answers as told.

    `reply` is what the model "says". If `echo` is on, the reply contains the
    question - which is how the journal test makes sure an echoed secret would
    still not reach the log.
    """

    def __init__(self, reply: str = "This is a test answer.", models: list[str] | None = None,
                 reachable: bool = True, echo: bool = False) -> None:
        self.reply = reply
        self.models = models if models is not None else ["qwen3:8b"]
        self.reachable = reachable
        self.echo = echo
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: Any, data: bytes | None = None, timeout: float | None = None):
        target = url if isinstance(url, str) else getattr(url, "full_url", str(url))
        self.calls.append({"url": target, "data": data, "timeout": timeout})
        if not self.reachable:
            raise OSError("test: nothing is listening on that port")

        if target.endswith("/api/tags"):
            return FakeHTTPResponse(
                {"models": [{"name": name} for name in self.models]}
            )
        if target.endswith("/api/chat"):
            asked = ""
            if data:
                try:
                    asked = json.loads(data.decode("utf-8"))["messages"][-1]["content"]
                except (KeyError, IndexError, ValueError):
                    asked = ""
            text = f"{self.reply} {asked}" if self.echo else self.reply
            return FakeHTTPResponse({"message": {"role": "assistant", "content": text}})
        raise AssertionError(f"The fake model was asked for an unexpected address: {target}")


def install_fake_ollama(fake: FakeOllama) -> Callable[[], None]:
    """Point every module's urlopen at the fake. Returns a function to undo it."""
    from jarvis_core import model

    original = model.urllib.request.urlopen
    model.urllib.request.urlopen = fake  # type: ignore[assignment]

    def restore() -> None:
        model.urllib.request.urlopen = original  # type: ignore[assignment]

    return restore
