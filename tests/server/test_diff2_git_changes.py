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


GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


def script(path: Path, text: str) -> None:
    """An executable, written, synced and closed before anything runs it (LOAD5)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755)
    try:
        os.write(fd, text.encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    path.chmod(0o755)


def signed_commit(root: Path, signer: Path, tries: int = 5) -> None:
    """LOAD5: on Linux, exec of a file that some process still holds open for writing fails with ETXTBSY. A fork
    elsewhere in the xdist worker can hold the signer's write fd until it execs, so git's run of the signer can fail
    once (#604's run 41229345300, exit 128). Retry only that; any other failure ends the setup with git's stderr."""
    for _ in range(tries):
        done = subprocess.run(["git", "-c", f"gpg.program={signer}", "-c", "user.signingkey=synthetic",
                               "commit", "-qS", "-m", "signed"], cwd=root, capture_output=True, text=True,
                              env={**os.environ, **GIT_ENV})
        if done.returncode == 0:
            return
        if "text file busy" not in done.stderr.lower():
            break
        time.sleep(0.2)
    pytest.fail(f"the signed commit failed in setup (exit {done.returncode}): {done.stderr.strip()}")


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
    # A signed commit on the branch, so `log` would verify it if it were allowed to (gpg.program below marks).
    signer = repo.parent / "signer"
    script(signer, "#!/bin/sh\necho '[GNUPG:] SIG_CREATED D 1 8 00 1 X' >&2\n"
                   "printf -- '-----BEGIN PGP SIGNATURE-----\\nc3lu\\n-----END PGP SIGNATURE-----\\n'\n")
    write(repo, "signed.md", "signed\n")
    git(repo, "add", "-A")
    signed_commit(repo, signer)
    for key, name in (("filter.evil.clean", "clean"), ("filter.evil.smudge", "smudge"), ("filter.evil.process", "process"),
                      ("core.fsmonitor", "fsmonitor"), ("diff.evil.textconv", "textconv"), ("diff.evil.command", "extdiff"),
                      ("diff.external", "external"), ("core.pager", "pager")):
        git(repo, "config", key, f"sh -c 'touch {marks / name}; cat'")
    verifier = repo.parent / "verifier"             # git runs gpg.program as a program, not through a shell
    script(verifier, f"#!/bin/sh\ntouch {marks / 'gpg'}\n")
    git(repo, "config", "gpg.program", str(verifier))
    git(repo, "config", "log.showSignature", "true")
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("* filter=evil diff=evil\n")
    hooks = repo / ".git" / "hooks"
    for hook in ("post-checkout", "pre-commit", "reference-transaction"):
        script(hooks / hook, f"#!/bin/sh\ntouch {marks / hook}\n")
    time.sleep(1.1)                                               # every file's mtime differs from the index's
    write(repo, "a.md", "one\nTWO\nthree\nfour\n")
    s = git_changes.summary(repo, repo)
    git_changes.file_diff(repo, repo, "a.md")
    assert by_path(s)["a.md"]["uncommitted"] is True
    assert sorted(p.name for p in marks.iterdir()) == []


def test_load5_a_busy_signer_is_retried(repo, monkeypatch):
    """LOAD5: ETXTBSY can't be forced on macOS, so git's answer is replayed: busy once, then signed."""
    real, answers = subprocess.run, ["error: cannot run signer: Text file busy\n", ""]

    def run(args, **kw):
        if "commit" not in args:
            return real(args, **kw)
        err = answers.pop(0)
        return subprocess.CompletedProcess(args, 128 if err else 0, "", err)
    monkeypatch.setattr(subprocess, "run", run)
    signed_commit(repo, repo.parent / "signer")
    assert answers == []


def test_load5_any_other_signing_failure_shows_gits_stderr(repo):
    signer = repo.parent / "signer"
    script(signer, "#!/bin/sh\nexit 1\n")
    write(repo, "signed.md", "signed\n")
    git(repo, "add", "-A")
    with pytest.raises(pytest.fail.Exception, match=r"exit 128\).*gpg failed to sign"):
        signed_commit(repo, signer)


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
echo "$(pwd) :: $@" >> {log}
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
    monkeypatch.chdir(repo)                                   # even called from inside the repo, gh runs elsewhere
    out = git_changes.prs("o/r", "feature")
    assert out["signed_in"] is True
    assert [(p["number"], p["state"], p["draft"], p["checks"]) for p in out["prs"]] == [
        (42, "open", False, "passed"), (41, "open", True, "failing"), (40, "merged", False, "running"),
        (39, "closed", False, None)]
    assert out["prs"][3]["url"] is None                                         # only an https link is kept
    calls = [line for line in log.read_text().splitlines() if "pr list" in line]
    assert len(calls) == 1 and "--repo o/r --head feature" in calls[0]
    cwd = Path(calls[0].split(" :: ")[0]).resolve()
    assert repo.resolve() != cwd and repo.resolve() not in cwd.parents                # gh runs no git in the repo


def test_gh_signed_out_or_missing_is_not_signed_in(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, auth_ok=False)
    assert git_changes.prs("o/r", "feature") == {"signed_in": False, "prs": []}
    git_changes._pr_cache.clear()
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    monkeypatch.setattr(git_changes, "merged_path", lambda: str(tmp_path / "nothing"))
    assert git_changes.prs("o/r", "feature") == {"signed_in": False, "prs": []}


def test_a_slow_gh_is_unavailable_not_a_hang(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, sleep=5)
    monkeypatch.setattr(git_changes, "GH_TIMEOUT_S", 0.5)
    assert git_changes.prs("o/r", "feature") == {"signed_in": True, "prs": [], "error": "unavailable"}


def test_prs_are_cached_for_a_minute(repo, tmp_path, monkeypatch):
    log = fake_gh(tmp_path, monkeypatch, prs=ROLLUP)
    git_changes.prs("o/r", "feature")
    git_changes.prs("o/r", "feature")
    assert log.read_text().count("pr list") == 1
    real = time.monotonic
    monkeypatch.setattr(git_changes.time, "monotonic", lambda: real() + git_changes.PR_CACHE_S + 1)
    git_changes.prs("o/r", "feature")
    assert log.read_text().count("pr list") == 2


# -- the routes ----------------------------------------------------------------------------------------------

async def test_the_routes_answer_for_the_conversations_folder(client, repo, monkeypatch):
    from server.services import settings_service

    async def workspace(_db):
        return repo
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    git(repo, "remote", "add", "origin", "git@github.com:someone/proj.git")
    asked = []
    monkeypatch.setattr(git_changes, "prs", lambda slug, branch: asked.append((slug, branch)) or {"signed_in": False, "prs": []})
    r = await client.get("/api/v1/conversations/c1/repo-changes")
    assert r.status_code == 200
    body = r.json()["repo"]
    assert body["branch"] == "feature" and {f["path"] for f in body["files"]} == {"a.md", "gone.md"}
    assert (body["signed_in"], body["github"], asked) == (False, "someone/proj", [("someone/proj", "feature")])
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


async def test_a_repo_not_on_github_asks_gh_nothing(client, repo, monkeypatch):
    from server.services import settings_service

    async def workspace(_db):
        return repo
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    git(repo, "remote", "add", "origin", "https://gitlab.com/someone/proj.git")
    monkeypatch.setattr(git_changes, "prs", lambda *a: pytest.fail("gh asked about a repo not on github.com"))
    body = (await client.get("/api/v1/conversations/c1/repo-changes")).json()["repo"]
    assert (body["github"], body["signed_in"], body["prs"]) == (None, None, [])


@pytest.mark.parametrize("url,slug", [
    ("https://github.com/o/r.git", "o/r"), ("https://github.com/o/r", "o/r"), ("git@github.com:o/r.git", "o/r"),
    ("ssh://git@github.com/o/r.git", "o/r"), ("https://github.com.evil.com/o/r", None), ("https://github.com/o", None),
    ("https://gitlab.com/o/r", None), ("https://github.com/o/r/../x", None)])
def test_only_a_github_com_remote_names_a_repo(repo, url, slug):
    git(repo, "remote", "add", "origin", url)
    assert git_changes.github_repo(repo) == slug


def test_core_worktree_in_the_repos_config_cannot_move_the_work_tree(repo, tmp_path):
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "elsewhere.md").write_text("outside\n")
    git(repo, "config", "core.worktree", str(sibling))
    untracked = git_changes._git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    assert b"elsewhere" not in untracked                                     # git itself looked at the repo
    assert set(by_path(git_changes.summary(repo, repo))) == {"a.md", "gone.md"}


