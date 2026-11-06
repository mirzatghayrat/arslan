"""S2a-3 c: what the reader understands of a command's text. server/services/shell_grammar.py models a small part of
bash 3.2, and a command is understood only when all of it is in that part. The cases here are grammar features, written
with harmless commands; the real-shell comparison is S2a-3 d's test.
"""
from __future__ import annotations

import inspect
import sys
import time

import pytest

from server.services import shell_grammar


def _programs(command):
    reading = shell_grammar.read(command)
    assert reading.understood, reading.why
    return [c[0] for c in reading.commands]


def _refused(command):
    return not shell_grammar.read(command).understood


# ── what it understands ─────────────────────────────────────────────────────

@pytest.mark.parametrize("command,programs", [
    ("", []),
    ("# only a comment", []),
    ("ls -la", ["ls"]),
    ("git status && git log -1 || echo none", ["git", "git", "echo"]),
    ("cd src; make -j4 & wait", ["cd", "make", "wait"]),
    ("! grep -q x f", ["grep"]),
    ("grep -r 'a b' src | sort | uniq -c > out.txt 2>&1", ["grep", "sort", "uniq"]),
    ("ls &> all.log", ["ls"]),
    ("ls |\n  wc -l &&\n  echo ok ||\n  pwd", ["ls", "wc", "echo", "pwd"]),
    ('echo "$HOME/x ${USER} $1 $?" \'$not_expanded\'', ["echo"]),
    ('echo "a\\$b \\`c \\"d \\\\e \\f"', ["echo"]),
    ("echo $(git rev-parse HEAD)", ["git", "echo"]),
    ('echo "$(git rev-parse HEAD)"', ["git", "echo"]),
    ("echo $()", ["echo"]),
    ("echo $(git log --format='%h #1')", ["git", "echo"]),
    ("echo a#b c", ["echo"]),
    ("A=1 B='two words' make test", ["make"]),
    ("x=1", []),
    ("x=$(git rev-parse HEAD)", ["git"]),
    ("(cd build && cmake ..)", ["cd", "cmake"]),
    ("( (ls) )", ["ls"]),
    ("(ls) > out | wc", ["ls", "wc"]),
    ("{ ls; pwd; } > list.txt", ["ls", "pwd"]),
    ("{ { ls; } }", ["ls"]),
    ("if [ -d out ]; then rm -r out/tmp; elif [ -f x ]; then :; else mkdir out; fi", ["[", "rm", "[", ":", "mkdir"]),
    ("if a; then if b; then c; fi fi", ["a", "b", "c"]),
    ("if a; then b; fi > out", ["a", "b"]),
    ("for f in *.md docs/*.md; do wc -l \"$f\"; done", ["wc"]),
    ("for f in $(ls); do wc -l \"$f\"; done", ["ls", "wc"]),
    ("for f; do echo \"$f\"; done", ["echo"]),
    ("for f\ndo\necho \"$f\"\ndone", ["echo"]),
    ("for f in a b\ndo echo \"$f\"; done", ["echo"]),
    ("for f in; do echo \"$f\"; done", ["echo"]),
    ("for x in a do; do ls; done", ["ls"]),
    ("while read -r line; do echo \"$line\"; done < list.txt", ["read", "echo"]),
    ("until make; do sleep 1; done", ["make", "sleep"]),
    ("case \"$1\" in start|run) npm start;; *) echo usage;; esac", ["npm", "echo"]),
    ("case x in (a) ls;; b) ;; esac", ["ls"]),
    ("case x\nin\n a) ls\n ;;\n b) pwd\nesac", ["ls", "pwd"]),
    ("case x in a) ls;; esac > out", ["ls"]),
    ("cat > notes.md <<'EOF'\nquoted $body $(is) data `here`\nEOF", ["cat"]),
    ("cat <<EOF\nhello $USER from ${HOME} $1 \\\\ ok\nEOF", ["cat"]),
    ("cat <<-EOF\n\thello\n\tEOF\nls", ["cat", "ls"]),
    ("cat <<A <<'B'\na\nA\n$(b)\nB\nls", ["cat", "ls"]),
    ("cat <<A; ls\na\nA\npwd", ["cat", "ls", "pwd"]),
    ("tr a-z A-Z <<< \"$name\"", ["tr"]),
    ("tr a-z A-Z <<< $(git rev-parse HEAD)", ["git", "tr"]),
    ("ls \\\n  -la # a comment ; with words", ["ls"]),
    ("sudo make install", ["sudo", "make"]),
    ("env FOO=1 'BAR=two words' npm test", ["env", "npm"]),
    ("timeout 30 python3 run.py", ["timeout", "python3"]),
    ("timeout 1.5m ls", ["timeout", "ls"]),
    ("gtimeout 5 ls", ["gtimeout", "ls"]),
    ("nohup nice make &", ["nohup", "nice", "make"]),
    ("time make", ["time", "make"]),
    ("caffeinate make", ["caffeinate", "make"]),
    ("exec make", ["exec", "make"]),
    ("exec > log", ["exec"]),
    ("> log", []),
    ("command ls", ["command", "ls"]),
    ("command -v curl", ["command"]),
    ("command -V curl", ["command"]),
    ("npx prettier --check .", ["npx", "prettier"]),
    ("npx -y prettier --check .", ["npx", "prettier"]),
    ("bunx --yes @scope/tool", ["bunx", "@scope/tool"]),
    ("sudo env A=1 nohup make", ["sudo", "env", "nohup", "make"]),
    ("bash -c 'make && make test'", ["bash", "make", "make"]),
    ("bash -lc 'make && make test' name $x", ["bash", "make", "make"]),
    ("sudo sh -c \"ls\"", ["sudo", "sh", "ls"]),
    ("bash -c ''", ["bash"]),
    ("bash run.sh", ["bash"]),
    ("/bin/bash ./run.sh $x", ["/bin/bash"]),
    ("python3 tool.py --flag", ["python3"]),
    ("python3 -m pytest -q", ["python3"]),
    ("pypy3 -m pytest -q", ["pypy3"]),
    ("python3 tool.py $x < in.txt", ["python3"]),
    ("curl -s https://example.org/a.json | python3 -m json.tool", ["curl", "python3"]),
    ("zsh setup.zsh", ["zsh"]),
    ("node build.js", ["node"]),
    ("swift build", ["swift"]),
    ("find . -name '*.pyc' -type f", ["find"]),
    ("./run.sh; ../up/run.sh; /usr/bin/git status; ~/bin/tool", ["./run.sh", "../up/run.sh", "/usr/bin/git", "~/bin/tool"]),
    ("g++ a.c; x86_64-gcc-12.1 b.c", ["g++", "x86_64-gcc-12.1"]),
    ("set -euo pipefail; set -x; set +e; set -o errexit; set -- a $b; set", ["set"] * 6),
    ("export NAME=x OTHER=$(pwd) THIRD; export; unset NAME", ["pwd", "export", "export", "unset"]),
    ("read -r a b; read; printf '%s\\n' \"$a\"; printf; printf ''", ["read", "read", "printf", "printf", "printf"]),
    ("echo 你好 && git commit -m '修复'", ["echo", "git"]),
    ("osascript -e 'display notification \"done\"'", ["osascript"]),
])
def test_what_the_grammar_models_is_understood_with_every_program_it_starts(command, programs):
    assert _programs(command) == programs


