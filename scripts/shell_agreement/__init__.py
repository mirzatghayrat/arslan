"""Real-shell comparison for terminal_policy (S2a-3 d, the user's decision of 2026-10-22).

Every command in a corpus is run by the real shell the product uses (`/bin/bash -p -c`), inside a
disposable bubblewrap sandbox: the root read-only, a fresh empty home, no network, and every program
directory (/bin, /usr/bin, /usr/sbin, /usr/local/bin, /opt/homebrew/bin …) replaced by stubs that
only record "I was started, with these arguments". What the shell actually started is then held
against what terminal_policy decided for the text: a program the shell started at a higher layer
than the verdict, or one the reader never listed under a "run" verdict, is a disagreement.

Runs only on Linux with bwrap, meant for a one-time CI machine or a container; it refuses on macOS.
See README.md in this folder.
"""
