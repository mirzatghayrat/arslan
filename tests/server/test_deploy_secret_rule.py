"""Deploy, publish and secret-write commands ask, this time only, and the card says what happens (③Hands' design,
approved by ⓪Plan on 2026-11-14 on one condition: the card states the concrete consequence, not "Allow?").

Measured on main first, through `terminal_policy.assess` with nothing run: of 43 probes, 13 ran with no card (five
deploys, four publishes, four secret writes). They ask now: the deploy and publish verbs in the `publish` rule's table,
the secret writes in a new rule, `secret-write`, once only and never automatic. fly's, heroku's and wrangler's secret
verbs moved from `publish` to it, so a secret card says "secret". Reads that look like them still run with no card.
"""
from __future__ import annotations

import os

import pytest

from server.services import approvals, card_purpose, command_confirm, hard_rules, permissions, terminal_policy as tp
from server.services.permissions import Request
from tests.server import quoted_args_option_profiles as profiles

# ── the 43 measured probes ─────────────────────────────────────────────────────

#: The 13 that ran with no card on main, and the rule each asks with now.
GAPS = [
    ("render deploy", "publish"), ("gcloud app deploy", "publish"), ("pulumi up --yes", "publish"),
    ("eas submit", "publish"), ("fastlane deliver", "publish"),
    ("yarn npm publish", "publish"), ("uv publish", "publish"), ("gem push zz.gem", "publish"),
    ("poetry publish", "publish"),
    ("gh secret set ZZ --body x", "secret-write"), ("vercel env add ZZ production", "secret-write"),
    ("netlify env:set ZZ x", "secret-write"),
    ("aws secretsmanager put-secret-value --secret-id zz --secret-string x", "secret-write"),
]
#: The three that asked as `publish` on main and ask as `secret-write` now.
MOVED = ["fly secrets set ZZ=x", "heroku config:set ZZ=x", "wrangler secret put ZZ"]
#: The 30 that asked on main (the three moved ones among them), with main's verdict, which they keep.
KEPT = [
    ("vercel deploy --prod", "ask", "publish"), ("vercel --prod", "ask", "publish"),
    ("netlify deploy --prod", "ask", "publish"), ("fly deploy", "ask", "publish"), ("flyctl deploy", "ask", "publish"),
    ("firebase deploy", "ask", "publish"), ("wrangler deploy", "ask", "publish"), ("wrangler publish", "ask", "publish"),
    ("heroku container:release web", "ask", "publish"), ("git push heroku main", "ask", "git-push"),
    ("railway up", "ask", "publish"), ("aws s3 sync ./dist s3://zz-bucket", "ask", "upload"),
    ("kubectl apply -f k.yaml", "ask", "publish"), ("terraform apply -auto-approve", "ask", "publish"),
    ("docker push zz/img:1", "ask", "publish"), ("xcrun altool --upload-app -f a.ipa", "ask", "unreadable"),
    ("npm publish", "ask", "publish"), ("pnpm publish", "ask", "publish"), ("cargo publish", "ask", "publish"),
    ("twine upload dist/*", "ask", "publish"), ("gh release create v1", "ask", "publish"),
    *((command, "ask", "publish") for command in MOVED),
    ("security add-generic-password -a zz -s zz -w x", "ask", "keychain-write"),
    ("security delete-generic-password -s zz", "ask", "keychain-write"),
    ("security -i", "ask", "unreadable"), ('echo "delete-keychain zz" | security -i', "ask", "unreadable"),
    ("security -i < cmds.txt", "ask", "unreadable"),
    ("security find-generic-password -s zz -w", "forbid", "keychain-secrets"),
]
#: Reads that look like them: they run with no card, as on main.
LOOK_ALIKES = ["gh secret list", "vercel env ls", "pulumi preview", "gcloud app describe", "netlify env:list",
               "aws secretsmanager list-secrets", "npm view x", "fly secrets list", "wrangler secret list",
               "heroku config:get K", "gh variable list", "gcloud secrets list", "doppler secrets get ZZ",
               "render deploys list", "eas build", "fastlane lanes", "pulumi stack ls", "uv sync", "gem install zz",
               "poetry install", "yarn npm info zz", "gcloud run services list"]


def test_the_measured_probes_are_43():
    assert len(GAPS) == 13 and len(KEPT) == 30 and len(GAPS) + len(KEPT) == 43


