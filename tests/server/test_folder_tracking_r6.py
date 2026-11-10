"""Additive folder observations preserve main's reader and all named policy rules."""
from collections import Counter
from itertools import product
import json
import shlex

import pytest

from server.services import shell_grammar as sg, terminal_policy as tp
from tests.server.folder_revision_data import MAIN, load_revision
from tests.server import test_folder_tracking_matrix as matrix
from tests.server import test_folder_tracking_r3_matrix as revisions
from tests.server import test_folder_tracking_r4 as r4
from tests.server import test_quoted_args_file_run as quoted
from tests.server import test_quoted_command_word as words
from tests.server import quoted_args_file_run_evidence as evidence
from tests.server.test_s2a3_folder_tracking import A, B, DEL, FIND

# Whole-corpus comparisons: over pytest-timeout's 120 s default on CI runners and under load.
pytestmark = pytest.mark.timeout(600)

# Includes implicit targets, expansions, stack operations, wrappers, loops,
# options, patterns and quote/escape/case spellings accepted by main's reader.
CD_FORMS = (
    'cd', 'cd -', 'cd "$D"', 'cd $D', 'cd "$(pwd)"', 'popd', 'pushd $D',
    'command cd x', 'for x in 1 2; do cd x; done', 'cd -P x', 'cd -- x',
    'cd -L x', 'pushd', 'pushd +1', 'pushd -1', 'cd ~someone', 'cd "~/x"',
    'cd x*', "cd ''", 'cd x y', 'time cd x', 'exec cd x',
    'while false; do cd x; done', 'until true; do cd x; done',
    "'cd' x", '"cd" x', r'c\d x', 'CD x', 'cd x', 'cd ~',
)
SEPARATORS = ('; ', ' && ', '\n')
ENDS = (
    ('rm "-rf" "/"', 'forbid', 'wipe-root'),
    ("rm '-rf' '/'", 'forbid', 'wipe-root'),
    ('security "dump-keychain"', 'forbid', 'keychain-secrets'),
    ('git "push" origin topic', 'ask', 'git-push'),
    ("git 'push' origin topic", 'ask', 'git-push'),
)


@pytest.fixture
def prefix_never_tracks(monkeypatch):
    original = sg._Reader._change_folder

    def checked(self, *args):
        assert self.out.track_folders, "Prefix parsing must never call _change_folder"
        return original(self, *args)

    monkeypatch.setattr(sg._Reader, "_change_folder", checked)


@pytest.mark.parametrize("form, separator, endpoint", tuple(product(CD_FORMS, SEPARATORS, ENDS)))
def test_named_rule_after_unfollowable_move(form, separator, endpoint, prefix_never_tracks):
    end, level, rule = endpoint
    text = form + separator + end
    result = tp.assess(text)
    assert (result.level, result.rule) == (level, rule)
    assert not sg.read_prefix(text).refused
    assert sg.read(text).understood
    if level == 'ask':
        assert tp.ask_rules(text) == {rule}


def named_family():
    seeds = {program + rest for rule, _, program, rest in words.RULES}
    seeds.update(quoted.spelled(command, spelling, 'plain')
                 for command, _, _ in quoted.NAMED for spelling in quoted.FAMILIES)
    seeds.update(quoted.spelled(command, spelling, 'plain')
                 for _, command, _, _ in quoted.OPTION_OPERATIONS for spelling in quoted.FAMILIES)
    # Quote operands of each simple named-rule family too, including families
    # absent from NAMED. Compound seeds retain their original syntax.
    seeds.update(' '.join((program, *(shlex.quote(arg) if not arg.isalnum() else '"' + arg + '"'
                                     for arg in shlex.split(rest))))
                 for _, _, program, rest in words.RULES if '&&' not in rest and '<' not in rest)
    seeds = sorted(seeds)
    for (f, form), (s, separator), (j, seed) in product(enumerate(CD_FORMS), enumerate(SEPARATORS), enumerate(seeds)):
        # Default sample (FOLDER_TRACKING_EVIDENCE_FULL=1 keeps all): a Latin square, so every seed
        # meets every separator once and the move form rotates, reaching every form under each separator.
        if revisions.FULL or f == (j + s) % len(CD_FORMS):
            yield form + separator + seed


