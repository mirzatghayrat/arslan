"""LOOP1 d2: terminal_policy reads a command through shell_grammar once. The forbid floor's named rules, layer ②'s
named rules, outside-reach and the not-understood check all read that one pass. A command the reader does not
understand keeps its named rules on the commands before the refusal, beside the rules on the raw text.

Its own file, not test_terminal_policy.py: the folder-tracking matrices read that file's parameters as a frozen corpus."""
import pytest

from server.services import shell_grammar, terminal_policy as tp


def _counted_reads(monkeypatch) -> list[str]:
    """Every pass of the reader over a text, from here on, with the policy's kept parses dropped first."""
    passes, real = [], shell_grammar._read_commands

    def counted(text, out):
        passes.append(text)
        return real(text, out)
    monkeypatch.setattr(shell_grammar, "_read_commands", counted)
    tp._parsed.cache_clear()
    return passes


@pytest.mark.parametrize("command", ["git status && rm build/out.txt", "ls docs | grep -n x > list.txt",
                                     "rm -rf ~", "git push origin main", "open -a Preview report.pdf",
                                     "python3 report.py", "ls; 'git' push; echo `x`"])
def test_a_command_is_parsed_once_for_every_reader(monkeypatch, command):
    """Inside and outside the sandbox. Before d2 an understood command was read twice: once for the named rules and
    once to say it was understood."""
    passes = _counted_reads(monkeypatch)
    for outside in (False, True):
        tp.assess(command, outside=outside)
        tp.ask_rules(command, outside=outside)
        tp.risk_grade(command, outside=outside)
    assert passes == [command]


@pytest.mark.parametrize("command, verdict", [
    ("ls; 'git' push; echo `x`", ("ask", "git-push")),
    ("x=1; 'shutdown'; echo `x`", ("forbid", "shutdown")),
    ("'open' -a Terminal; echo `x`", ("ask", "open-app")),
])
def test_a_command_the_reader_does_not_understand_keeps_its_named_rules_on_the_prefix(command, verdict):
    """Not understood (the backquotes), so its named rules read the commands before the refusal, which the text rules
    miss when the program word is quoted."""
    tp._parsed.cache_clear()
    assert (tp.assess(command).level, tp.assess(command).rule) == verdict
    assert verdict[0] == "forbid" or tp.ask_rules(command) == {verdict[1]}


def test_why_the_reader_does_not_understand_a_command_is_the_readers_own():
    """The one pass says what `shell_grammar.read` says: not understood, and why."""
    for command in ("python3 report.py", "echo `date`", "ls; 'git' push; echo `x`", "git status"):
        reading = shell_grammar.read(command)
        assert tp._not_understood(command) == ("" if reading.understood else reading.why)
