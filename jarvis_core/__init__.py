# ==============================================================================
# Author: James through Deepseek Harness
# Description: The package itself, and the one place the version number lives. Exports __version__, the only thing every other part reads to say which build it is.
# ==============================================================================

"""jarvis-core - the small, honest foundation for Jarvis.

One sentence of what this is: a local HTTP server that talks to a local model
(Ollama on this PC) and runs nothing at all unless the owner has said yes.

Why the version lives here: every part of the program that needs to say "which
build am I" imports it from one place, so there is no second number to forget.
"""

__version__ = "0.1.0"
