"""Git can invoke configured helpers; all command text stays reader/policy data."""
from collections import Counter
from itertools import product
import json

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server import test_folder_tracking_r3_matrix as revisions
from tests.server.test_folder_tracking_r4 import fold
from tests.server.test_s2a3_folder_tracking import A, B, DEL, FIND, stand_in_rules  # noqa: F401


def git_cases(program):
    for prefix, move, up, join, end in product(
        (A, A + "/zz-deep"), ("cd", "pushd"), ("..", "../."), ("; ", " && ", "\n"),
        (DEL + " zz-file", FIND + " zz-file -delete"),
    ):
        yield program + join + fold(prefix, move, up, end)


def plain_tree(work):
    (work / A / B).mkdir(parents=True)
    (work / A / "zz-deep" / B).mkdir(parents=True)


@pytest.mark.parametrize("kind", ["git-status-config", "git-diff-config"])
def test_effect_or_unreadable_never_authorizes_fold(kind, tmp_path, monkeypatch):
    plain_tree(tmp_path)
    # Inert fixtures: neither Git nor a helper is started. Configuration is not
    # an input to the policy and therefore cannot establish absence of effects.
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text(
        '[core]\n\tfsmonitor = zz-monitor-helper\n'
        '[diff "zz-driver"]\n\tcommand = zz-diff-helper\n\ttextconv = zz-text-helper\n'
    )
    (tmp_path / ".gitattributes").write_text('* diff=zz-driver\n')
    program = "git status" if kind == "git-status-config" else "git diff"
    texts = list(git_cases(program))
    assert len(texts) == 48
    baseline = revisions.load_revision(revisions.ROUND_FOUR, monkeypatch)
    counts = Counter()
    for text in texts:
        assert sg.read(text, fold_partial=False).understood, text
        for supplied, cwd in ((True, tmp_path), (False, None)):
            before, after = baseline.assess(text, cwd=cwd), tp.assess(text, cwd=cwd)
            assert before.level == ("run" if supplied else "ask"), text
            assert after.level == ("ask" if supplied else "run"), text
            assert after.rule == (tp._DELETE_OUTSIDE[0] if supplied else ""), text
            counts[f"{'supplied' if supplied else 'unknown'}:{before.level}->{after.level}"] += 1
    assert counts == {"supplied:run->ask": 48, "unknown:ask->run": 48}
    print("R5_GIT_CONFIG " + json.dumps({kind: counts}, sort_keys=True))


GIT_TAILS = (
    "", "status", "log", "diff", "checkout zz-revision", "zz-unknown",
    "-c core.fsmonitor=zz-helper status", "--no-pager log", "--paginate diff",
    "-C zz-repository status", "--git-dir=zz-repository status", "--work-tree=zz-work diff",
    "status --unknown", "log --output=zz-file", "diff --output=zz-file",
    "status -- zz-file", "log zz-revision", "diff -- zz-file",
    *("status " + option for option in
      ("--short", "--porcelain", "--branch", "-s", "-b", "--untracked-files=no")),
    *("log " + option for option in
      ("--oneline", "--stat", "--name-only", "--no-patch", "--no-ext-diff", "--no-textconv")),
    *("diff " + option for option in
      ("--stat", "--name-only", "--name-status", "--cached", "--staged", "--no-ext-diff", "--no-textconv")),
)


@pytest.mark.parametrize("name", ["git", "'git'", '"git"', r"g\it", "/usr/bin/git", "./git", "Git", "GIT"])
def test_git_spelling_never_authorizes_fold(name, tmp_path, monkeypatch):
    plain_tree(tmp_path)
    def no_anchor(*args):
        pytest.fail("Git before the fold must veto before filesystem checks")
    monkeypatch.setattr(tp, "_valid_fold_anchor", no_anchor)
    for tail in GIT_TAILS:
        for text in git_cases((name + " " + tail).rstrip()):
            reading = sg.read(text, fold_partial=False)
            assert reading.understood == ("/" not in name), text
            if not reading.understood:
                assert reading.why == "its program word contains a path"
            assert tp.assess(text, cwd=tmp_path).level == "ask", text
            assert tp.assess(text).level == ("ask" if "/" in name else "run"), text
        # A complete return must also retain its unfolded cautious decision.
        text = f"cd {A} && {name} {tail}; cd .. && {DEL} zz-file"
        reading = sg.read(text, fold_partial=False)
        assert reading.understood == ("/" not in name), text
        if not reading.understood:
            assert reading.why == "its program word contains a path"
        assert tp.assess(text, cwd=tmp_path).level == "ask", text
        assert tp.assess(text).level == ("ask" if "/" in name else "run"), text