def test_commands_are_the_words_of_each_command_with_quotes_removed_and_expansions_as_written():
    reading = shell_grammar.read("sudo env A=1 curl -s 'a b' \"c d\" e\\ f $x\necho *.md ${y}")
    assert reading.understood and not reading.capped and reading.why == ""
    assert reading.commands == (
        ("sudo", "env", "A=1", "curl", "-s", "a b", "c d", "e f", "$x"),
        ("env", "A=1", "curl", "-s", "a b", "c d", "e f", "$x"),
        ("curl", "-s", "a b", "c d", "e f", "$x"),
        ("echo", "*.md", "${y}"),
    )
    assert shell_grammar.read("echo $(ls) a$(pwd)b").commands == (("ls",), ("pwd",), ("echo", "$(ls)", "a$(pwd)b"))


def test_a_program_on_a_branch_a_condition_might_skip_is_still_listed():
    assert _programs("if false; then a; else b; fi; false && c; false || d; for x in; do e; done") == [
        "false", "a", "b", "false", "c", "false", "d", "e"]


def test_words_after_a_redirection_still_belong_to_the_command():
    assert shell_grammar.read("ls &> f pwd").commands == (("ls", "pwd"),)
    assert shell_grammar.read("ls > f pwd").commands == (("ls", "pwd"),)


# ── what it refuses, and why ────────────────────────────────────────────────

@pytest.mark.parametrize("command,why", [
    ("echo $'a'", "$'…'"),
    ('echo $"a"', "$'…'"),
    ("echo `date`", "backquotes"),
    ('echo "`date`"', "backquotes"),
    ("echo $((1 + 2))", "arithmetic"),
    ("echo $[1 + 2]", "arithmetic"),
    ("((n++))", "arithmetic"),
    ("echo {a,b}", "brace expansion"),
    ("echo a}", "brace expansion"),
    ("echo {}", "brace expansion"),
    ("{ls; }", "brace expansion"),
    ("echo ${name:-x}", "operator"),
    ("diff <(ls a) <(ls b)", "process substitution"),
    ("ls >(cat)", "process substitution"),
    ("greet() { echo hi; }", "function"),
    ("function greet { echo hi; }", "function"),
    ("select x in a; do ls; done", "select"),
    ("coproc ls", "coproc"),
    ("[[ -f x ]] && cat x", "[["),
    ("eval ls", "eval"),
    ("source env.sh", "source"),
    (". env.sh", "`.`"),
    ("alias l=ls", "alias"),
    ("trap 'echo bye' EXIT", "trap"),
    ("shopt -s extglob", "shopt"),
    ("builtin echo hi", "builtin"),
    ("$TOOL --version", "variable"),
    ("$(which python3) x.py", "variable"),
    ("/usr/bin/l? -la", "pattern"),
    ("x[1]=a", "pattern"),
    ("'' a", "program name"),
    ("echo 'open", "quoting"),
    ("echo \"open", "quoting"),
    ("echo \"open\\", "quoting"),
    ("echo end\\", "backslash"),
    ("if true; then ls", "does not close"),
    ("{ ls", "does not close"),
    ("(ls", "does not close"),
    ("echo $(ls", "does not close"),
    ("case x in a) ls;;", "does not close"),
    ("case x in a) ls", "does not close"),
    ("cat <<EOF\nno end", "here-document"),
    ("cat <<EOF", "here-document"),
    ("cat <<", "here-document"),
    ("cat <<$x\nb\n$x", "here-document"),
    ("echo a |& cat", "bash 4"),
    ("echo a &>> log", "bash 4"),
    ("case a in a) ls;& esac", "bash 4"),
    ("case a in a) ls;;& esac", "bash 4"),
    ("x=$(case a in a) ls;; esac)", "case inside"),
    ("ls\x07", "control"),
    ("ls\x7f", "control"),
    ("ls\r", "control"),
    ("ls\x85", "control"),
    ("ls\u200b -la", "control"),
    ("ls\ufeff -la", "control"),
    ("ls\u202e -la", "control"),
    ("ls\u00a0-la", "control"),
    ("ls\u3000-la", "control"),
    ("ls\u2028-la", "control"),
    ("ls\u2029-la", "control"),
    ("ls\ud800", "control"),
    ("ls\U000e0001", "control"),
])
def test_anything_outside_it_is_not_understood_and_says_why(command, why):
    reading = shell_grammar.read(command)
    assert not reading.understood
    assert why in reading.why
    assert not reading.capped
    assert reading.commands == ()