def test_the_environment_cannot_point_git_elsewhere(repo, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))
    assert git_changes.summary(repo, repo)["branch"] == "feature"
    # With the other repo's (empty) index, every tracked file of this one would be "untracked".
    assert git_changes._git(repo, "ls-files", "--others", "--exclude-standard", "-z") == b""


def test_a_dot_git_file_points_at_the_git_folder(repo, tmp_path):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    assert (linked / ".git").is_file()
    write(linked, "b.md", "edited in the worktree\n")
    s = git_changes.summary(linked, linked)
    assert s["branch"] == "side" and by_path(s)["b.md"]["uncommitted"] is True


def test_macos_shim_without_the_command_line_tools_is_no_git(repo, tmp_path, monkeypatch):
    bin_dir = tmp_path / "shimbin"
    bin_dir.mkdir()
    shim = bin_dir / "git"
    marker = tmp_path / "dialog"
    shim.write_text(f"#!/bin/sh\ntouch {marker}\n")
    (bin_dir / "xcode-select").write_text("#!/bin/sh\nexit 2\n")
    for f in (shim, bin_dir / "xcode-select"):
        f.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(git_changes, "_ON_MAC", True)
    monkeypatch.setattr(git_changes, "_SHIM", str(shim))
    with pytest.raises(git_changes.GitError, match="no git"):
        git_changes.summary(repo, repo)
    assert not marker.exists()


