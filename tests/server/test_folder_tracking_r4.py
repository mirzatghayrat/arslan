"""Effect and anchor witnesses: generated programs are assessed, never executed."""
from collections import Counter
from itertools import product
import errno
import json
import os
from types import SimpleNamespace

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.test_s2a3_folder_tracking import A, B, DEL, FIND, TOOL, stand_in_rules  # noqa: F401
from tests.server import test_folder_tracking_r3_matrix as revisions
from tests.server import test_folder_tracking_matrix as matrix

CLASSES = {
    "REMOVE-LINK": "rm -rf {p}; ln -s zz-outside {p}",
    "RENAME-LINK": "mv {p} zz-moved; ln -s zz-outside {p}",
    "FORCE-LINK-AFTER-REMOVE": "rm -rf {p}; ln -sfn zz-outside {p}",
    "MKDIR-REMOVE-LINK": "mkdir -p {p}; rm -rf {p}; ln -s zz-outside {p}",
    "PARENT-RENAME-LINK": "mv zz-a zz-moved; ln -s zz-outside zz-a",
    "COPY-LINK": "rm -rf {p}; cp -R zz-source {p}",
    "TAR-LINK": "rm -rf {p}; tar -xf zz-archive",
    "UNZIP-LINK": "rm -rf {p}; unzip zz-archive",
    "GIT-LINK": "git checkout -f zz-revision -- {p}",
    "RSYNC-LINK": "rsync -a zz-source/ {p}/",
    "FORCE-LINK-ONLY": "ln -sfn zz-outside {p}",
    "INSTALL-FILE": "install zz-source {p}",
    "TEE-FILE": "tee {p}",
    "REDIRECT-FILE": "echo x > {p}",
    "ORDINARY-PROGRAM": "zz-opaque {p}",
    "REMOTE-RSYNC": "rsync -a zz-host:zz-source {p}",
    "PRIVILEGED-LINK": "sudo ln -s zz-outside {p}",
}
FORMS = (
    "{effect}; {fold}", "{{ {effect}; }} && {fold}", "{{ {effect}; false; }} || {fold}",
    "{effect}\n{fold}", "({effect}); {fold}", "{{ {effect}; }}; {fold}",
    "echo $({effect}); {fold}", "bash -c '{effect}'; {fold}",
)


def fold(prefix=A, move="cd", up="..", end=None):
    return f"{move} {prefix}/{B} && cd {up} && {end or DEL + ' zz-file'}"


def mutation_cases(effect):
    for prefix, move, up, end, form in product(
        (A, A + "/zz-deep"), ("cd", "pushd"), ("..", "../."),
        (DEL + " zz-file", FIND + " zz-file -delete"), FORMS,
    ):
        yield form.format(effect=effect.format(p=prefix), fold=fold(prefix, move, up, end))