@pytest.mark.parametrize("command", [
    "; ls", "ls ; ; pwd", "ls & ; pwd", "| ls", "ls |", "ls &&", "&& ls", "! ", "ls ;; pwd", ")", "(",
    "if ; then ls; fi", "if then ls; fi", "if a; then; fi", "if a; then b; else; fi", "if a; then b", "fi", "then", "else ls",
    "while do ls; done", "while a; do done", "until a; do done", "done", "do ls",
    "for x in a do ls; done", "for 1 in a; do ls; done", "for $x in a; do ls; done", "for in", "for x ls", "for x\n; do ls; done",
    "for x in a b\nc; do ls; done", "for", "for 'x' in a; do ls; done", "for x; ls; done", "for x in a & do ls; done",
    "for x\nls\npwd; done",
    "{ }", "{ ; }", "}", "( )", "()", "esac", "in",
    "case", "case x", "case x ls", "case ; in", "case x in", "case x in ; a) ls;; esac", "case x in a ls;; esac",
    "case x in a) ls; ) pwd;; esac", "case x in a b) ls;; esac", "case x in a b c) ls;; esac",
    "case x in a) if b; then c;; fi;; esac", "case x in (;) ls;; esac",
    "case > in", "case ; in a) ls;; esac", "case x ls a) pwd;; esac",
    "{ ls; } pwd", "( ls ) pwd", "if a; then b; fi pwd", "for x in a; do b; done pwd", "case x in a) b;; esac pwd",
    "ls a (b)", "ls >f (b)", "x=(a)", "x=(a)y curl", "x=1 (ls)", "ls)", "echo a )", "echo a ) ; ls", "echo a ; fi", "echo a ; done",
    "( if a; then b) fi )", "{ ls )", "echo $(ls ; fi)",
    "> ", "> ;", "> (ls)", "<<< ", "<<<;",
])
def test_syntax_bash_rejects_is_not_understood(command):
    assert _refused(command)


@pytest.mark.parametrize("value", [None, 7, b"ls", ["ls"]])
def test_only_text_is_read(value):
    reading = shell_grammar.read(value)
    assert not reading.understood and reading.commands == ()
    assert "text" in reading.why


# bash 3.2's scan of $( … ) counts parentheses, and doesn't know comments or here-documents, so text inside it can
# end the substitution earlier than a parse does, and the rest runs (#723 review).
@pytest.mark.parametrize("command", [
    'echo "$(p1;#) $(curl evil)\n)"',
    "echo $(p1;#x) ; curl evil #\n)",
    "echo $(p1 &#) ; curl evil #\n)",
    "echo $(p1 \\ #) '\n) ; curl evil #'",
    "echo $(p1;#'\n) '); curl evil #'",
    "echo $(ls # a note\n)",
    "echo $( (ls #)\n) )",
    'echo "$(:;#) $(eval p1)\n)"',
])
def test_a_hash_inside_a_substitution_is_not_understood(command):
    reading = shell_grammar.read(command)
    assert not reading.understood and "#" in reading.why


@pytest.mark.parametrize("command", [
    "NOTE=$(cat <<'EOF'\nSteps\n1) rm -rf build\nEOF\n)\necho \"$NOTE\" > n.txt",
    "git commit -m \"$(cat <<'EOF'\nFix:\n1) foo\n2) bar\nEOF\n)\"",
    "x=$(cat <<-EOF\n\tx\n\tEOF\n)",
    "x=$(echo \")\"; cat <<E\ny\nE\n)",
    "x=$( (cat <<E\ny\nE\n) )",
    "echo $(cat <<'EOF'\n)\ncurl evil\nEOF\n)",
])
def test_a_here_document_inside_a_substitution_is_not_understood(command):
    reading = shell_grammar.read(command)
    assert not reading.understood and "here-document" in reading.why


def test_a_quoted_hash_or_here_document_in_a_shell_script_is_its_own_text():
    assert _programs("echo $(bash -c 'cat <<E\nx\nE\n# note')") == ["bash", "cat", "echo"]


