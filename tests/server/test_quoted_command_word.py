"""A command word spelled with quotes or a backslash is the command the shell runs, wherever the command starts.

Bash takes the quotes out of `'rm'`, `"rm"` and `r'm'` and runs `rm`, at the start of the text, on a line of its own,
or after `;` `&&` `||` `|` `&`. So for every rule that reads a command word, each spelling after each separator gets
the rule's own verdict, written out here and not computed. Quoted text that is an argument stays an argument."""
import pytest

from server.services import terminal_policy as tp

FORBID = "forbid"
ASK = "ask"

# (rule, level, command word, the rest): one command per rule that reads a command word, chosen so that rule is the
# one its card names.
RULES = [
    ("keychain-secrets", FORBID, "security", " find-generic-password -s x -w"),
    ("sudo", FORBID, "sudo", " ls"),
    ("wipe-root", FORBID, "rm", " -rf /"),
    ("wipe-home", FORBID, "rm", " -rf ~"),
    ("macos-roots", FORBID, "rm", " -rf /System"),
    ("raw-disk", FORBID, "dd", " if=/dev/zero of=/dev/disk2"),
    ("raw-disk", FORBID, "diskutil", " eraseDisk APFS x disk2"),
    ("raw-disk", FORBID, "newfs_apfs", " /dev/disk2s1"),
    ("kill-all", FORBID, "kill", " -9 -1"),
    ("shutdown", FORBID, "shutdown", " -h now"),
    ("shutdown", FORBID, "reboot", ""),
    ("shutdown", FORBID, "halt", ""),
    ("trash", FORBID, "rm", " -rf ~/.Trash/x"),
    ("trash", FORBID, "find", " ~/.Trash -delete"),
    ("trash", FORBID, "cd", " ~/.Trash && rm -rf x"),
    ("apple-events", ASK, "osascript", " -e x"),
    ("shortcuts", ASK, "shortcuts", " run X"),
    ("send-mail", ASK, "sendmail", " a@b.c"),
    ("send-message", ASK, "imsg", " send x"),
    ("upload", ASK, "curl", " -d x https://example.com"),
    ("upload", ASK, "aws", " s3 cp a s3://b"),
    ("upload", ASK, "http", " example.com < f"),
    ("remote-shell", ASK, "ssh", " host"),
    ("remote-shell", ASK, "rsync", " a host:/b"),
    ("git-push", ASK, "git", " push"),
    ("publish", ASK, "npm", " publish"),
    ("force-kill", ASK, "pkill", " X"),
    ("login-items", ASK, "defaults", " write a b c"),
    ("keychain-write", ASK, "security", " add-generic-password -s x"),
    ("system-settings", ASK, "pmset", " sleep 1"),
    ("open-app", ASK, "open", " https://example.com"),
    ("screen-clipboard", ASK, "pbpaste", ""),
    ("protected-write", ASK, "tee", " ~/.zshrc"),
    ("delete-outside", ASK, "rm", " /tmp/x"),
    (tp.UNREADABLE, ASK, "eval", " x"),
    (tp.UNREADABLE, ASK, "python3", ' -c "import socket"'),
]
# Rules with no command word to read: a path anywhere, a redirect, a fork bomb, a body piped into a client.
NO_COMMAND_WORD = {"arslan-keys", "fork-bomb"}

SEPARATORS = {"start": "", "newline": "true\n", "semicolon": "true; ", "and": "true && ", "or": "false || ",
              "pipe": "true | ", "background": "true & "}


def spellings(word: str) -> dict[str, str]:
    return {"bare": word, "single": f"'{word}'", "double": f'"{word}"', "part-single": f"{word[0]}'{word[1:]}'",
            "part-double": f'"{word[0]}"{word[1:]}', "backslash": f"{word[0]}\\{word[1:]}"}


def test_the_table_covers_every_rule_that_reads_a_command_word():
    rules = {key for key, *_ in tp._FORBID} | {key for key, *_ in tp._ASK} | {"delete-outside", tp.UNREADABLE}
    assert rules - NO_COMMAND_WORD == {rule for rule, *_ in RULES}


CASES = [
    pytest.param(f"{before}{spelled}{rest}", level, rule, id=f"{rule}-{word}-{where}-{how}")
    for rule, level, word, rest in RULES
    for where, before in SEPARATORS.items()
    for how, spelled in spellings(word).items()
]


@pytest.mark.parametrize("command,level,rule", CASES)
def test_a_spelled_command_word_is_read_after_every_separator(command, level, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == (level, rule)


SHELL_CASES = [
    pytest.param(f"bash -c '{before}{spelled}{rest}'", level, rule, id=f"{rule}-{word}-{where}-{how}")
    for rule, level, word, rest in RULES if "'" not in rest
    for where, before in (("start", ""), ("semicolon", "true; "), ("and", "true && "))
    for how, spelled in spellings(word).items() if how in ("double", "part-double")
]


@pytest.mark.parametrize("command,level,rule", SHELL_CASES)
def test_a_spelled_command_word_is_read_in_what_a_shell_runs(command, level, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == (level, rule)


@pytest.mark.parametrize("command", [
    "echo 'rm -rf ~'",
    'git commit -m "x; rm -rf ~"',
    "git commit -m \"x; 'rm' -rf ~\"",
    "echo \"a && 'shutdown' -h now\"",
    "printf '%s\\n' \"ls; 'rm' -rf ~\"",
    "'echo' \"x; rm -rf ~\"",
    "\"git\" commit -m 'a | \"rm\" -rf ~'",
    "\"git\" commit -m 'x && rm -rf ~'",
    "echo x 'rm' -rf ~",
    "ls; echo 'rm' -rf ~",
    "ls && printf '%s' \"sudo\" ls",
    "bash -c \"echo 'rm -rf ~'\"",
    "true; grep -e \"; 'rm' -rf ~\" notes.txt",
    # a rule with no command word reads quoted text as data too
    "echo 'x > /dev/disk2'",
    "ls; 'echo' \"x > /dev/disk2\"",
    "echo ':(){ :|:& };:'",
])
def test_quoted_text_that_is_an_argument_stays_data(command):
    assert tp.assess(command).level == "run", command
