"""The stub program directory: every program records that it was started, wrappers start what they
were given. Only bash and sh are real."""
from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

#: Record separator and field separator in the trace file (one record per started program).
RECORD, FIELD = "\x1e", "\x1f"

HOST_PROGRAM_DIRS = ("/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin", "/bin", "/sbin")

# Programs the reader reads through to the command they start (shell_grammar._through_wrapper), the
# launchers whose quoted argument is a command line, and find. Each gets the wrapper script.
WRAPPERS = frozenset({"env", "sudo", "doas", "nohup", "setsid", "nice", "ionice", "timeout", "gtimeout",
                      "caffeinate", "stdbuf", "time", "xargs", "find", "npx", "bunx", "watch", "script",
                      "tmux"})

# Programs named by the policy's rules and the card, so a corpus that never spells one still has it.
KNOWN_PROGRAMS = frozenset({
    "osascript", "shortcuts", "launchctl", "crontab", "tccutil", "networksetup", "killall", "security",
    "open", "at", "batch", "pbcopy", "pbpaste", "say", "defaults", "diskutil", "hdiutil", "mdfind",
    "brew", "xcrun", "afplay", "screencapture", "swift", "pmset", "scutil", "sw_vers", "zsh", "python3",
    "node", "perl", "ruby", "curl", "wget", "git", "gh", "rsync", "ssh", "scp", "rm", "cp", "mv", "ls",
    "cat", "grep", "sed", "awk", "make", "npm", "pip", "pip3", "docker", "kubectl", "terraform", "aws",
})

_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+@%:,-]{0,200}")

_RECORD_SH = r"""#!/bin/bash
# A stub: records that it was started, with its arguments, and does nothing else.
printf -v rec '%s\037' "$0" "$@"
printf '%s\036' "$rec" >> "$ARSLAN_TRACE"
exit "${ARSLAN_STUB_EXIT:-0}"
"""