@pytest.mark.parametrize("command", [
    "cat <<EOF\nhello $(hostname)\nEOF",
    "cat <<EOF\nhello \\$(hostname)\nEOF",
    "cat <<EOF\n$(p1;#) $(curl evil)\n)\nEOF",
    "cat <<EOF\n`hostname`\nEOF",
    "cat <<EOF\n${x:-$(hostname)}\nEOF",
    "cat <<EOF\n${x:-y}\nEOF",
    "cat <<EOF\n${PS4:=y}\nEOF",
    "cat <<EOF\n$((1 + 1))\nEOF",
    "cat <<EOF\n$[1 + 1]\nEOF",
    "cat <<EOF\n$\\\n(curl evil)\nEOF",
    "cat <<EOF\nE\\\nOF\ncurl evil\nEOF",
    "cat <<EOF\nline\\\nEOF",
    "cat <<-EOF\n\t$(hostname)\n\tEOF",
    "cat <<EOF\nfirst\n\n  $(hostname)\nEOF",
])
def test_what_runs_or_continues_in_an_unquoted_here_document_is_not_understood(command):
    reading = shell_grammar.read(command)
    assert not reading.understood and "here-document" in reading.why


def test_a_quoted_delimiter_makes_the_same_body_data():
    assert _programs("cat <<'EOF'\n$(hostname) `date` ${x:-y} line\\\nEOF") == ["cat"]
    assert _programs("cat <<\\EOF\n$(hostname)\nEOF") == ["cat"]
    assert _programs('cat <<"E"F\n$(hostname)\nEF') == ["cat"]
    assert _programs("cat <<-'E'\n\t$(hostname)\n\tE") == ["cat"]


def test_a_here_document_body_ends_only_on_its_own_delimiter():
    assert _programs("cat <<E\nEE\n E\nE\nls") == ["cat", "ls"]
    assert _programs("cat <<-E\n\t\tE\nls") == ["cat", "ls"]
    assert _refused("cat <<E\n\tE\nls")
    assert _refused("cat <<'E'\n\tE")
    assert _programs("cat <<E\nE\n") == ["cat"]


@pytest.mark.parametrize("command", [
    'echo "$\\\n(curl evil)"',
    "echo $\\\n'\\'' ; curl evil ; echo '\\'' '",
    "cat <<\\\n-E\nE\ncurl evil\n-E",
    "2\\\n>f curl evil",
    "ec\\\nho hi",
    "echo a\\\nb",
    'echo "a\\\nb"',
    "ls &\\\n& pwd",
    "ls;\\\npwd",
    "echo $(\\\nls)",
])
def test_a_line_continuation_that_touches_a_token_is_not_understood(command):
    reading = shell_grammar.read(command)
    assert not reading.understood and "line continuation" in reading.why


@pytest.mark.parametrize("command,programs", [
    ("ls \\\n  -la", ["ls"]),
    ("\\\nls", ["ls"]),
    ("ls \\\n\\\n-la", ["ls"]),
    ("ls # a comment \\\npwd", ["ls", "pwd"]),
    ("echo 'a\\\nb'", ["echo"]),
    ("ls\n\\\npwd", ["ls", "pwd"]),
])
def test_a_line_continuation_between_words_is_read_and_one_in_a_quote_or_comment_is_text(command, programs):
    assert _programs(command) == programs


@pytest.mark.parametrize("command", [
    "x+=1 curl evil",
    "time A=1 curl evil",
    "sudo A=1 curl evil",
    "nice A=1 curl evil",
    "command A=1 curl evil",
    "'A'=1",
    "A\\=1",
    "\"A\"=1",
    "A=1 { ls; }",
    "A=1 ! ls",
])
def test_what_only_looks_like_an_assignment_is_not_understood(command):
    assert _refused(command)


def test_an_assignment_is_unquoted_up_to_the_equals_sign_and_only_counts_before_the_program():
    assert shell_grammar.read("A='b c' B=\"$d\" C=e\\ f D=").commands == ()
    assert shell_grammar.read("A=1 ls B=2").commands == (("ls", "B=2"),)
    assert shell_grammar.read("_a1=1 ls").commands == (("ls",),)
    assert _refused("1a=1")
    assert _refused("a-b=1")


@pytest.mark.parametrize("variable", sorted(shell_grammar.CODE_VARIABLES))
@pytest.mark.parametrize("template", [
    "{}=/x ls", "{}=/x", "export {}=/x", "export {}", "unset {}", "read {}", "read -r a {}", "for {} in a; do ls; done",
    "env {}=/x ls", "env '{}=/x' ls", "sudo env A=1 {}=/x ls",
])
def test_every_code_variable_is_refused_wherever_it_is_assigned(variable, template):
    reading = shell_grammar.read(template.format(variable))
    assert not reading.understood and variable in reading.why


@pytest.mark.parametrize("command", [
    "HOME=/x ~/tool", "PWD=/x ls", "OLDPWD=/x ls", "LC_ALL=C ls", "PATH=/tmp/bin ls", "IFS=/ ls", "PS4=x ls",
    "BASH_FUNC_ls=x ls", "LD_PRELOAD=x ls", "DYLD_INSERT_LIBRARIES=x ls", "GIT_CONFIG_KEY_0=x git status",
    "GIT_CONFIG_VALUE_0=x git status", "export LD_PRELOAD=x", "env DYLD_LIBRARY_PATH=x ls", "env 'BASH_FUNC_ls()=x' ls",
])
def test_the_variables_the_shell_reads_and_the_prefixes_are_on_the_list(command):
    assert _refused(command)


