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

from server.services import terminal_policy as tp


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
])
def test_listing_and_reading_cloud_storage_still_runs(command):
    assert tp.assess(command).rule != "upload", command


def test_a_gist_already_asks_as_publishing():
    """`gh gist create f` was never silent: it publishes, which asks this time only too."""
    assert (tp.assess("gh gist create notes.txt").level, tp.assess("gh gist create notes.txt").rule) == ("ask", "publish")
