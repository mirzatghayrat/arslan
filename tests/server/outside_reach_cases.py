"""Public, inert command strings for the step-5 adversarial corpus."""
from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class Case:
    category: str
    id: str
    text: str
    readonly: bool = False
    gap: str = ""


CASES = []


def add(category, rows):
    CASES.extend(Case(category, name, text) for name, text in rows)


add("quoting", [
    ("single-program", "'open' note.txt"), ("double-program", '"batch"'),
    ("split-program", "laun'ch'ctl kickstart example"), ("escaped-program", r"o\pen note.txt"),
    ("split-verb", "security un'lock'-keychain example"),
    ("escaped-verb", r"security cre\ate-keychain example"),
    ("escaped-newline", "op\\\nen note.txt"),
    ("at-program", "a't' now"), ("shortcuts-verb", "shortcuts vi'ew' example"),
    ("network-verb", "networksetup -detect'new'hardware"),
    ("tccutil-verb", "tccutil ex'ample'"),
])
add("case", [("upper-program", "OPEN note.txt"), ("mixed-program", "LaUnChCtL kickstart example"),
             ("upper-verb", "security CREATE-keychain example"),
             ("mixed-verb", "security UnLoCk-keychain example"),
             ("upper-both", "SECURITY CREATE-KEYCHAIN example")])
add("paths", [("absolute", "/usr/bin/open note.txt"), ("relative", "tools/open note.txt"),
              ("dot", "./open note.txt"), ("slashes", "/usr//bin///batch"),
              ("quoted-path", "'/usr/bin/security' unlock-keychain example")])
add("wrappers", [(name, prefix + "open note.txt") for name, prefix in [
    ("env-assignment", "env NOTE=example "), ("env-options", "env -i -- NOTE=example "),
    ("env-unset", "env -u NOTE "), ("timeout", "timeout -s TERM 2 "),
    ("nice", "nice -n 5 "), ("nohup", "nohup "), ("caffeinate", "caffeinate -i "),
    ("xcrun", "xcrun --sdk macosx "), ("arch", "arch -arm64 "),
    ("command", "command -- "), ("exec", "exec -- "), ("builtin", "builtin command "),
    ("time", "time -p "), ("sudo", "sudo -n "), ("npx", "npx --yes "),
    ("bunx", "bunx --bun "), ("pnpm", "pnpm dlx "),
    ("stacked", "env NOTE=example nice -n 1 nohup "),
]])
for shell in ("sh", "bash", "zsh"):
    text = "open note.txt"
    for depth in (1, 2, 3):
        text = shell + " -c " + shlex.quote(text)
        add("carriers", [(f"{shell}-{depth}", text)])
add("find-xargs", [("find-exec", "find . -exec open note.txt \\;"),
                   ("find-execdir", "find . -execdir batch +"),
                   ("xargs", "xargs open"), ("xargs-options", "xargs -n 1 -I ITEM open ITEM")])
add("launchers", [("watch", "watch -n 2 open note.txt"),
                  ("script", "script -q transcript open note.txt"),
                  ("tmux", "tmux new-session 'open note.txt'"),
                  ("screen", "screen -dm open note.txt"),
                  ("parallel", "parallel open ::: note.txt"),
                  ("concurrently", "concurrently 'open note.txt' 'batch'")])
add("heredocs", [("heredoc", "bash <<'END'\nopen note.txt\nEND"),
                 ("heredoc-tabs", "sh <<-END\n\tbatch\nEND"),
                 ("herestring", "bash <<< 'open note.txt'")])
add("multiline", [("quoted-then-command", "printf '%s' 'first\nsecond'\nopen note.txt"),
                  ("double-then-command", 'printf "%s" "first\nsecond"; batch'),
                  ("quoted-carrier", 'bash -c "true\nopen note.txt"')])
add("substitutions", [("dollar", 'printf "%s" "$(open note.txt)"'),
                      ("backtick", 'printf "%s" "`batch`"'),
                      ("process-input", "cat <(open note.txt)"),
                      ("process-output", "printf x > >(batch)"),
                      ("arithmetic-substitution", "printf '%s' $((1 + $(open note.txt)))"),
                      ("arithmetic-lookalike", "printf '%s' $( (open note.txt) )")])