async def test_gh_not_answering_is_not_the_repos_error(client, repo, monkeypatch):
    from server.services import settings_service

    async def workspace(_db):
        return repo
    monkeypatch.setattr(settings_service, "workspace_dir", workspace)
    git(repo, "remote", "add", "origin", "https://github.com/someone/proj.git")
    monkeypatch.setattr(git_changes, "prs", lambda *a: {"signed_in": True, "prs": [], "error": "unavailable"})
    body = (await client.get("/api/v1/conversations/c1/repo-changes")).json()["repo"]
    assert "error" not in body and body["prs_error"] == "unavailable" and body["branch"] == "feature"


@pytest.mark.parametrize("rel,ok", [("a.md", True), ("docs/a.md", True), (".github/workflows/ci.yml", True),
                                    ("", False), ("/etc/passwd", False), ("../x", False), ("a/../../x", False),
                                    ("..", False), (".git", False), (".git/config", False), (".git/hooks/pre-commit", False)])
def test_contained_paths(rel, ok):
    assert git_changes._contained(rel) is ok


def test_gh_talks_to_github_com_only(repo, tmp_path, monkeypatch):
    log = tmp_path / "gh.env"
    bin_dir = tmp_path / "envbin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"""#!/bin/sh
echo "host=$GH_HOST repo=$GH_REPO ent=$GH_ENTERPRISE_TOKEN cfg=$GH_CONFIG_DIR :: $@" >> {log}
[ "$1" = auth ] && exit 0
echo '[]'
""")
    (bin_dir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    for key, value in (("GH_HOST", "ghe.example.com"), ("GH_REPO", "evil/repo"), ("GH_ENTERPRISE_TOKEN", "t"),
                       ("GH_CONFIG_DIR", str(tmp_path / "other-config"))):
        monkeypatch.setenv(key, value)
    git_changes.prs("o/r", "feature")
    lines = log.read_text().splitlines()
    assert len(lines) == 2 and all(line.startswith("host=github.com repo= ent= cfg= ::") for line in lines)