@pytest.mark.parametrize("corpus", ('named', 'policy', *evidence.GENERATORS))
def test_no_cwd_equals_main(corpus, monkeypatch, prefix_never_tracks, tmp_path):
    baseline = load_revision(MAIN, monkeypatch)
    if corpus == 'named':
        texts = named_family()
    elif corpus == 'policy':
        texts = matrix._parameters(matrix.policy_cases) | matrix._parameters(words) | matrix._parameters(quoted)
    else:
        # By default the quoted-argument suite's own stratified rows; every row with FULL.
        rows = list(evidence.GENERATORS[corpus]())
        texts = (text for _, text in (rows if revisions.FULL else evidence.stratified(rows)))
    counts = Counter()
    for text in texts:
        before, after = baseline.assess(text), tp.assess(text)
        assert (after.level, after.rule, after.reason) == (before.level, before.rule, before.reason), text
        assert tp.ask_rules(text) == baseline.ask_rules(text), text
        main_read, reading = baseline.shell_grammar.read(text), sg.read(text)
        assert (reading.understood, reading.why, reading.capped, reading.commands) == (
            main_read.understood, main_read.why, main_read.capped, main_read.commands), text
        anchored = tp.assess(text, cwd=tmp_path)
        assert anchored.level == before.level or (before.level, anchored.level) == ('run', 'ask'), text
        if anchored.level == before.level:
            assert anchored.rule == before.rule, text
        counts[before.level + '->' + anchored.level] += 1
    print('R6_IDENTITY ' + json.dumps({'corpus': corpus, 'cases': sum(counts.values()),
                                     'differences': 0, 'with_cwd': counts}, sort_keys=True))


def test_folder_corpus_identity_and_transitions(tmp_path, monkeypatch, prefix_never_tracks):
    from tests.server.test_s2a3_folder_tracking import stand_in_rules
    # Use the same stand-in policy rules as all earlier folder matrices.
    stand_in_rules.__wrapped__(monkeypatch)
    baseline = load_revision(MAIN, monkeypatch)
    corpora = {'original': revisions.repository_corpus(), 'structural': revisions.structural_corpus(),
               'no-effect': matrix._chains()[1], 'common': {text for _, text in r4.common_cases()}}
    assert {k: len(v) for k, v in corpora.items()} == {
        'original': 1340, 'structural': 11816, 'no-effect': 297, 'common': 576}
    plain = tmp_path / 'matrices'
    plain.mkdir()
    matrix.make_plain_tree(set.union(*corpora.values()), plain)
    # Fixed sample by default; FOLDER_TRACKING_EVIDENCE_FULL=1 runs every text.
    cohorts = [(name, revisions.sampled(texts), plain) for name, texts in corpora.items()]
    for topology in ('plain', 'outside-link', 'inside-link', 'deep-link', 'missing'):
        work, outside = tmp_path / topology, tmp_path / (topology + '-outside')
        work.mkdir()
        (outside / B).mkdir(parents=True)
        prefix = A
        if topology == 'plain':
            (work / A / B).mkdir(parents=True)
        elif topology == 'outside-link':
            (work / A).symlink_to(outside, target_is_directory=True)
        elif topology == 'inside-link':
            (work / 'zz-real' / B).mkdir(parents=True)
            (work / A).symlink_to(work / 'zz-real', target_is_directory=True)
        elif topology == 'deep-link':
            (work / A).mkdir()
            (work / A / 'zz-link').symlink_to(outside, target_is_directory=True)
            prefix += '/zz-link'
        texts = {f'{move} {prefix}/{B} && {parent} {up} && {end}'
                 for move, parent, up, end in product(('cd', 'pushd'), ('cd', 'pushd'),
                 ('..', '../.', '../'), (DEL + ' zz-file', FIND + ' zz-file -delete'))}
        assert len(texts) == 24
        cohorts.append((topology, texts, work))
    for name, texts, cwd in cohorts:
        transitions, causes = Counter(), Counter()
        for text in texts:
            before, unknown, after = baseline.assess(text), tp.assess(text), tp.assess(text, cwd=cwd)
            assert (unknown.level, unknown.rule, unknown.reason) == (before.level, before.rule, before.reason), text
            assert tp.ask_rules(text) == baseline.ask_rules(text), text
            assert before.level == after.level or (before.level, after.level) == ('run', 'ask'), text
            if before.level == after.level:
                assert before.rule == after.rule, text
            else:
                assert after.rule in ('delete-outside', 'protected-write'), text
                causes[after.rule] += 1
            transitions[before.level + '->' + after.level] += 1
        print('R6_FOLDERS ' + json.dumps({'corpus': name, 'cases': len(texts), 'differences': 0,
                                       'with_cwd': transitions, 'causes': causes}, sort_keys=True))


@pytest.mark.parametrize('form', CD_FORMS[:24])
def test_unknown_folder_stays_unknown(form):
    reading = sg.read(form + '; cd zz-known; echo ok > zz-file')
    assert reading.understood
    assert reading.commands[-1] == ('echo', 'ok')
    assert reading.folders[-1] == ()
    assert reading.writes[-1] == ('zz-file', ())