@pytest.mark.parametrize("kind", CLASSES)
def test_mutating_class(kind, tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    (tmp_path / A / "zz-deep" / B).mkdir(parents=True)
    texts = list(mutation_cases(CLASSES[kind]))
    assert len(texts) == 128
    for text in texts:
        assert sg.read(text).understood, text
        expected = "forbid" if kind == "PRIVILEGED-LINK" else "ask"
        assert tp.assess(text, cwd=tmp_path).level == expected, text
        assert tp.assess(text).level == expected, text


@pytest.mark.parametrize("effect", [
    "echo ok; zz-opaque", "echo ok | zz-opaque", "zz-opaque | echo ok",
    "(zz-opaque)", "echo $(zz-opaque)", "bash -c 'zz-opaque'", "zz-opaque & echo ok",
    "echo ok > zz-file", "ls --output=zz-file", "zz-unlisted", "make",
])
def test_effect_veto(effect, tmp_path, monkeypatch):
    (tmp_path / A / B).mkdir(parents=True)
    def unexpected(*args, **kwargs):
        pytest.fail("a vetoed fold must perform no filesystem access")
    monkeypatch.setattr(tp, "_valid_fold_anchor", unexpected)
    monkeypatch.setattr(tp, "_safe_fold_prefix", unexpected)
    text = effect + "; " + fold()
    assert tp.assess(text, cwd=tmp_path).level == "ask"


@pytest.mark.parametrize("program", [
    "echo ok", "printf ok", "pwd", "true", "false", ":", "test -e zz-file", "[ -e zz-file ]",
    "ls", "ls -l", "cat zz-file", "grep -n zz-pattern zz-file", "head zz-file", "tail zz-file", "wc -l zz-file",
    "git status", "git log --oneline", "git diff --stat", "cat <<<'zz-data'",
    "cat <<'END'\nzz-data\nEND\n",
])
def test_allowlisted_chain(program, tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    text = program + "\n" + fold()
    assert tp.assess(text, cwd=tmp_path).level == "run", text


@pytest.mark.parametrize("program", [
    "ls --unknown", "cat --output=zz-file", "grep --output=zz-file zz-pattern", "head --output=zz-file",
    "tail --output=zz-file", "wc --output=zz-file", "git status --output=zz-file", "git log --output=zz-file",
    "git diff --output=zz-file", "git -c zz-option=zz-value status", "git checkout zz-revision",
    "ls $ZZ_OPTIONS", "env ls", "nohup ls", "time ls", "bash -c 'ls'", "ZZ_OPTION=x ls", "/zz-bin/echo ok",
])
def test_unknown_options_and_wrappers(program, tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    assert tp.assess(program + "; " + fold(), cwd=tmp_path).level == "ask"


@pytest.mark.parametrize("template", [
    "{{ {fold}; }} | zz-opaque", "echo ok | {{ {fold}; }} | zz-opaque",
    "({fold}) > zz-output", "{{ {fold}; }} > zz-output",
    "ZZ_VALUE=$({fold}) | zz-opaque", "{{ {fold}; }} & zz-opaque",
    "echo $(echo x > zz-file); {fold}", "bash -c 'echo x > zz-file'; {fold}",
])
def test_concurrent_and_enclosing_effects(template, tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    assert tp.assess(template.format(fold=fold()), cwd=tmp_path).level == "ask"


def test_effect_after_fold_does_not_veto_it(tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    for suffix in ("; zz-opaque", "; echo x > zz-file", " && " + DEL + " zz-other"):
        assert tp.assess(fold() + suffix, cwd=tmp_path).level == "run"
    assert tp.assess(f"cd {A}/{B} && cd .. && zz-opaque && {DEL} zz-file", cwd=tmp_path).level == "run"


def test_each_fold_has_its_own_effect_history(tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    text = fold() + f" && cd {B} && cd .. && {DEL} zz-file"
    assert tp.assess(text, cwd=tmp_path).level == "ask"


def test_complete_return_uses_effect_veto(tmp_path):
    for preceding, expected in (("make", "ask"), ("ls", "run")):
        assert tp.assess(f"cd {A} && {preceding} && cd .. && {DEL} zz-file", cwd=tmp_path).level == expected


@pytest.mark.parametrize("move, up, end", tuple(product(("cd", "pushd"), ("..", "../."), (DEL, FIND))))
def test_simulated_rename_then_reassess(move, up, end, tmp_path):
    (tmp_path / A / B).mkdir(parents=True)
    text = fold(move=move, up=up, end=end + " zz-file" + (" -delete" if end == FIND else ""))
    assert tp.assess(text, cwd=tmp_path).level == "run"
    (tmp_path / A).rename(tmp_path / "zz-old")
    (tmp_path / A).symlink_to(tmp_path / "zz-old", target_is_directory=True)
    assert tp.assess(text, cwd=tmp_path).level == "ask"


INVALID = ("relative", "trailing", "dot", "empty", "parent", "anchor-link", "ancestor-link", "nul",
           "file", "missing", "too-long", "oserror", "non-str", "bytes", "alternate-case")


@pytest.mark.parametrize("kind", INVALID)
def test_invalid_anchor(kind, tmp_path, monkeypatch):
    work = tmp_path / "zz-work"
    (work / A / B).mkdir(parents=True)
    anchor = str(work)
    if kind == "relative":
        monkeypatch.chdir(tmp_path)
        anchor = "zz-work"
    elif kind == "trailing":
        anchor += "/"
    elif kind == "dot":
        anchor += "/."
    elif kind == "empty":
        anchor = str(tmp_path) + "//zz-work"
    elif kind == "parent":
        anchor += "/../zz-work"
    elif kind == "anchor-link":
        (tmp_path / "zz-link").symlink_to(work, target_is_directory=True)
        anchor = str(tmp_path / "zz-link")
    elif kind == "ancestor-link":
        (tmp_path / "zz-link").symlink_to(tmp_path, target_is_directory=True)
        anchor = str(tmp_path / "zz-link" / "zz-work")
    elif kind == "nul":
        anchor += "\0"
    elif kind == "file":
        (tmp_path / "zz-file").write_text("stand-in")
        anchor = str(tmp_path / "zz-file")
    elif kind == "missing":
        anchor = str(tmp_path / "zz-missing")
    elif kind == "too-long":
        anchor = str(tmp_path / ("z" * 300))
    elif kind == "oserror":
        def fail(*args, **kwargs):
            raise OSError(errno.EACCES, "stand-in")
        monkeypatch.setattr(tp, "os", SimpleNamespace(fspath=os.fspath, path=SimpleNamespace(realpath=fail)))
    elif kind == "non-str":
        anchor = 42
    elif kind == "bytes":
        anchor = bytes(anchor, "utf8")
    elif kind == "alternate-case":
        anchor = str(tmp_path / "ZZ-WORK")
    def no_prefix(prefix, cwd, checked):
        assert cwd is None, "an invalid anchor reached the prefix walk"
        return False
    monkeypatch.setattr(tp, "_safe_fold_prefix", no_prefix)
    text = fold()
    assert tp.assess(text, cwd=anchor).level == "ask"
    assert tp.ask_rules(text, cwd=anchor) == {"delete-outside"}
    assert tp._layer_two(text, tp._detection_texts(text), anchor) == [tp._DELETE_OUTSIDE]


def test_valid_anchor_checked_once(tmp_path, monkeypatch):
    (tmp_path / A / B).mkdir(parents=True)
    original = tp._valid_fold_anchor
    calls = []
    def record(cwd):
        calls.append(cwd)
        return original(cwd)
    monkeypatch.setattr(tp, "_valid_fold_anchor", record)
    text = f"cd {A}/{B} && cd .. && cd {B} && cd .. && {DEL} zz-file"
    assert tp.assess(text, cwd=tmp_path).level == "run"
    assert calls == [tmp_path]


def test_anchor_validated_before_prefix(tmp_path, monkeypatch):
    (tmp_path / A / B).mkdir(parents=True)
    events = []
    validate, prefix = tp._valid_fold_anchor, tp._safe_fold_prefix
    def record_anchor(cwd):
        events.append("anchor")
        return validate(cwd)
    def record_prefix(*args):
        events.append("prefix")
        return prefix(*args)
    monkeypatch.setattr(tp, "_valid_fold_anchor", record_anchor)
    monkeypatch.setattr(tp, "_safe_fold_prefix", record_prefix)
    assert tp.assess(fold(), cwd=tmp_path).level == "run"
    assert events == ["anchor", "prefix"]


COMMON = ("echo ok", "printf ok", "pwd", "true", "false", ":", "ls", "git status", "cat zz-file",
          "mkdir zz-unrelated", "touch zz-unrelated", "cp zz-source zz-unrelated")


def common_cases():
    for preceding, prefix, move, up, join, end in product(
        COMMON, (A, A + "/zz-deep"), ("cd", "pushd"), ("..", "../."), ("; ", " && ", "\n"),
        (DEL + " zz-file", FIND + " zz-file -delete"),
    ):
        yield preceding, preceding + join + fold(prefix, move, up, end)


def test_common_overask(tmp_path, monkeypatch):
    (tmp_path / A / B).mkdir(parents=True)
    (tmp_path / A / "zz-deep" / B).mkdir(parents=True)
    baseline = revisions.load_revision(revisions.ROUND_THREE, monkeypatch)
    report = Counter()
    for preceding, text in common_cases():
        assert baseline.assess(text, cwd=tmp_path).level == "run"
        after = tp.assess(text, cwd=tmp_path).level
        expected = "ask" if preceding in COMMON[-3:] else "run"
        assert after == expected, text
        report[after] += 1
    assert report == {"run": 432, "ask": 144}
    print("R4_COMMON " + json.dumps(report))
    with monkeypatch.context() as prototype:
        prototype.setattr(tp, "_fold_effect_safe", lambda words: bool(words and words[0] in tp._FOLD_BUILTINS))
        prototype_counts = Counter(tp.assess(text, cwd=tmp_path).level for _, text in common_cases())
    assert prototype_counts == {"run": 288, "ask": 288}
    print("R4_PROTOTYPE_COMMON " + json.dumps(prototype_counts))


def test_round_four_matrices(tmp_path, monkeypatch):
    corpora = {"repository": revisions.repository_corpus(), "structural": revisions.structural_corpus()}
    assert len(corpora["repository"]) == 1340
    assert len(corpora["structural"]) == 11816
    matrix.make_plain_tree(set.union(*corpora.values()), tmp_path)
    report = {}
    for revision in (revisions.MAINS[0], revisions.ROUND_THREE):
        baseline = revisions.load_revision(revision, monkeypatch)
        report[revision] = {}
        for name, texts in corpora.items():
            counts = Counter()
            for text in texts:
                before = baseline.assess(text, **({"cwd": tmp_path} if revision == revisions.ROUND_THREE else {}))
                after = tp.assess(text, cwd=tmp_path)
                counts[before.level + "->" + after.level] += 1
                assert before.level == after.level or (before.level, after.level) == ("run", "ask"), text
            report[revision][name] = dict(counts)
    invalid = Counter()
    for text in corpora["repository"]:
        valid = tp.assess(text, cwd=tmp_path)
        bad = tp.assess(text, cwd=str(tmp_path) + "/.")
        assert bad == tp.assess(text), text
        invalid[valid.level + "->" + bad.level] += 1
    assert invalid["run->ask"] == 66
    report["invalid_anchor"] = dict(invalid)
    print("R4_MATRIX " + json.dumps(report, sort_keys=True))


def test_vetoed_returns_cannot_overflow_toward_run():
    text = "zz-opaque; " + (f"cd {A} && cd .. && " * 8) + DEL + " zz-file"
    assert sg.read(text).understood
    assert tp.assess(text).level == "ask"


def test_plain_moves_have_the_existing_effect_gap(tmp_path, monkeypatch):
    (tmp_path / A / B).mkdir(parents=True)
    mains = [revisions.load_revision(rev, monkeypatch) for rev in (revisions.MAINS[0], revisions.ROUND_THREE)]
    counts = Counter()
    for kind, effect in list(CLASSES.items())[:15]:
        for form in FORMS:
            text = form.format(effect=effect.format(p=A), fold=f"cd {A} && {DEL} zz-file")
            assert mains[0].assess(text).level == "run", text
            assert mains[1].assess(text, cwd=tmp_path).level == "run", text
            assert tp.assess(text, cwd=tmp_path).level == "run", text
            counts[kind] += 1
    assert set(counts.values()) == {8}
    print("R4_PLAIN_GAP " + json.dumps(counts, sort_keys=True))


def test_round_three_topologies(tmp_path, monkeypatch):
    baseline = revisions.load_revision(revisions.ROUND_THREE, monkeypatch)
    report = {}
    for topology in ("plain", "outside-link", "inside-link", "deep-link", "missing"):
        work, outside = tmp_path / topology, tmp_path / (topology + "-outside")
        work.mkdir()
        (outside / B).mkdir(parents=True)
        prefix = A
        if topology == "plain":
            (work / A / B).mkdir(parents=True)
        elif topology == "outside-link":
            (work / A).symlink_to(outside, target_is_directory=True)
        elif topology == "inside-link":
            (work / "zz-real" / B).mkdir(parents=True)
            (work / A).symlink_to(work / "zz-real", target_is_directory=True)
        elif topology == "deep-link":
            (work / A).mkdir()
            (work / A / "zz-link").symlink_to(outside, target_is_directory=True)
            prefix += "/zz-link"
        counts = Counter()
        for move, parent, up, end in product(("cd", "pushd"), ("cd", "pushd"), ("..", "../.", "../"),
                                             (DEL + " zz-file", FIND + " zz-file -delete")):
            text = f"{move} {prefix}/{B} && {parent} {up} && {end}"
            before, after = baseline.assess(text, cwd=work), tp.assess(text, cwd=work)
            assert (before.level, before.rule) == (after.level, after.rule)
            counts[before.level + "->" + after.level] += 1
        assert counts == {"run->run" if topology == "plain" else "ask->ask": 24}
        report[topology] = dict(counts)
    print("R4_TOPOLOGY " + json.dumps(report, sort_keys=True))