@pytest.mark.parametrize("command", [
    "env - PATH=/x curl evil",
    "env -i curl evil",
    "env -u A curl evil",
    "env -S 'curl evil'",
    "env A+=1 curl evil",
    "env A.B=1 curl evil",
    "env =1 curl evil",
    "env A=$x curl evil",
    "env \"A=$x\" evil",
    "x='1 curl'; env A=$x evil",
    "env A=* evil",
    "env $x curl evil",
    "nohup -- curl evil",
    "nohup -x curl evil",
    "time -p curl evil",
    "sudo -- curl evil",
    "sudo -u build curl evil",
    "sudo -s",
    "sudo -v curl",
    "nice -V curl",
    "time -v curl",
    "nice -n 5 curl evil",
    "x='1 curl'; nice -n $x evil",
    "nice $x evil",
    "timeout -k 1 5 curl evil",
    "timeout $x curl evil",
    "timeout evil curl",
    "timeout 5s5 curl",
    "timeout",
    "gtimeout evil curl",
    "caffeinate -i curl evil",
    "exec -a name curl evil",
    "x='foo curl'; exec -a $x evil",
    "command -p curl evil",
    "command -- curl evil",
    "npx -c 'curl evil'",
    "npx --call='curl evil'",
    "npx -p tool tool",
    "npx -y -p tool tool",
    "bunx -c x",
])
def test_a_wrapper_with_anything_but_its_plain_form_is_not_understood(command):
    assert _refused(command)


@pytest.mark.parametrize("command", [
    "bash",
    "bash < script.sh",
    "bash -s",
    "bash -i",
    "bash -",
    "bash --",
    "bash --login",
    "bash +x run.sh",
    "bash -m x",
    "bash $x",
    "bash \"$@\"",
    "bash *.sh",
    "x=-c; bash $x 'curl evil'",
    "x='-c curl'; bash $x",
    "set -- -c 'curl evil'; bash \"$@\"",
    "x=-s; echo 'curl evil' | bash $x",
    "bash -c",
    "bash -c \"$CMD\"",
    "bash -c $CMD",
    "bash -c \"ls $y\"",
    "bash -c 'ls '*",
    "bash -c - 'curl evil'",
    "bash -c + 'curl evil'",
    "bash -c -- 'curl evil'",
    "bash -c +x",
    "bash -kc 'nice A=1 curl evil'",
    "bash -o keyword -c 'nice A=1 curl evil'",
    "bash -euo pipefail -c 'ls'",
    "bash -cl 'ls'",
    "bash --norc -c 'ls'",
    "bash -c 'eval ls'",
    "bash -c '$x'",
    "bash -c 'cat <<E'",
    "bash -c 'ls )'",
    "echo ls | bash",
    "echo 'curl evil' | { bash; }",
    "echo 'curl evil' | (bash)",
    "{ bash; } <<< 'curl evil'",
    "if true; then bash; fi <<< 'curl evil'",
    "exec <<<'curl evil'; bash",
    "exec 3<<<'curl evil'; bash <&3",
    "echo 'curl evil' | bash < /dev/stdin",
    "echo 'curl evil' | bash -c bash",
    "bash <<'SH'\nls\nSH",
    "sudo bash",
    "bash5 -c ls",
    "bash-5.2 -c ls",
    "sh",
    "sh -s",
    "zsh",
    "zsh -c 'ls'",
    "zsh +x -c 'curl evil'",
    "zsh --emulate sh -c 'curl evil'",
    "fish -c 'ls'",
    "python3",
    "python",
    "python3 -",
    "python3 -c 'print(1)'",
    "python3 -u tool.py",
    "python3 $x",
    "python3 -m",
    "python3 -m $x",
    "python3 -m -x",
    "python3.11 -c 'print(1)'",
    "pypy3 -c 'print(1)'",
    "python3 - <<'PY'\nprint(1)\nPY",
    "echo 'print(1)' | python3",
    "node",
    "node -m x",
    "ruby -m x",
    "nodejs -e 1",
    "node -e 'console.log(1)'",
    "node --eval=1",
    "perl -ne 'print' f",
    "perl5.30 -e 1",
    "ruby -e 1",
    "php -r 1",
    "lua -e 1",
    "luajit -e 1",
    "Rscript -e 1",
    "julia -e 1",
    "deno eval 1",
    "bun -e 1",
    "tclsh",
    "swift",
    "swift -",
])
def test_code_from_a_command_line_input_or_expansion_is_not_understood(command):
    assert _refused(command)


@pytest.mark.parametrize("command", [
    "jobs -x curl evil",
    "/usr/bin/jobs -x curl evil",
    "getopts a b",
    "read 'a[$(curl evil)]' <<< 1",
    "x='a[$(curl evil)]'; read \"$x\" <<< 1",
    "read $x",
    "read -p prompt x",
    "read -a x",
    "read -r -a x",
    "read PS4 <<< '$(curl evil)'; set -x; p1",
    "/usr/bin/read PS4",
    "printf -v PS4 '%s' '$(curl evil)'; set -x; p1",
    "printf -vPS4 x",
    "/usr/bin/printf -v PS4 x",
    "printf $x a",
    "printf \"$@\"",
    "printf -- a",
    "for PS4 in '$(curl evil)'; do set -x; p1; done",
    "export -f x",
    "export -n x",
    "export -r x",
    "export 'a[$(curl evil)]=1'",
    "export $x",
    "export $x=1",
    "export a$x=1",
    "export a*",
    "unset -f x",
    "unset -r x",
    "unset 'a[$(curl evil)]'",
    "unset $x",
    "set -k",
    "set -o keyword",
    "set -o",
    "set -eo",
    "set -",
    "set +",
    "set $x",
    "set -f",
    "set -e $x",
    "command export A=$x",
    "command read a",
    "command printf a",
    "command unset a",
    "command set -e",
    "time export A=$x",
])
def test_a_builtin_that_runs_or_assigns_is_not_understood(command):
    assert _refused(command)