# The wrappers start the command they were given, the way the real program reads its arguments:
# options first, then the command. Nothing here runs code from a file or the network; the command it
# starts is itself a stub (or bash, the real one).
_WRAP_SH = r"""#!/bin/bash
printf -v rec '%s\037' "$0" "$@"
printf '%s\036' "$rec" >> "$ARSLAN_TRACE"
name=${0##*/}
fail=${ARSLAN_STUB_EXIT:-0}

# skip_options WITH_ARG FLAGS -- "$@": drops leading options; WITH_ARG lists the ones that take a
# separate operand, FLAGS the one-letter ones that may be bundled. Leaves the rest in REST.
skip_options() {
  local with_arg=" $1 " flags=$2; shift 2
  while (($#)); do
    case $1 in
      --) shift; break ;;
      -) break ;;
      --*=*) shift ;;
      --*) if [[ $with_arg == *" $1 "* ]]; then shift 2; else shift; fi ;;
      -?) if [[ $with_arg == *" $1 "* ]]; then shift 2; else shift; fi ;;
      -*) shift ;;             # bundled flags, or an operand written onto its option (-n1, -I{})
      *) break ;;
    esac
  done
  REST=("$@")
}

start() { (($#)) || exit "$fail"; exec "$@"; }

case $name in
  env)
    while (($#)); do
      case $1 in
        --) shift; break ;;
        -i|--ignore-environment|-0|--null) shift ;;
        -u|--unset|-C|--chdir) shift 2 ;;
        --unset=*|--chdir=*) shift ;;
        -S*|--split-string*|-P*) exit 125 ;;     # splits a string into a command: not modelled here
        -*) shift ;;
        *=*) export "$1" 2>/dev/null; shift ;;
        *) break ;;
      esac
    done
    start "$@" ;;
  sudo|doas)
    while (($#)); do
      case $1 in
        --) shift; break ;;
        -s|--shell|-i|--login) shift; (($#)) && exec /bin/bash -c "$*"; exit "$fail" ;;
        -e|--edit) exit "$fail" ;;
        -u|-g|-h|-p|-C|-U|-r|-t|-T|--user|--group|--host|--prompt|--close-from|--other-user|--role|--type) shift 2 ;;
        -*) shift ;;
        *) break ;;
      esac
    done
    start "$@" ;;
  nohup|setsid) skip_options "" "" "$@"; start "${REST[@]}" ;;
  nice) skip_options "-n --adjustment" "" "$@"; start "${REST[@]}" ;;
  ionice) skip_options "-c -n -p -P -u --class --classdata --pid --pgid --uid" "" "$@"; start "${REST[@]}" ;;
  timeout|gtimeout)
    skip_options "-k --kill-after -s --signal" "" "$@"
    set -- "${REST[@]}"; (($#)) && shift          # the duration
    start "$@" ;;
  caffeinate) skip_options "-t -w" "dimsu" "$@"; start "${REST[@]}" ;;
  stdbuf) skip_options "-i -o -e --input --output --error" "" "$@"; start "${REST[@]}" ;;
  time) skip_options "-f -o --format --output" "" "$@"; start "${REST[@]}" ;;
  npx|bunx)
    while (($#)); do
      case $1 in
        -c|--call) exec /bin/sh -c "$2" ;;
        --call=*) exec /bin/sh -c "${1#--call=}" ;;
        -p|--package) shift 2 ;;
        --) shift; break ;;
        -*) shift ;;
        *) break ;;
      esac
    done
    start "$@" ;;
  xargs)
    replace=""
    while (($#)); do
      case $1 in
        -I|-J|--replace) replace=$2; shift 2 ;;
        -I?*|-J?*) replace=${1:2}; shift ;;
        -L|-n|-P|-s|-E|-d|-a|-R|-S|--max-args|--max-procs|--delimiter|--arg-file|--max-lines|--max-chars|--eof) shift 2 ;;
        --) shift; break ;;
        -*) shift ;;
        *) break ;;
      esac
    done
    (($#)) || exit "$fail"                        # no command: the real xargs runs echo
    items=()                                      # its input, one item per line (read with bash alone)
    while IFS= read -r item || [[ -n $item ]]; do [[ -n $item ]] && items+=("$item"); done
    # With no input the real xargs may start nothing; this one starts the command once anyway, so the
    # comparison sees the program the text names (more than the shell would start, never less).
    if [[ -n $replace && ${#items[@]} -gt 0 ]]; then
      for item in "${items[@]}"; do "${@//"$replace"/$item}"; done; exit $? ;
    fi
    exec "$@" "${items[@]}" ;;
  find)
    start_path="."
    args=("$@"); k=0
    while ((k < ${#args[@]})) && [[ ${args[k]} == -[HLPEXdsx] ]]; do ((k++)); done
    if ((k < ${#args[@]})) && [[ ${args[k]} != -* && ${args[k]} != [\(\!\)] ]]; then start_path=${args[k]}; fi
    ran=0
    for ((k = 0; k < ${#args[@]}; k++)); do
      case ${args[k]} in
        -exec|-execdir|-ok|-okdir)
          cmd=(); for ((j = k + 1; j < ${#args[@]}; j++)); do
            [[ ${args[j]} == ";" || ${args[j]} == "+" ]] && break
            cmd+=("${args[j]//\{\}/${start_path%/}/found}")
          done
          ((${#cmd[@]})) && { "${cmd[@]}"; ran=1; }
          k=$j ;;
      esac
    done
    exit "$fail" ;;
  watch)
    skip_options "-n -d --interval --differences -c --color -p --precise -t --no-title -x --exec -b --beep -e --errexit -g --chgexit -w --no-wrap" "" "$@"
    ((${#REST[@]})) && exec /bin/sh -c "${REST[*]}"; exit "$fail" ;;
  script)
    while (($#)); do
      case $1 in
        -c|--command) exec /bin/sh -c "$2" ;;
        -*) shift ;;
        *) shift ;;
      esac
    done
    exit "$fail" ;;
  tmux)
    while (($#)); do
      case $1 in
        new|new-session|new-window|split-window|respawn-pane|send-keys)
          shift; while (($#)) && [[ $1 == -* ]]; do shift; done
          (($#)) && exec /bin/sh -c "$*"; exit "$fail" ;;
        *) shift ;;
      esac
    done
    exit "$fail" ;;
  *) exit "$fail" ;;
esac
"""


def words_of(text: str) -> set[str]:
    """Every word of a command that could be a program name (what the shell would look up on PATH)."""
    return {w for w in _NAME.findall(text) if not w.startswith((".", "-")) and w not in (".", "..")}


def host_program_names() -> set[str]:
    names: set[str] = set()
    for folder in HOST_PROGRAM_DIRS:
        try:
            names.update(os.listdir(folder))
        except OSError:
            continue
    return names


def build(folder: Path, corpus: list[str]) -> Path:
    """Fill `folder` with the stub directory for `corpus` and return it. Idempotent for a folder."""
    folder.mkdir(parents=True, exist_ok=True)
    record, wrap = folder / ".record", folder / ".wrap"
    record.write_text(_RECORD_SH)
    wrap.write_text(_WRAP_SH)
    for script in (record, wrap):
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    bash = shutil.which("bash") or "/bin/bash"
    for real in ("bash", "sh"):
        shutil.copy2(os.path.realpath(bash), folder / real)
    names = host_program_names() | KNOWN_PROGRAMS | WRAPPERS
    for command in corpus:
        names |= words_of(command)
    names -= {"bash", "sh", ".record", ".wrap"}
    for name in names:
        if "/" in name or not _NAME.fullmatch(name) or len(name.encode()) > 255:
            continue
        target = folder / name
        if target.is_symlink() or target.exists():
            continue
        target.symlink_to(".wrap" if name in WRAPPERS else ".record")
    return folder
