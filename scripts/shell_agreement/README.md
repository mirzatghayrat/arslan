# shell_agreement: does the real shell agree with the policy?

S2a-3 d (card `docs/plans/0162/S2a-command-three-layers.md`, section S2a-3). The policy says
"run" only when `shell_grammar` understood the whole command and listed every program it starts.
This harness checks that claim against the real shell instead of against hand-written cases.

## How it works

1. `stubs.build()` makes a program directory: every name that exists in the host's program
   directories, every word of the corpus, and the wrappers the reader knows, each a symlink to a
   script that appends one record (`$0` and its arguments) to a trace file and exits. Wrapper
   programs (`env`, `nohup`, `nice`, `timeout`, `sudo`, `xargs`, `find -exec` …) record themselves
   and then start the command they were given, as the real program would. Only `bash` and `sh` are
   the real binary.
2. `sandbox.run()` starts `bwrap`: the host root read-only, that directory bound over `/usr/bin`,
   `/usr/sbin`, `/usr/local/bin` and the other program directories, empty tmpfs over `/home`,
   `/root`, `/tmp`, `/run` and `/var/tmp`, a fresh work folder as `$HOME` and cwd, no network, no
   inherited environment, a time limit. Then `/bin/bash -p -c <command>`, as `terminal_exec` does.
   Each command runs twice: once with every stub succeeding, once with every stub failing, so both
   sides of `&&` / `||` are taken.
3. `oracle.judge()` compares. For each program the shell started, the policy's own verdict on that
   plain argv must not be above the verdict on the whole text; under a "run" verdict every started
   program must be one the reader listed.
4. `mutate.forms()` wraps each corpus command mechanically (a wrapper program in front, a chain, a
   compound command, `bash -c` with the text re-quoted …) and the same comparison runs on each form.

## Where it may run

Only on Linux with `bwrap` (bubblewrap), on a one-time CI machine or inside a container. It refuses
to start on macOS (`sandbox.require()`). Nothing in it reads keys or tokens: the sandbox gets an
empty environment and sees no home directory.

## Running

```bash
# the corpus harvested from the repository's own tests (default), with the mechanical forms
.venv/bin/python -m scripts.shell_agreement --mutate
# an external corpus: one command per line, or JSON lines with a "command" field
.venv/bin/python -m scripts.shell_agreement --corpus commands.jsonl --jobs 8 --report out.json
```

Exit status 1 when any disagreement was found; the report lists each one with the text, the verdict,
and what the shell started. In CI: the `shell-agreement` job in `.github/workflows/ci.yml`.

## What it does not cover

- Code inside another interpreter (`python3 -c …`, an awk program): the stub records the interpreter
  and runs nothing. The reader already asks for those. What that code would start is out of reach.
- Programs outside the wrapper table that run commands from their arguments or files. The sandbox
  contains those today (card S2a-3, remaining risk).
- The shell is Linux bash 5.x; the product's is macOS bash 3.2. The reader models a subset of 3.2,
  so what it understands should read the same in both, but this harness does not prove it.