# Everything `compgen -b` lists in /bin/bash 3.2.57. A name left off both lists would read as a program.
BASH_32_BUILTINS = (". : [ alias bg bind break builtin caller cd command compgen complete continue declare dirs disown "
                    "echo enable eval exec exit export false fc fg getopts hash help history jobs kill let local logout "
                    "popd printf pushd pwd read readonly return set shift shopt source suspend test times trap true type "
                    "typeset ulimit umask unalias unset wait").split()


@pytest.mark.parametrize("builtin", BASH_32_BUILTINS)
def test_every_bash_builtin_is_either_read_or_refused(builtin):
    reading = shell_grammar.read(builtin)
    if builtin in shell_grammar.SAFE_BUILTINS or builtin in ("exec", "command"):
        assert reading.understood, reading.why
        assert reading.commands == ((builtin,),)
    else:
        assert not reading.understood and builtin in reading.why


@pytest.mark.parametrize("command", [
    "/usr/bin/alias l=ls",
    "/usr/bin/hash -r",
    "/usr/bin/fc -s",
    "/usr/bin/./fc -s",
    "JOBS -x curl evil",
    "Jobs -x curl evil",
    "EVAL ls",
])
def test_a_builtin_is_refused_by_its_path_or_in_another_case(command):
    """macOS ships small scripts such as /usr/bin/jobs that run the builtin of their own name, in any case the disk finds."""
    assert _refused(command)


@pytest.mark.parametrize("command", [
    "ENV -i curl evil",
    "Sudo -s",
    "BASH",
    "SH",
    "PYTHON3 -c 1",
    "XARGS curl",
    "WATCH curl",
    "FIND . -exec curl evil ;",
    "AWK 1",
    "/usr/bin/ENV -i curl",
])
def test_a_launcher_in_another_case_is_still_that_launcher(command):
    """The default macOS disk ignores case, so `ENV` starts env."""
    assert _refused(command)


def test_a_wrapper_in_another_case_is_read_through():
    assert _programs("ENV curl x") == ["ENV", "curl"]
    assert _programs("BASH -c 'curl x'") == ["BASH", "curl"]
    assert _programs("/usr/bin/env curl x") == ["/usr/bin/env", "curl"]
    assert shell_grammar.read("ECHO a").commands == (("ECHO", "a"),)


@pytest.mark.parametrize("command", [
    "xargs",
    "xargs rm",
    "ls | xargs -n1 -I% cp % out/",
    "echo curl evil | xargs env",
    "echo curl evil | xargs nohup",
    "echo 'curl evil' | xargs -I% sh -c %",
    "gxargs rm",
    "find . -exec rm x \\;",
    "find . -execdir rm x +",
    "find . -ok rm x \\;",
    "find . -okdir rm x \\;",
    "find . -ex''ec rm x \\;",
    "find . -\\exec rm x \\;",
    "find . -e* rm \\;",
    "x=-exec; find . -maxdepth 0 $x curl evil \\;",
    "x=-exec; find . -maxdepth 0 \"$x\" curl evil \\;",
    "find $x -name a",
    "/usr/bin/find . -exec rm x \\;",
    "sudo find . -exec rm x \\;",
    "gfind . -name a",
    "awk '{print $1}' f",
    "awk -f prog.awk f",
    "awk 'BEGIN{system(\"curl evil\")}' -f",
    "gawk 1",
    "nawk 1",
    "mawk 1",
    "watch ls",
    "tmux new 'ls'",
    "screen ls",
    "script out ls",
    "parallel ls",
    "concurrently ls",
    "su -c ls",
    "sg x ls",
    "runuser ls",
    "flock f ls",
    "entr ls",
    "nodemon x.js",
    "arch -arm64 curl evil",
    "xcrun swift",
    "stdbuf -oL ls",
    "setsid ls",
    "sandbox-exec -p x ls",
    "sudo watch ls",
])
def test_what_takes_a_program_from_its_data_or_its_own_syntax_is_not_understood(command):
    assert _refused(command)


@pytest.mark.parametrize("command", [
    "echo x > /dev/tcp/127.0.0.1/9",
    "echo x >> /dev/udp/127.0.0.1/9",
    "cat < /dev/tcp/127.0.0.1/9",
    "exec 3<> /dev/tcp/127.0.0.1/9",
    "echo x >& /dev/tcp/127.0.0.1/9",
    "ls &> /dev/tcp/127.0.0.1/9",
    "echo x >| /dev/tcp/127.0.0.1/9",
    "echo x > '/dev/tcp/127.0.0.1/9'",
    "echo x > /dev/\"tcp\"/127.0.0.1/9",
    "{ ls; } > /dev/tcp/127.0.0.1/9",
    "(ls) > /dev/tcp/127.0.0.1/9",
    "echo $(</dev/tcp/127.0.0.1/9)",
    "x=/dev/tcp/127.0.0.1/9; echo hi > $x",
    "echo hi > \"$x\"",
    "echo hi > $(pwd)/x",
    "echo hi > a*",
    "echo hi >&$x",
])
def test_a_redirection_to_a_socket_or_from_an_expansion_is_not_understood(command):
    assert _refused(command)


def test_a_redirection_may_be_a_written_out_file_and_a_here_string_may_be_anything():
    assert _programs("ls > out.txt 2> ~/err >> log < in 3<> rw 2>&1 >&2 <&- >| f") == ["ls"]
    assert _programs("echo x > /dev/null; echo y > /dev/stderr") == ["echo", "echo"]
    assert _programs("cat <<< /dev/tcp/127.0.0.1/9") == ["cat"]


