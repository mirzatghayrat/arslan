"""Deploy, publish and secret-write commands ask, this time only, and the card says what happens (③Hands' design,
approved by ⓪Plan on 2026-11-14 on one condition: the card states the concrete consequence, not "Allow?").

Measured on main first, through `terminal_policy.assess` with nothing run: of 43 probes, 13 ran with no card (five
deploys, four publishes, four secret writes). They ask now: the deploy and publish verbs in the `publish` rule's table,
the secret writes in a new rule, `secret-write`, once only and never automatic. fly's, heroku's and wrangler's secret
verbs moved from `publish` to it, so a secret card says "secret". Reads that look like them still run with no card.
"""
from __future__ import annotations

import pytest

from server.services import approvals, card_purpose, command_confirm, hard_rules, permissions, terminal_policy as tp
from server.services.permissions import Request

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
