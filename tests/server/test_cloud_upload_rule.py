"""Cloud storage uploads ask, this time only (Astra on #688/#689, via ⓪Plan, 2026-11-03).

`gcloud storage cp f gs://…`, `gsutil cp`, `aws s3api put-object --body f`, `gh release upload`, `az storage blob
upload`, `azcopy`, `rclone` and `s3cmd` sent local files with no card: the card readers said "may send local data",
but the server's terminal policy had no rule for them. They are the `upload` rule now ("sends data to a website or a
cloud"), so the shared card's upload wording, in the user's language, applies to them as to `aws s3 cp`. A global
option before the subcommand (`aws --profile p s3 cp`) no longer hides it either.

A copy whose direction the text can't tell (`gsutil cp gs://b/f .`, `rclone copy remote:a b`) asks too: the rule
reads the verb, not the direction, as `aws s3 cp` always has.
"""
import pytest

from server.services import card_purpose, task_service, terminal_policy as tp


@pytest.mark.parametrize("command", [
    # Google Cloud
    "gcloud storage cp f.txt gs://b/f.txt", "gcloud --project p storage cp f gs://b", "gcloud alpha storage cp f gs://b",
    "gcloud storage rsync ./site gs://b/site", "gcloud storage mv f gs://b/f",
    "gsutil cp f gs://b/f", "gsutil -m cp -r ./d gs://b", "gsutil rsync -r . gs://b", "gsutil mv f gs://b/f",
    # AWS
    "aws s3api put-object --bucket b --key k --body f", "aws s3api upload-part --bucket b --key k --body f",
    "aws --profile p s3 cp f s3://b/f", "aws --region eu-west-1 s3 sync . s3://b", "aws s3 cp f s3://b/f",
    # GitHub
    "gh release upload v1.0 dist/app.zip",
    # Azure
    "az storage blob upload -f f -c c -n n", "az storage blob upload-batch -d c -s ./d", "az storage file upload -s s --source f",
    "azcopy copy ./d 'https://acct.blob.core.windows.net/c'", "azcopy sync ./d 'https://acct.blob.core.windows.net/c'",
    # rclone, s3cmd
    "rclone copy ./d remote:b", "rclone sync ./d remote:b", "rclone copyto f remote:b/f", "rclone move ./d remote:b",
    "echo hi | rclone rcat remote:b/f", "s3cmd put f s3://b/f", "s3cmd sync ./d s3://b", "s3cmd cp s3://a/f s3://b/f",
    # reached through a launcher, as every layer ② rule is
    "env AWS_PROFILE=p aws s3api put-object --bucket b --key k --body f", "/usr/local/bin/gsutil cp f gs://b",
    # #693 review: a quoted value with a space, or an escaped one, is one option value
    'gsutil -h "Cache-Control:public, max-age=3600" cp f gs://b', 'aws --profile "work account" s3 cp f s3://b',
    'rclone --exclude "My Folder/**" copy ./d remote:b', "rclone --exclude My\\ Folder/** copy ./d remote:b",
    "rclone --exclude 'My Folder/**' sync ./d remote:b",
    # options after the first word too, and for gh and azcopy
    "aws s3 --region r cp f s3://b", "aws s3api --region r put-object --bucket b --key k --body f",
    "gcloud storage --project=p cp f gs://b", "gcloud --verbosity debug alpha --quiet storage cp f gs://b",
    "gh release -R o/r upload v1 f", "gh -R o/r release upload v1 f", "azcopy --log-level=ERROR copy ./d u",
    "az --only-show-errors storage --debug blob upload -f f -c c", "az storage fs file upload -s f -p p -f fs",
    "rclone -P --transfers 8 moveto f remote:b/f", "rclone bisync ./d remote:b", "rclone copyurl https://x remote:b/f",
    "azcopy cp ./d u", "s3cmd -c cfg mv s3://a/f s3://b/f", "s3cmd --acl-public put f s3://b",
    # gsutil's other names for its copy verbs, and aws s3 removal through options
    "gsutil copy f gs://b", "gsutil move f gs://b", "gsutil ren gs://b/a gs://b/c", "gsutil rename gs://b/a gs://b/c",
    "aws s3 mv f s3://b/f", "aws --profile p s3 rm --recursive s3://b",
])
def test_a_cloud_upload_asks_this_time_only(command):
    assert tp.assess(command).level == "ask", command
    assert "upload" in tp.ask_rules(command) and "upload" in tp.ONCE_ONLY_RULES and "upload" in tp.SEND_OUT_RULES