@pytest.mark.parametrize("command", [">&-curl evil", ">& -curl evil", "<&-curl evil", "<& -curl evil", "ls 2>&-curl", "ls >&-'x'"])
def test_text_after_the_dash_of_a_closed_descriptor_is_not_understood(command):
    """bash reads the - after <& or >& as a token of its own, so what follows it is a word, even a program."""
    reading = shell_grammar.read(command)
    assert not reading.understood and "after the -" in reading.why


def test_a_descriptor_closed_with_a_dash_alone_is_read():
    assert shell_grammar.read("ls >&- a").commands == (("ls", "a"),)
    assert shell_grammar.read("ls <& - a").commands == (("ls", "a"),)
    assert shell_grammar.read("ls 2>&-").commands == (("ls",),)


@pytest.mark.parametrize("command", [
    "-x", "+x", "%1", "=x", "!", "! ! ls", "~", "~+", "~-", "~root", "~+/x", "[[", "]", "a!b", "a$",
    "\\!", "'{'", "'}'", "'ls -la'", "'a;b'", "ls\\ -la", "a=b\\ c 'd e'",
])
def test_a_program_name_outside_plain_characters_is_not_understood(command):
    assert _refused(command)


def test_a_non_ascii_digit_is_not_a_file_descriptor():
    assert _refused("٣>x")                           # bash starts a program called ٣
    assert _refused("٣ >x")
    assert _programs("echo ٣>x") == ["echo"]
    assert shell_grammar.read("2>x ls").commands == (("ls",),)
    assert shell_grammar.read("12>x ls").commands == (("ls",),)
    assert shell_grammar.read("echo a2>x").commands == (("echo", "a2"),)
    assert shell_grammar.read("echo 2 >x").commands == (("echo", "2"),)
    assert shell_grammar.read("echo 2").commands == (("echo", "2"),)


def test_a_lone_bracket_is_the_test_builtin_and_any_other_bracket_is_a_pattern():
    assert _programs("[ -f x ] && ls") == ["[", "ls"]
    assert _refused("[a -f x ]")
    assert _refused("a[ x")
    assert _programs("ls [ab] a[") == ["ls"]


def test_a_program_is_read_only_when_it_is_written_out():
    for command in ("$x", "l*", "l?", "l[s]", "'l*'", "${x}", "$1", "$(ls)", "l$x", "a$(ls)"):
        assert _refused(command), command
    for command in ("l's'", "l\\s", '"ls"', "l''s"):
        assert shell_grammar.read(command).commands == (("ls",),), command


@pytest.mark.parametrize("command", ["'if' a", "\\if a", 'i"f" a', "'then'", "'fi'", "'done'", "'esac'", "'in'", ">f then"])
def test_a_quoted_or_late_reserved_word_is_a_program(command):
    reading = shell_grammar.read(command)
    assert reading.understood and len(reading.commands) == 1


def test_only_a_reserved_word_in_command_position_is_reserved():
    assert shell_grammar.read("echo if then fi done").commands == (("echo", "if", "then", "fi", "done"),)
    assert shell_grammar.read("echo {").commands == (("echo", "{"),)
    assert shell_grammar.read("echo }").commands == (("echo", "}"),)
    assert shell_grammar.read("if a; then echo fi; fi").commands == (("a",), ("echo", "fi"))


# ── the caps ────────────────────────────────────────────────────────────────

def test_commands_past_the_cap_are_not_understood():
    limit = shell_grammar.MAX_COMMANDS
    exact = shell_grammar.read("ls\n" * limit)
    assert exact.understood and len(exact.commands) == limit and not exact.capped
    many = shell_grammar.read("ls\n" * (limit + 1))
    assert not many.understood and many.capped and many.commands == ()


