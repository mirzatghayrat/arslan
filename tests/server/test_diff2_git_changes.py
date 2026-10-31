"""DIFF2-1 (v0.1.64, card docs/plans/0164/DIFF2-git-changes.md): Changes for a working folder that is a git repo, on
real repositories made in tmp_path. git only reads its object store (rev-parse, merge-base, log, ls-tree, cat-file,
ls-files --others); Arslan hashes the working files itself, so no program named in the repo's config runs. PRs come
from `gh` when it is signed in. Fixture text is synthetic."""
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from server.services import checkpoints, git_changes

pytestmark = pytest.mark.skipif(subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
                                reason="needs git")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture(autouse=True)
def _fresh_caches():
    git_changes._hashes.clear()
    git_changes._counts.clear()
    git_changes._pr_cache.clear()


@pytest.fixture
def repo(tmp_path) -> Path:
    """main: a.md, b.md, gone.md; branch feature: one commit editing a.md and deleting gone.md."""
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, "a.md", "one\ntwo\nthree\n")
    write(root, "b.md", "keep\n")
    write(root, "gone.md", "bye\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "checkout", "-qb", "feature")
    write(root, "a.md", "one\nTWO\nthree\n")
    (root / "gone.md").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Edit a, drop gone")
    return root


def by_path(summary: dict) -> dict:
    return {f["path"]: f for f in summary["files"]}


def test_the_branch_against_main_committed_and_uncommitted_together(repo):
    write(repo, "b.md", "keep\nmore\n")                         # uncommitted edit
    write(repo, "notes/new.md", "fresh\n")                       # not in git yet
    s = git_changes.summary(repo, repo)
    assert (s["branch"], s["detached"], s["base"]) == ("feature", None, "main")
    assert [c["subject"] for c in s["commits"]] == ["Edit a, drop gone"]
    files = by_path(s)
    assert {p: (f["kind"], f["uncommitted"]) for p, f in files.items()} == {
        "a.md": ("edited", False), "gone.md": ("deleted", False), "b.md": ("edited", True), "notes/new.md": ("made", True)}
    assert (files["a.md"]["added"], files["a.md"]["removed"]) == (1, 1)
    assert (files["notes/new.md"]["added"], files["gone.md"]["removed"]) == (1, 1)
    assert s["more"] == 0


def test_a_change_undone_in_the_working_tree_is_not_listed(repo):
    write(repo, "a.md", "one\ntwo\nthree\n")                     # back to main's bytes
    assert "a.md" not in by_path(git_changes.summary(repo, repo))


def test_origin_head_is_the_base_when_there_is_one(repo):
    git(repo, "update-ref", "refs/remotes/origin/trunk", "main")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    assert git_changes.summary(repo, repo)["base"] == "origin/trunk"


def test_detached_and_without_a_default_branch(repo):
    git(repo, "branch", "-qm", "main", "trunk-renamed")
    head = git(repo, "rev-parse", "--short", "HEAD").strip()
    git(repo, "checkout", "-q", "--detach")
    write(repo, "b.md", "changed\n")
    s = git_changes.summary(repo, repo)
    assert (s["branch"], s["detached"], s["base"], s["commits"]) == (None, head, None, [])
    assert set(by_path(s)) == {"b.md"}                           # no base: what is not committed only


def test_a_repo_without_commits_lists_every_file_as_made(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, "x.txt", "x\n")
    s = git_changes.summary(root, root)
    assert (s["branch"], s["base"]) == ("main", None)
    assert {p: f["kind"] for p, f in by_path(s).items()} == {"x.txt": "made"}


def test_programs_named_in_the_repos_config_never_run(repo):
    """The card's probe as a test: plain `git diff` ran this filter driver; nothing here may."""
    marks = repo.parent / "marks"
    marks.mkdir()
    for key, name in (("filter.evil.clean", "clean"), ("filter.evil.smudge", "smudge"), ("filter.evil.process", "process"),
                      ("core.fsmonitor", "fsmonitor"), ("diff.evil.textconv", "textconv"), ("diff.evil.command", "extdiff"),
                      ("diff.external", "external"), ("gpg.program", "gpg"), ("core.pager", "pager")):
        git(repo, "config", key, f"sh -c 'touch {marks / name}; cat'")
    git(repo, "config", "log.showSignature", "true")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* filter=evil diff=evil\n")
    hooks = repo / ".git" / "hooks"
    for hook in ("post-checkout", "pre-commit", "reference-transaction"):
        (hooks / hook).write_text(f"#!/bin/sh\ntouch {marks / hook}\n")
        (hooks / hook).chmod(0o755)
    time.sleep(1.1)                                               # every file's mtime differs from the index's
    write(repo, "a.md", "one\nTWO\nthree\nfour\n")
    s = git_changes.summary(repo, repo)
    git_changes.file_diff(repo, repo, "a.md")
    assert by_path(s)["a.md"]["uncommitted"] is True
    assert sorted(p.name for p in marks.iterdir()) == []


def test_the_working_file_is_hashed_once_until_it_changes(repo, monkeypatch):
    calls = []
    real = git_changes._hash_file

    def counting(*args):
        calls.append(args[-1])
        return real(*args)
    monkeypatch.setattr(git_changes, "_hash_file", counting)
    git_changes.summary(repo, repo)
    first = len(calls)
    assert first >= 2
    git_changes.summary(repo, repo)
    assert len(calls) == first                                   # (size, mtime) unchanged: from the cache
    time.sleep(0.01)
    write(repo, "b.md", "keep\nagain\n")
    git_changes.summary(repo, repo)
    assert calls[first:] == ["b.md"]


def test_a_symlink_is_compared_as_a_link_and_never_followed(repo, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("outside the repo\n")
    (repo / "link.md").symlink_to(outside)
    s = git_changes.summary(repo, repo)
    assert by_path(s)["link.md"]["kind"] == "made"
    with pytest.raises(checkpoints.NoDiff) as exc:
        git_changes.file_diff(repo, repo, "link.md")
    assert exc.value.code == "not_text"


def test_one_files_diff_in_diff1s_shape(repo):
    d = git_changes.file_diff(repo, repo, "a.md")
    assert (d["kind"], d["added"], d["removed"]) == ("edited", 1, 1)
    assert d["lines"] == [[" ", 1, 1, "one"], ["-", 2, None, "two"], ["+", None, 2, "TWO"], [" ", 3, 3, "three"]]
    assert git_changes.file_diff(repo, repo, "gone.md")["lines"] == [["-", 1, None, "bye"]]


@pytest.mark.parametrize("rel,code", [("b.md", "not_listed"), ("../proj/a.md", "not_listed"), (".git/config", "not_listed")])
def test_only_a_listed_path_has_a_diff(repo, rel, code):
    with pytest.raises(checkpoints.NoDiff) as exc:
        git_changes.file_diff(repo, repo, rel)
    assert exc.value.code == code


def test_a_secret_shaped_name_is_listed_but_not_shown(repo):
    write(repo, ".env", "TOKEN=x\n")
    assert ".env" in by_path(git_changes.summary(repo, repo))
    with pytest.raises(checkpoints.NoDiff) as exc:
        git_changes.file_diff(repo, repo, ".env")
    assert exc.value.code == "hidden"


def test_a_git_lfs_pointer_says_so(repo):
    git(repo, "checkout", "-q", "main")
    write(repo, "big.bin", "version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 9\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "lfs")
    git(repo, "checkout", "-qb", "other")
    write(repo, "big.bin", "real bytes\n")
    with pytest.raises(checkpoints.NoDiff) as exc:
        git_changes.file_diff(repo, repo, "big.bin")
    assert exc.value.code == "lfs"


def test_the_list_is_capped(repo, monkeypatch):
    monkeypatch.setattr(git_changes, "MAX_FILES", 2)
    for i in range(4):
        write(repo, f"n{i}.md", "x\n")
    s = git_changes.summary(repo, repo)
    assert len(s["files"]) == 2 and s["more"] == 4


def test_a_folder_inside_a_repo_shows_only_its_own_files(repo, tmp_path):
    write(repo, "sub/inner.md", "in\n")
    found = git_changes.repo_root(repo / "sub", home=tmp_path)
    assert found == repo
    s = git_changes.summary(repo, repo / "sub")
    assert set(by_path(s)) == {"sub/inner.md"}


def test_the_walk_up_stops_at_home_and_outside_home_only_the_folder_counts(repo, tmp_path):
    (repo / "deep").mkdir()
    assert git_changes.repo_root(repo / "deep", home=repo) is None              # home itself is not looked at
    assert git_changes.repo_root(repo / "deep", home=tmp_path / "elsewhere") is None
    assert git_changes.repo_root(repo, home=tmp_path / "elsewhere") == repo
    assert git_changes.repo_root(tmp_path, home=tmp_path / "elsewhere") is None


# -- PRs through gh ------------------------------------------------------------------------------------------

def fake_gh(tmp_path, monkeypatch, *, auth_ok=True, prs="[]", sleep=0.0) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "gh.log"
    (bin_dir / "gh").write_text(f"""#!/bin/sh
echo "$@" >> {log}
if [ "$1" = auth ]; then {'exit 0' if auth_ok else 'echo "not logged in" >&2; exit 1'}; fi
sleep {sleep}
cat <<'JSON'
{prs}
JSON
""")
    (bin_dir / "gh").chmod((bin_dir / "gh").stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


ROLLUP = """[
 {"number": 42, "title": "Dark mode", "state": "OPEN", "isDraft": false, "url": "https://github.com/o/r/pull/42",
  "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}, {"state": "SUCCESS"}]},
 {"number": 41, "title": "Broken", "state": "OPEN", "isDraft": true, "url": "https://github.com/o/r/pull/41",
  "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "FAILURE"}]},
 {"number": 40, "title": "Busy", "state": "MERGED", "isDraft": false, "url": "https://github.com/o/r/pull/40",
  "statusCheckRollup": [{"status": "IN_PROGRESS", "conclusion": ""}, {"state": "PENDING"}]},
 {"number": 39, "title": "Bare", "state": "CLOSED", "isDraft": false, "url": "javascript:alert(1)", "statusCheckRollup": []}
]"""


def test_prs_with_their_state_and_checks(repo, tmp_path, monkeypatch):
    log = fake_gh(tmp_path, monkeypatch, prs=ROLLUP)
    out = git_changes.prs(repo, "feature")
    assert out["signed_in"] is True
    assert [(p["number"], p["state"], p["draft"], p["checks"]) for p in out["prs"]] == [
        (42, "open", False, "passed"), (41, "open", True, "failing"), (40, "merged", False, "running"),
        (39, "closed", False, None)]
    assert out["prs"][3]["url"] is None                                         # only an https link is kept
    assert "--head feature" in log.read_text()


def test_gh_signed_out_or_missing_is_not_signed_in(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, auth_ok=False)
    assert git_changes.prs(repo, "feature") == {"signed_in": False, "prs": []}
    git_changes._pr_cache.clear()
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    monkeypatch.setattr(git_changes, "merged_path", lambda: str(tmp_path / "nothing"))
    assert git_changes.prs(repo, "feature") == {"signed_in": False, "prs": []}


def test_a_slow_gh_is_unavailable_not_a_hang(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, sleep=5)
    monkeypatch.setattr(git_changes, "GH_TIMEOUT_S", 0.5)
    assert git_changes.prs(repo, "feature") == {"signed_in": True, "prs": [], "error": "unavailable"}


def test_prs_are_cached_for_a_minute(repo, tmp_path, monkeypatch):
    log = fake_gh(tmp_path, monkeypatch, prs=ROLLUP)
    git_changes.prs(repo, "feature")
    git_changes.prs(repo, "feature")
    assert log.read_text().count("pr list") == 1
    real = time.monotonic
    monkeypatch.setattr(git_changes.time, "monotonic", lambda: real() + git_changes.PR_CACHE_S + 1)
    git_changes.prs(repo, "feature")
    assert log.read_text().count("pr list") == 2


# -- the routes ----------------------------------------------------------------------------------------------

async def test_the_routes_answer_for_the_conversations_folder(client, repo, monkeypatch):
    from server.services import settings_service

    async def workspace(_db):
        return repo
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    monkeypatch.setattr(git_changes, "prs", lambda root, branch: {"signed_in": False, "prs": []})
    r = await client.get("/api/v1/conversations/c1/repo-changes")
    assert r.status_code == 200
    body = r.json()["repo"]
    assert body["branch"] == "feature" and {f["path"] for f in body["files"]} == {"a.md", "gone.md"}
    assert body["signed_in"] is False
    d = await client.get("/api/v1/conversations/c1/repo-changes/diff", params={"path": "a.md"})
    assert d.status_code == 200 and d.json()["added"] == 1
    assert (await client.get("/api/v1/conversations/c1/repo-changes/diff", params={"path": "b.md"})).status_code == 404


async def test_a_folder_that_is_not_a_repo_answers_none(client, tmp_path, monkeypatch):
    from server.services import settings_service

    async def workspace(_db):
        return tmp_path
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    r = await client.get("/api/v1/conversations/c1/repo-changes")
    assert r.json() == {"repo": None}
