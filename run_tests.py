"""Run every test file in tests/, in order, one at a time.

    py -3 run_tests.py

Why no pytest: `requirements.txt` is empty on purpose, so this program has
nothing to install. That is worth about sixty lines of test runner, because it
means "clone it and run it" is literally two commands on any PC with Python.

"One at a time" also matters. Each file is imported fresh, so a test cannot
leave a mess behind for the next file - and the output shows which file you are
in, so a failure tells you where to look.
"""

from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent / "tests"


def test_files() -> list[Path]:
    """Every test_*.py in tests/, in alphabetical order (so it is one order)."""
    return sorted(TESTS_DIR.glob("test_*.py"))


def test_functions(module) -> list:
    """Every function whose name starts with test_, in the order it is written.

    The order is taken from the file's own text rather than from the module's
    dictionary, because a dictionary's order is an implementation detail and
    the file is what a person reads.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    order = [line.split("def ", 1)[1].split("(", 1)[0].strip()
             for line in source.splitlines()
             if line.startswith("def test_")]
    found = [(name, getattr(module, name)) for name in order if hasattr(module, name)]
    return found or [(name, value) for name, value in vars(module).items()
                     if name.startswith("test_") and callable(value)]


def main() -> int:
    if str(TESTS_DIR) not in sys.path:
        # So the test files can `from _helpers import ...` without a package.
        sys.path.insert(0, str(TESTS_DIR))

    files = test_files()
    if not files:
        print("No test files found in tests/. That is a failure, not a pass.")
        return 1

    passed = 0
    failures: list[tuple[str, str, str]] = []

    for path in files:
        print(f"\n{path.name}")
        module_name = path.stem
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - an import error is a test failure too
            print(f"  IMPORT FAILED")
            failures.append((path.name, "<import>", traceback.format_exc()))
            continue

        for name, function in test_functions(module):
            try:
                function()
            except Exception:  # noqa: BLE001
                print(f"  FAIL  {name}")
                failures.append((path.name, name, traceback.format_exc()))
            else:
                print(f"  ok    {name}")
                passed += 1

    print("\n" + "-" * 60)
    if failures:
        for file_name, test_name, detail in failures:
            print(f"\nFAILED: {file_name}::{test_name}")
            print(detail.rstrip())
        print(f"\n{passed} passed, {len(failures)} failed.")
        return 1
    print(f"{passed} passed, 0 failed. Every test in tests/ ran.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