@pytest.mark.parametrize("command", [
    "gcloud storage ls gs://b", "gcloud storage buckets list", "gsutil ls gs://b", "gsutil du -s gs://b",
    "aws s3 ls", "aws s3api list-objects --bucket b", "aws s3api head-object --bucket b --key k",
    "gh release view v1.0", "gh release list", "az storage blob list -c c", "rclone ls remote:b", "rclone lsd remote:",
    "s3cmd ls s3://b", "s3cmd info s3://b/f", "echo gsutil cp is how you upload",
    "aws s3api put-object-tagging --bucket b --key k --tagging t",   # a longer subcommand: metadata, no file sent
    'gsutil -h "x: y" ls gs://b', "aws --profile p s3 ls", "gh -R o/r release view v1", "rclone --exclude 'a b' lsd x:",
])
def test_listing_and_reading_cloud_storage_still_runs(command):
    assert tp.assess(command).rule != "upload", command


def test_a_gist_already_asks_as_publishing():
    """`gh gist create f` was never silent: it publishes, which asks this time only too."""
    assert (tp.assess("gh gist create notes.txt").level, tp.assess("gh gist create notes.txt").rule) == ("ask", "publish")


@pytest.mark.parametrize("command", [
    "azcopy c ./d https://x.example/c", "azcopy s ./d https://x.example/c", "azcopy sc ./d https://x.example/c",
    "azcopy --log-level=ERROR c ./d https://x.example/c",
    "az storage blob sync -c c -s ./d",
])
def test_short_azcopy_subcommands_and_a_blob_sync_ask_too(command):
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", "upload"), command


@pytest.mark.parametrize("command", ["aws s3 cp$X f s3://b/f", "gsutil rsync${X} d gs://b", "s3cmd put$X f s3://b/f"])
def test_a_variable_glued_to_the_verb_still_asks(command):
    """The verb's end isn't a word boundary because `put-object-tagging` isn't `put-object`, but `$` can't be part of
    a verb, so a variable there doesn't change what runs."""
    assert tp.assess(command).rule == "upload", command


@pytest.mark.parametrize("command", [
    "s3cmd --version && cp a b", "rclone --version; mv a b", "azcopy --version || cp a b", "aws --version | cp a b",
    "gsutil --version & cp a b",
])
def test_an_option_doesnt_read_past_the_end_of_its_command(command):
    """`&&`, `;`, `|` and `&` end the command, so the next command's `cp` isn't the cloud tool's verb."""
    assert tp.assess(command).rule != "upload", command


def test_a_run_of_options_with_no_values_stays_linear():
    """An option's value can't start with `-` (`_opts`'s lookahead). Without that each option could be read two ways,
    which grows the work about 1.6 times per option: a few seconds at this length, so it fails rather than hangs."""
    import re
    import time
    rule = [re.compile(p, re.I) for key, p, _ in tp._ASK if key == "upload" and "gsutil" in p][0]
    start = time.perf_counter()
    assert rule.search("aws " + "-x " * 34 + "ls") is None
    assert time.perf_counter() - start < 0.25


@pytest.mark.parametrize("command", ["aws " + "-x s3 " * 3600 + "ls", "gcloud " + "-x storage " * 2000 + "ls",
                                     "gh " + "-x release " * 2000 + "view", "rclone " + "--e 'a b' " * 2500 + "lsd"])
def test_the_cloud_rule_stays_linear_on_long_option_chains(command):
    """An option's value is never the next word (`_opts`'s lookahead), so a chain of options whose values are that
    word is read one way only. The pattern alone, on about 22 kB: a few ms here, over a second without the lookahead
    (quadratic); the 0.25 s bound leaves room for a loaded CI runner."""
    import re
    import time
    rule = [re.compile(p, re.I) for key, p, _ in tp._ASK if key == "upload" and "gsutil" in p][0]
    start = time.perf_counter()
    assert rule.search(command) is None
    assert time.perf_counter() - start < 0.25


@pytest.mark.parametrize("depth", [256, 1000, 2000])
def test_commands_nested_past_what_can_be_read_ask_as_unreadable(depth):
    """Each nested `$(` was one Python frame deeper, so past the recursion limit every reader raised and ended the turn
    with no run and no card."""
    command = "$(x " * depth
    verdict = tp.assess(command)
    assert (verdict.level, verdict.rule) == ("ask", tp.UNREADABLE)
    assert tp.ask_rules(command) == {tp.UNREADABLE}
    assert tp.other_osa_language(command) is False
    assert task_service.unwrapped_once(command) is False
    assert card_purpose.phrase(command, "")


def test_a_forbidden_first_command_stays_forbidden_past_the_limit():
    assert tp.assess("rm -rf / ; " + "$(x " * 1000).level == "forbid"


def test_nesting_under_the_limit_is_still_read_with_the_stack_a_turn_has_used():
    """The limit has to leave room: a turn's dispatch is already some frames deep when it reads a command."""
    def deep(frames: int):
        return deep(frames - 1) if frames else tp.assess("$(" * 255 + "git push")
    assert deep(200).rule == "git-push"
