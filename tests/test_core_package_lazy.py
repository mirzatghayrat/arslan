"""Importing a module of arslan.core loads only what it needs (C2d).

The server's attachment import uses arslan.core.chunking (server/services/ingest.py). The package's
__init__ used to pre-import the dialogue engine of the legacy `arslan` command line, so every
chunking import loaded it too; with that command line deleted, the package imports nothing.
"""
import subprocess
import sys


def test_importing_chunking_does_not_load_the_dialogue_engine():
    probe = ("import sys, arslan.core.chunking; "
             "print(sorted(m for m in sys.modules if m.startswith('arslan.core')))")
    loaded = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert "arslan.core.chunking" in loaded
    assert "arslan.core.dialogue" not in loaded