@pytest.mark.parametrize("command, rule", GAPS)
def test_each_measured_gap_asks_with_its_rule(command, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", rule) and rule in tp.ask_rules(command)


@pytest.mark.parametrize("command, level, rule", KEPT)
def test_what_already_asked_keeps_its_rule_but_the_moved_secrets(command, level, rule):
    verdict = tp.assess(command)
    expected = "secret-write" if command in MOVED else rule
    assert (verdict.level, verdict.rule) == (level, expected)
    if command in MOVED:
        assert tp.ask_rules(command) == {"secret-write"}            # no longer `publish` at all


@pytest.mark.parametrize("command", LOOK_ALIKES)
def test_a_look_alike_read_runs_with_no_card(command):
    assert tp.assess(command).level == "run" and not tp.ask_rules(command)


@pytest.mark.parametrize("command, rule", [
    # deploys and publishes past the measured spellings: aliases, options before the verb, a release track
    ("render deploys create srv-1", "publish"), ("gcloud run deploy svc", "publish"),
    ("gcloud functions deploy fn", "publish"), ("gcloud beta run deploy svc", "publish"),
    ("gcloud --project p app deploy", "publish"), ("pulumi update", "publish"), ("eas build --auto-submit", "publish"),
    ("fastlane pilot", "publish"), ("fastlane upload_to_testflight", "publish"), ("cd x && uv publish", "publish"),
    ("sh -c 'gem push zz-1.0.gem'", "publish"),
    # secret writes and removals, each family
    ("gh secret delete ZZ", "secret-write"), ("gh -R o/r secret set ZZ", "secret-write"),
    ("gh variable set ZZ --body x", "secret-write"), ("vc env rm ZZ production", "secret-write"),
    ("ntl env:unset ZZ", "secret-write"), ("aws --profile p secretsmanager create-secret --name zz", "secret-write"),
    ("aws ssm put-parameter --name n --value v", "secret-write"), ("gcloud secrets create zz", "secret-write"),
    ("gcloud secrets versions add zz --data-file=f", "secret-write"), ("doppler secrets set ZZ=x", "secret-write"),
    ("flyctl secrets unset ZZ", "secret-write"), ("fly -a x secrets set ZZ=x", "secret-write"),
    ("heroku config:unset ZZ", "secret-write"), ("wrangler secret delete ZZ", "secret-write"),
    ("/usr/local/bin/heroku config:add ZZ=x", "secret-write"),
])
def test_the_rest_of_each_family_asks(command, rule):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", rule)


# ── secret-write is once only and never automatic ──────────────────────────────

def test_secret_write_is_once_only_and_never_auto():
    assert "secret-write" in tp.ONCE_ONLY_RULES and "secret-write" in hard_rules.NEVER_AUTO_RULES
    assert "secret-write" in {rule for row in hard_rules.NEVER_AUTO for rule in row.rules}
    assert "secret-write" in tp.SEND_OUT_RULES                 # a failed write may have reached the service
    for command in ("gh secret set ZZ --body x", "fly secrets set ZZ=x"):
        target = "rules:" + "|".join(sorted(tp.ask_rules(command)))
        assert hard_rules.never_auto(Request(kind="command", target=target, title="t", detail=command,
                                             once_only=False)) is True
        assert approvals.island_may_answer({"type": "propose_run_command", "pretty": command,
                                            "perm_kind": "command"}) is False
    assert "secret-write" in approvals._island_risky_rules()       # never_auto's command part, read by the island


# ── the consequence the card states ────────────────────────────────────────────

@pytest.mark.parametrize("command, key, params", [
    # publish: the package and version from the words, else the registry alone
    ("npm publish ./my-pkg-1.2.3.tgz", "publishes", {"package": "my-pkg@1.2.3", "registry": "npm"}),
    ("twine upload dist/pkg-1.0-py3-none-any.whl", "publishes", {"package": "pkg@1.0", "registry": "PyPI"}),
    ("cargo publish -p foo", "publishes", {"package": "foo", "registry": "crates.io"}),
    ("gem push zz.gem", "publishes", {"package": "zz", "registry": "RubyGems"}),
    ("uv publish", "publishesTo", {"registry": "PyPI"}),
    ("twine upload dist/*", "publishesTo", {"registry": "PyPI"}),
    # deploy: the folder or app from the words, else the service alone
    ("vercel deploy ./web", "deploys", {"target": "./web", "service": "Vercel"}),
    ("fly -a myapp deploy", "deploys", {"target": "myapp", "service": "Fly.io"}),
    ("gcloud beta run deploy svc", "deploys", {"target": "svc", "service": "Cloud Run"}),
    ("render deploy", "deploysTo", {"service": "Render"}),
    ("vercel --prod", "deploysTo", {"service": "Vercel"}),
    ("fastlane pilot", "deploysTo", {"service": "TestFlight"}),
    # secret write: the NAME is the first word after the verb; where, the repo or app, else the service
    ("gh secret set ZZ --body x", "setsSecret", {"name": "ZZ", "where": "GitHub"}),
    ("gh secret set -R o/r TOKEN", "setsSecret", {"name": "TOKEN", "where": "o/r"}),
    ("fly secrets set ZZ=x", "setsSecret", {"name": "ZZ", "where": "Fly.io"}),
    ("heroku -a shop config:set ZZ=x", "setsSecret", {"name": "ZZ", "where": "shop"}),
    ("aws secretsmanager put-secret-value --secret-id zz --secret-string x", "setsSecret",
     {"name": "zz", "where": "AWS Secrets Manager"}),
    ("gh secret delete ZZ", "removesSecret", {"name": "ZZ", "where": "GitHub"}),
    # an option this can't place before the name: its value could be the secret, so no name is shown
    ("gh secret set --body hunter2 ZZ", "setsASecret", {"where": "GitHub"}),
    ("vercel deploy --token t0k3n", "deploysTo", {"service": "Vercel"}),
])
def test_the_consequence_is_read_from_the_words(command, key, params):
    assert tp.consequence(command) == (key, params)


def test_the_consequence_never_shows_a_value_that_followed_an_unknown_option():
    for command in ("gh secret set --body hunter2 ZZ", "vercel deploy --token t0k3n", "netlify env:set --x hunter2"):
        assert "hunter2" not in str(tp.consequence(command)) and "t0k3n" not in str(tp.consequence(command))


def test_only_a_publish_deploy_or_secret_step_has_one():
    for command in ("gh pr create --fill", "kubectl apply -f k.yaml", "gh secret list", "ls", "npm view x"):
        assert tp.consequence(command) is None


@pytest.mark.parametrize("lang, command, line", [
    ("en", "npm publish ./my-pkg-1.2.3.tgz", "Publishes my-pkg@1.2.3 to npm, public and permanent"),
    ("en", "uv publish", "Publishes to PyPI, public and permanent"),
    ("en", "vercel deploy ./web", "Deploys ./web to Vercel"),
    ("en", "gh secret set ZZ --body x", "Sets secret ZZ in GitHub, which CI or production will read"),
    ("zh", "gh secret set ZZ --body x", "在 GitHub 设置密钥 ZZ，CI 或线上环境会读取它"),
    ("en", "ls", ""),
])
def test_the_card_line_in_the_users_language(lang, command, line):
    assert card_purpose.consequence(command, lang) == line


def test_every_language_has_every_consequence_line():
    keys = {"publishes", "publishesTo", "deploys", "deploysTo", "setsSecret", "setsASecret", "removesSecret",
            "removesASecret"}
    for lang in ("en", "zh", "ja", "es", "de", "fr"):
        assert keys <= set(card_purpose.TEXT[lang]["fact"]), lang


class _Asker:
    def __init__(self):
        self.frames: list[dict] = []

    async def __call__(self, frame):
        self.frames.append(frame)
        return {"approved": False, "scope": "once", "note": "", "by": "mac", "call_id": frame["call_id"]}


@pytest.mark.parametrize("kw", [{}, {"sandbox": "outside"}], ids=["ordinary", "outside"])
async def test_the_card_leads_with_the_consequence_in_its_existing_fields(execution_db, kw):
    """No new frame key: the line leads the Mac card's touches row and the phone's `reason`."""
    asker = _Asker()
    with permissions.asking_with(asker):
        await command_confirm.Confirmations("c1").command("gh secret set ZZ --body x", [], **kw)
    [frame] = asker.frames
    line = "Sets secret ZZ in GitHub, which CI or production will read"
    assert frame["summary"]["touches"][0] == line and frame["reason"].startswith(line)
    assert frame["rules"] == ["secret-write"]


def test_a_card_with_no_consequence_keeps_its_fields():
    frame = {"summary": {"touches": ["a"]}, "reason": "r"}
    command_confirm.with_consequence(frame, "")
    assert frame == {"summary": {"touches": ["a"]}, "reason": "r"}


# ── options between the program and its verb words (Codex's round-1 item 1 on #897) ──────────────────────────────
# A CLI reads its options wherever they stand, so `gcloud app --project X deploy` is `gcloud app deploy`. The verb
# path is read past options: a known option's value (`_OPTION_VALUES`) is skipped with it, and an unknown option's
# arity is unknown, so both readings are tried and either one placing a write verb asks.

OPTION_BETWEEN = [
    # the seven Codex named
    ("gcloud app --project X deploy", "publish"), ("gcloud --quiet run deploy svc", "publish"),
    ("fly --app a secrets set K=v", "secret-write"), ("gh --repo o/r secret set K", "secret-write"),
    ("vercel --token t env add K production", "secret-write"),
    ("aws --region r secretsmanager put-secret-value --secret-id x --secret-string y", "secret-write"),
    ("heroku config:set --app a K=v", "secret-write"),
    # more from the option profiles: a value option, its spaced and attached forms, flags and unknown options,
    # between the words of a two-word verb and before a one-word verb
    ("fly secrets --app a set K=v", "secret-write"), ("fly secrets --app 'Sample Account' set K=v", "secret-write"),
    ("flyctl secrets -t tok unset K", "secret-write"), ("fly secrets -aSample import", "secret-write"),
    ("vercel env --token t add K production", "secret-write"), ("vercel env -t t rm K", "secret-write"),
    ("wrangler secret -e prod put K", "secret-write"), ("wrangler secret --env=prod delete K", "secret-write"),
    ("heroku --weird config:set K=V", "secret-write"), ("gh variable -R o/r set K", "secret-write"),
    ("gh secret --repo 'Sample Account' delete K", "secret-write"),
    ("doppler secrets --config prd set K=v", "secret-write"), ("doppler --s2a3-unknown secrets set K", "secret-write"),
    ("gcloud secrets --project p versions add zz --data-file=f", "secret-write"),
    ("aws ssm --region r put-parameter --name n --value v", "secret-write"),
    ("netlify --auth t env:set K v", "secret-write"),
    ("yarn npm --silent publish", "publish"), ("yarn --cwd d npm publish", "publish"),
    ("yarn npm --cwd 'Sample Account' publish", "publish"), ("uv --s2a3-unknown publish", "publish"),
    ("uv -Z x publish", "publish"), ("pulumi --non-interactive up", "publish"),
    ("render deploys -o json create srv-1", "publish"), ("gcloud beta --quiet run deploy svc", "publish"),
    ("gcloud app --weird X deploy", "publish"), ("fly scale --app x count 2", "publish"),
    ("wrangler pages --env prod deploy dist", "publish"), ("eas --x submit", "publish"),
    ("fastlane --verbose upload_to_testflight", "publish"), ("eas --x build --auto-submit", "publish"),
    ("poetry -q publish", "publish"), ("gem -V push zz.gem", "publish"),
]
#: Reads with the same options between their words: they run with no card.
OPTION_BETWEEN_READS = [
    "gcloud app --project X describe", "gh --repo o/r secret list", "fly --app a secrets list",
    "vercel --token t env ls", "gh -R o/r variable list", "aws --region r secretsmanager list-secrets",
    "gcloud --project p secrets list", "yarn --cwd d npm info zz", "doppler --config prd secrets get K",
    "uv --s2a3-unknown sync", "pulumi --non-interactive preview", "gcloud --quiet run services list",
    "heroku config:get --app a K", "render deploys -o json list", "gh secret --repo o/r list",
]


@pytest.mark.parametrize("command, rule", OPTION_BETWEEN)
def test_options_between_the_words_still_ask_with_the_rule(command, rule):
    assert len(OPTION_BETWEEN) >= 17
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", rule), command


@pytest.mark.parametrize("command", OPTION_BETWEEN_READS)
def test_reads_with_options_between_still_run(command):
    assert tp.assess(command).level == "run" and not tp.ask_rules(command), command


# The corpus: every write verb path in the three tables, with each option form from the option profiles
# (`quoted_args_option_profiles.OPTIONS`: a flag, a short and a long value option; the program's unknown-option forms
# for every program) at every gap from before the first verb word to after the last, rendered in the profiles' six
# spellings and four positions. The reads beside them get the same forms.
FULL = os.environ.get("QUOTED_ARGS_EVIDENCE_FULL") == "1"
_UNKNOWN_FORMS = (("-Z",), ("--s2a3-unknown",), ("-ZSample",), ("-ZvZ",), ("--s2a3-unknown", "sample"),
                  ("-Z", "Sample Account"))
_READ_PATHS = [
    ("gcloud", ("app", "describe")), ("gcloud", ("secrets", "list")), ("gcloud", ("run", "services", "list")),
    ("gh", ("secret", "list")), ("gh", ("variable", "list")), ("fly", ("secrets", "list")), ("flyctl", ("status",)),
    ("vercel", ("env", "ls")), ("netlify", ("env:list",)), ("heroku", ("config:get",)), ("wrangler", ("secret", "list")),
    ("doppler", ("secrets", "get")), ("aws", ("secretsmanager", "list-secrets")), ("aws", ("ssm", "get-parameter")),
    ("render", ("deploys", "list")), ("pulumi", ("preview",)), ("pulumi", ("stack", "ls")), ("uv", ("sync",)),
    ("gem", ("install",)), ("poetry", ("install",)), ("yarn", ("npm", "info")), ("eas", ("build",)),
    ("fastlane", ("lanes",)), ("firebase", ("projects:list",)), ("helm", ("list",)), ("railway", ("status",)),
]


def _option_forms(program):
    flag, short, long = profiles.OPTIONS.get(program, ("", "", ""))
    forms = []
    if flag:
        forms += [(flag,)] + ([(flag + flag[1:],)] if len(flag) == 2 else [])
    for value in filter(None, (short, long)):
        forms += [(value, "sample"), (value, "Sample Account")]
    if short:
        forms += [(short + "Sample",)] + ([(flag + short[1:], "Sample")] if len(flag) == 2 else [])
    if long:
        forms += [(long + "=Sample",)]
    return forms + list(_UNKNOWN_FORMS)


def _between(paths):
    for program, verb in paths:
        for form in _option_forms(program):
            for gap in range(len(verb) + 1):
                yield program, verb, (program, *verb[:gap], *form, *verb[gap:], "sample")


def option_between_corpus():
    """(text, rule) for the writes, (text, None) for the reads, each in every spelling and position."""
    writes = sorted({(program, verb, rule) for rule, table in (
        ("publish", tp._DEPLOY_PUBLISH), ("publish", tp._PUBLISH_MORE), ("secret-write", tp._SECRET_WRITE))
        for program, verbs in table.items() for verb in verbs})
    rows = [(words, rule) for program, verb, rule in writes for _, _, words in _between([(program, verb)])]
    rows += [(words, None) for _, _, words in _between(_READ_PATHS)]
    renderings = [(family, position) for family in profiles.FAMILIES for position in profiles.POSITIONS]
    for j, (words, rule) in enumerate(rows):
        # By default each row in one spelling and position, rotating through all 24; every one with FULL.
        for family, position in renderings if FULL else renderings[j % len(renderings):][:1]:
            yield words, profiles.render(words, family, position), rule


def _measure():
    misses, new_read_asks, writes, reads = [], [], 0, 0
    for words, text, rule in option_between_corpus():
        verdict = tp.assess(text)
        if rule:
            writes += 1
            if (verdict.level, verdict.rule) != ("ask", rule):
                misses.append(text)
        else:
            reads += 1
            program = tp._PROGRAM_ALIASES.get(words[0], words[0])
            # #821's reading, kept: a deploy CLI's verb this reader can't place asks as `publish`
            unplaceable = program in tp._DEPLOY_PROGRAMS and tp._verb_unplaceable(program, words[1:])
            if verdict.level != "run" and not (unplaceable and (verdict.level, verdict.rule) == ("ask", "publish")
                                               and tp.ask_rules(text) == {"publish"}):
                new_read_asks.append(text)
    return misses, new_read_asks, writes, reads


def test_the_option_between_corpus_has_no_miss_and_no_new_read_ask():
    """Measured on the full corpus (QUOTED_ARGS_EVIDENCE_FULL=1, 67,440 write and 16,104 read rows): before this,
    10,053 write rows missed (4,437 ran with no card, 5,616 asked as `publish` instead of `secret-write`); after it,
    none, and no read row's verdict changed."""
    misses, new_read_asks, writes, reads = _measure()
    assert (writes, reads) == ((67440, 16104) if FULL else (2810, 671))
    assert not misses, (len(misses), misses[:10])
    assert not new_read_asks, (len(new_read_asks), new_read_asks[:10])
