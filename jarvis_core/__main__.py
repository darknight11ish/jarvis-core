"""`py -3 -m jarvis_core` starts the server.

Everything real lives in server.py. This file exists so there is one obvious
way in, and so the exit code comes from one place.
"""

from __future__ import annotations

import sys

from .server import main

if __name__ == "__main__":
    sys.exit(main())