add("compound", [("group", "{ open note.txt; }"), ("subshell", "(batch)"),
                 ("if", "if true; then open note.txt; fi"),
                 ("case-branch", "case x in x) batch;; esac"),
                 ("while", "while false; do true; done; open note.txt"),
                 ("for", "for item in one; do open note.txt; done"),
                 ("function", "reach() { open note.txt; }; reach")])
add("separators", [("pipe-left", "open note.txt | cat"), ("pipe-right", "printf x | batch"),
                   ("and", "true && open note.txt"), ("or", "false || batch"),
                   ("background", "open note.txt & wait"), ("semicolon", "true; batch"),
                   ("newline", "true\nopen note.txt")])
add("indirection", [("variable", 'p=open; "$p" note.txt'),
                    ("array", 'p=(open note.txt); "${p[@]}"'),
                    ("alias", "shopt -s expand_aliases\nalias reach='open note.txt'\nreach"),
                    ("eval", "eval 'open note.txt'")])
add("lookalikes", [("cyrillic-o", "\u043epen note.txt"), ("zero-width", "op\u200ben note.txt"),
                   ("bidi", "op\u202een note.txt"), ("fullwidth", "\uff4fpen note.txt")])
add("limits", [("command-size", "open " + "x" * 8001),
               ("reader-commands", "true;" * 257 + "open note.txt"),
               ("reader-depth", "(" * 10 + "batch" + ")" * 10),
               ("substitution-count", "printf '%s' " + "$(true)" * 256 + "; open note.txt"),
               ("blank-run", "open" + " " * 65 + "note.txt"),
               ("blank-lines", "true" + "\n" * 17 + "batch")])

# Every allow-set verb and each networksetup query prefix has a plain control.
READ_ONLY = {
    "at": ("-l",),
    "launchctl": ("", "list", "print", "print-cache", "print-disabled", "blame", "error", "help", "version",
                  "getenv", "managerpid", "manageruid", "managername"),
    "shortcuts": ("", "list", "help", "-h", "--help"),
    "tccutil": ("", "-h", "--help", "--version"),
    "networksetup": ("", "-getinfo", "-listallnetworkservices", "-printcommands", "-showpppoestatus",
                     "-isairportpoweron", "-help", "-version"),
    "security": ("list-keychains",),
}
for program, verbs in READ_ONLY.items():
    for index, verb in enumerate(verbs):
        CASES.append(Case("readonly-table", f"{program}-{index}", f"{program} {verb}".strip(), True))

READ_ONLY_SHAPES = {
    "quoting": "'launch'ctl 'li'st", "case": "LAUNCHCTL list", "paths": "/bin/launchctl list",
    "wrappers": "env NOTE=example nice -n 1 launchctl list", "carriers": "bash -c 'launchctl list'",
    "find-xargs": "xargs launchctl list", "launchers": "watch -n 1 launchctl list",
    "heredocs": "bash <<'END'\nlaunchctl list\nEND", "multiline": "printf '%s' 'one\ntwo'\nlaunchctl list",
    "substitutions": 'printf "%s" "$(launchctl list)"', "compound": "{ launchctl list; }",
    "separators": "launchctl list; shortcuts list", "indirection": 'p=launchctl; "$p" list',
    "lookalikes": "launchctl list # \u043e \u200b \u202e", "limits": "launchctl" + " " * 65 + "list",
}
CASES.extend(Case(category, "readonly", text, True) for category, text in READ_ONLY_SHAPES.items())

# Fixed after measuring the unmodified head; never infer xfails from a runtime verdict.
GAPS = {
    ("wrappers", "pnpm"): "pnpm dlx does not expose its launched program to outside-reach",
    ("paths", "readonly"): "path-qualified read-only programs remain unreadable",
    ("wrappers", "readonly"): "stacked wrappers leave the read-only command unreadable",
    ("find-xargs", "readonly"): "xargs read-only invocation remains unreadable",
    ("launchers", "readonly"): "watch read-only invocation remains unreadable",
    ("heredocs", "readonly"): "shell here-document read-only body remains unreadable",
    ("indirection", "readonly"): "variable-held read-only program remains unreadable",
    ("lookalikes", "readonly"): "Unicode controls in an inert comment make the command unreadable",
    ("limits", "readonly"): "long blank runs make a read-only command unreadable",
}
CASES = tuple(Case(c.category, c.id, c.text, c.readonly, GAPS.get((c.category, c.id), "")) for c in CASES)