def test_a_wrapper_layer_counts_as_a_command():
    limit = shell_grammar.MAX_COMMANDS
    assert shell_grammar.read("sudo ls\n" * (limit // 2)).understood
    reading = shell_grammar.read("sudo ls\n" * (limit // 2) + "ls")
    assert not reading.understood and reading.capped


@pytest.mark.parametrize("opening,closing", [
    ("echo $(", ")"),
    ("( ", " )"),
    ("{ ", "; }"),
    ("if ", "; then ls; fi"),
    ("while ", "; do ls; done"),
    ("until ", "; do ls; done"),
    ("for x in a; do ", "; done"),
    ("case x in a) ", ";; esac"),
])
def test_nesting_past_the_cap_is_not_understood_whatever_it_is_made_of(opening, closing):
    def nested(levels):
        return opening * levels + "ls" + closing * levels
    assert shell_grammar.read(nested(shell_grammar.MAX_DEPTH)).understood
    reading = shell_grammar.read(nested(shell_grammar.MAX_DEPTH + 1))
    assert not reading.understood and reading.capped


def test_a_finished_compound_gives_its_level_back():
    assert shell_grammar.read("{ ls; }\n" * shell_grammar.MAX_COMMANDS).understood


def test_a_nested_shell_counts_as_a_level(monkeypatch):
    monkeypatch.setattr(shell_grammar, "MAX_DEPTH", 2)
    assert shell_grammar.read("bash -c 'bash -c ls'").understood
    reading = shell_grammar.read("bash -c 'bash -c \"bash -c ls\"'")
    assert not reading.understood and reading.capped


def test_wrappers_past_the_cap_are_not_understood():
    assert shell_grammar.read("env " * shell_grammar.MAX_DEPTH + "ls").understood
    reading = shell_grammar.read("env " * (shell_grammar.MAX_DEPTH + 1) + "ls")
    assert not reading.understood and reading.capped


def test_text_past_the_cap_is_not_understood():
    limit = shell_grammar.MAX_TEXT
    assert shell_grammar.read("x" * limit).understood
    reading = shell_grammar.read("x" * (limit + 1))
    assert not reading.understood and reading.capped


def test_running_out_of_stack_is_not_understood():
    """A turn's dispatch is already some frames deep when it reads a command, so even a nesting under the cap can run out."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack()) + 12)
    try:
        reading = shell_grammar.read("echo $(echo $(echo $(echo x)))")
    finally:
        sys.setrecursionlimit(limit)
    assert not reading.understood and reading.capped


# ── cost ────────────────────────────────────────────────────────────────────

# Each builds text of about `size` characters, to hit a place a slower reader would loop or read twice.
HOSTILE = {
    "lines of commands": lambda size: "ls -la src | grep x && echo ok\n" * (size // 30),
    "here-document substitutions": lambda size: "cat <<E\n" + "#$(\n" * (size // 4) + "\n)\nE",
    "nested here-documents": lambda size: "<<E1\n" + "#$(\n" * 8 + "<<E2\n" + "x\n" * (size // 2) + ")\nE2\n)\nE1",
    "plain here-document lines": lambda size: "cat <<E\n" + "$a\n" * (size // 3) + "E",
    "brackets in a word": lambda size: "x=" + "[" * size,
    "brackets in a substitution": lambda size: "cat <<E\n" + "#$(\n" * (size // 8) + "x=" + "[" * (size // 2) + "\n)\nE",
    "wrappers": lambda size: "env " * (size // 4) + "ls",
    "words under wrappers": lambda size: "env " * shell_grammar.MAX_DEPTH + "ls " + "a " * (size // 2),
    "words": lambda size: "ls " + "a " * (size // 2),
    "one long word": lambda size: "a" * size,
    "one long argument": lambda size: "ls " + "a" * size,
    "quoted pieces in a word": lambda size: "ls " + "''" * (size // 2),
    "expansions in a word": lambda size: "ls " + "$a" * (size // 2),
    "nested substitutions": lambda size: "echo " + "$(x " * (size // 3),
    "closed substitutions": lambda size: "ls " + "$(x)" * (size // 4),
    "opening parentheses": lambda size: "( " * (size // 2),
    "opening braces": lambda size: "{ " * (size // 2),
    "open ifs": lambda size: "if " * (size // 3),
    "a shell in a shell": lambda size: "bash -c 'bash -c \"bash -c " + "x" * size + "\"'",
    "pipes": lambda size: "a|" * (size // 2) + "a",
    "assignments": lambda size: "a=b " * (size // 4),
    "a for list": lambda size: "for x in " + "a " * (size // 2) + "; do ls; done",
    "line continuations": lambda size: "ls " + "\\\n " * (size // 3),
    "digits": lambda size: "1" * size + " x",
    "redirections": lambda size: ">a " * (size // 3) + "ls",
    "here-documents waiting": lambda size: "cat " + "<<E " * (size // 8) + "\n" + "E\n" * (size // 8),
    "a long quoted body": lambda size: "cat <<'E'\n" + "x\n" * (size // 2) + "E",
    "case arms": lambda size: "case x in " + "a) ;; " * (size // 6) + "esac",
    "semicolons": lambda size: "a;" * (size // 2),
    "settings": lambda size: "env " + "a=b " * (size // 4) + "ls",
    "exports": lambda size: "export " + "a=b " * (size // 4),
    "reads": lambda size: "read " + "a " * (size // 2),
    "set options": lambda size: "set " + "-e " * (size // 3),
    "find words": lambda size: "find . " + "-a " * (size // 3),
    "invisible characters at the end": lambda size: "a" * size + "\u200b",
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_a_read_grows_with_the_text_and_no_faster(name):
    def cost(size):
        text = HOSTILE[name](size)
        best = float("inf")
        for _ in range(5):
            start = time.thread_time()
            shell_grammar.read(text)
            best = min(best, time.thread_time() - start)
        return best
    size = shell_grammar.MAX_TEXT * 3 // 4
    small, large = cost(size // 4), cost(size)
    assert large < 10 * max(small, 2e-4)             # linear reads ~4×; quadratic would read ~16×


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_a_hostile_text_at_the_cap_reads_quickly_and_keeps_to_the_caps(name):
    text = HOSTILE[name](shell_grammar.MAX_TEXT)[:shell_grammar.MAX_TEXT]
    start = time.thread_time()
    reading = shell_grammar.read(text)
    assert time.thread_time() - start < 1.0
    assert len(reading.commands) <= shell_grammar.MAX_COMMANDS


def test_repeated_wrappers_do_not_multiply_what_is_kept():
    """Each layer lists the words after it, so layers are capped along with commands."""
    reading = shell_grammar.read("env " * 2000 + "ls")
    assert not reading.understood and reading.capped and reading.commands == ()
    wide = shell_grammar.read("env " * shell_grammar.MAX_DEPTH + "ls " + "a " * 3900)
    assert wide.understood
    assert sum(len(c) for c in wide.commands) < (shell_grammar.MAX_DEPTH + 1) * 3910
