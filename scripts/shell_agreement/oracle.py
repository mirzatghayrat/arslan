"""What the shell started, held against what the policy decided."""
from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass

from scripts.shell_agreement.sandbox import Run, Started
from server.services import shell_grammar, terminal_policy

RANK = {"run": 0, "ask": 1, "forbid": 2}

#: The kinds of disagreement, hardest first.
UNLISTED = "unlisted"        # judged run, yet the shell started a program the reader never listed
RUN_ABOVE = "run-above"      # judged run, yet the shell started a program that alone would ask or be forbidden
ASK_ABOVE = "ask-above"      # judged ask, yet the shell started a program that alone is forbidden (the floor)
HARD = frozenset({UNLISTED, RUN_ABOVE})


@dataclass(frozen=True)
class Disagreement:
    command: str
    verdict: str                 # "<level>:<rule>" for the whole text
    started: str                 # the plain argv the shell started, as one line
    kind: str                    # UNLISTED, RUN_ABOVE or ASK_ABOVE
    detail: str
    stub_exit: int

    def as_dict(self) -> dict:
        return asdict(self)


def plain(started: Started) -> str:
    """The started program as a plain command line: its name and the arguments the shell gave it."""
    return shlex.join([started.name, *started.args])


def own_level(line: str) -> tuple[str, str]:
    """The policy's verdict on a plain argv the shell started. The shell already resolved the argv, so
    the only `unreadable` that counts against it is the reader's own (inline code, a code variable …):
    when the reader understands the line and `unreadable` is its only rule (shell_text's grep-pattern
    heuristic on a bare `grep -e`), the line ranks as run."""
    verdict = terminal_policy.assess(line)
    if verdict.level == "ask" and terminal_policy.ask_rules(line) <= {terminal_policy.UNREADABLE} \
            and shell_grammar.read(line).understood:
        return "run", ""
    return verdict.level, verdict.rule


def judge(run: Run) -> list[Disagreement]:
    """Every way the shell's run of `run.command` disagrees with the policy.

    - run-above / ask-above: the policy's verdict on a started program's plain argv is a higher layer
      than its verdict on the whole text. A "run" text started something that would ask; an "ask" text
      started something forbidden. Arguments are what the shell expanded them to.
    - unlisted: the text was judged "run", which the policy gives only when the reader understood the
      whole text, yet the shell started a program the reader did not list.
    """
    verdict = terminal_policy.assess(run.command)
    label = f"{verdict.level}:{verdict.rule}" if verdict.rule else verdict.level
    found: list[Disagreement] = []
    if verdict.level == "forbid" or not run.started:
        return found
    for started in run.started:
        line = plain(started)
        level, rule = own_level(line)
        if RANK[level] > RANK[verdict.level]:
            kind = RUN_ABOVE if verdict.level == "run" else ASK_ABOVE
            found.append(Disagreement(run.command, label, line, kind,
                                      f"the shell started it, and alone it is {level}:{rule}", run.stub_exit))
    if verdict.level == "run":
        reading = shell_grammar.read(run.command)
        if not reading.understood:
            found.append(Disagreement(run.command, label, "", UNLISTED,
                                      f"judged run although the reader did not understand it: {reading.why}",
                                      run.stub_exit))
        listed = {command[0].rsplit("/", 1)[-1] for command in reading.commands if command}
        for started in run.started:
            if started.name not in listed:
                found.append(Disagreement(run.command, label, plain(started), UNLISTED,
                                          f"the reader listed {sorted(listed)}", run.stub_exit))
    return found
