# DIFF2: Changes for a working folder that is a git repo

⑥Helper, 2026-10-31. README row DIFF2 (the user, 2026-10-30: 「我要做的跟Claude 一样的」). The user's picks on the DIFF2-0 mock (2026-10-31, relayed by ④参谋): all three as recommended, and 「借鉴主流agent产品做法，不要过度防御」.

| | |
|---|---|
| Lane | ⑥Helper writes it; ②Main reviews |
| Review and merge | Security surface: the server runs git and gh in the user's folder, gh with the user's GitHub credentials. effort=max review; the user merges both code PRs. This card: docs, ⓪Plan reviews. |
| Migration | None |
| Branches | `claude/0164-diff2-server`, `claude/0164-diff2-web` |
| Depends on | DIFF1's web half (#580) for the reader it reuses |

## What the user picked (DIFF2-0 mock)

1. **The diff covers** everything on the branch since it left the default branch, committed or not, as Claude desktop does.
2. **A PR opens** in the workbench's Browser tab.
3. **A PR row shows** its state and its checks (passed / failing / running).

## What to build

### DIFF2-1 server (`server/services/git_changes.py`, one route)

1. **Which folders.**
   - The conversation's folders that Overview's Changes already knows: the working folder and the project's folder.
   - A folder counts as a repo when it, or a folder above it inside home, holds a `.git` entry, found by name.
   - A folder that isn't a repo keeps DIFF1's per-turn list.
2. **What it answers, per repo:**
   - the branch, or "detached at <short sha>";
   - the default branch: `origin/HEAD`'s target, else a local `main`, else `master`;
   - the commits since the merge base (short sha and subject, at most 50);
   - the changed files since the merge base: made / edited / deleted, each with whether it has uncommitted changes and its +/- counts;
   - capped at 500 files, with "and N more".
3. **One file's diff:** the same `lines` shape as DIFF1 (`checkpoints.diff`): the merge base's blob on the left, the file now on the right. The web half then reuses `DiffReader` with no new rendering. The README row said "git's own diff"; this is the same comparison, drawn by the reader the user already picked. The limits are DIFF1's: 1 MiB, 20,000 lines, text only.
4. **How git runs: it only reads git's object store; Arslan reads the files itself.**
   - **Commands, all plumbing that reads objects or refs:**
     - `rev-parse`;
     - `symbolic-ref`;
     - `merge-base`;
     - `log --no-show-signature --format=…`;
     - `ls-tree -r -z`;
     - `cat-file --batch`;
     - `ls-files --others --exclude-standard -z`, for files not in git yet.
   - **Never `diff` or `status` against the working tree.** The probe (Raw material) showed a filter driver from the repo's own `.git/config` running under plain `git diff`, `--no-textconv` included.
   - **Comparing with the working tree.** Arslan reads each candidate file's bytes and hashes them the way git hashes a blob, then compares that with the tree's blob id. A cache keyed by (path, size, mtime) keeps a large repo cheap between polls. A file that is a symlink, or resolves outside the repo, is listed but not read.
   - **Every call:**
     - `-c core.fsmonitor=false` (the probe: a command-line `-c` overrides the repo's own setting);
     - `-c core.hooksPath=/dev/null`;
     - `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0`;
     - no network;
     - a 10 s timeout;
     - `cwd` = the repo.
   - **Why this is enough without over-defending:**
     - none of these commands run a program that the repo's config names: no filter, textconv, external diff, pager, hook or signature check;
     - a turn writing `.git/config` (HR's "written now, run later" list) therefore can't make this view run anything;
     - the user's own global config (for example git-lfs's filter) isn't run either, because nothing here applies filters.
5. **PRs (gh), only when `gh` is on PATH and signed in:**
   - **The call:** `gh pr list --head <branch> --state all --limit 10 --json number,title,state,isDraft,url,statusCheckRollup`, in the repo.
   - **Environment:** `GH_PROMPT_DISABLED=1`, `GH_NO_UPDATE_NOTIFIER=1`, a 10 s timeout.
   - **Cache:** 60 s per (repo, branch), so the 10 s poll doesn't call GitHub each time.
   - **Checks** reduce to passed / failing / running / none.
   - **Signed out** (`gh auth status` fails) or `gh` missing: the answer says `signed_in: false`, and the view shows the sign-in line. A GitHub connector as the other sign-in path is listed below as an extra.
6. **Outside content.** Branch names, commit subjects, PR titles and file paths come from the repo and GitHub. They're shown in the UI only, as plain text through `isolate()`. Nothing here goes into a model's prompt, so nothing marks a turn.
7. **The route:** `GET /conversations/{id}/repo-changes` (per repo: branch, base, commits, files, PRs, `signed_in`) and `GET /conversations/{id}/repo-changes/diff?repo&path`. 404 for a folder that isn't the conversation's. Read only.

### DIFF2-2 web

- **Overview's Changes:** a repo folder shows the DIFF2-0 layout:
  - the branch → base chip, "N commits ahead", +/- totals;
  - the PR rows (number, title, state pill, checks, ↗);
  - commits, folded;
  - files, each with "uncommitted" where it applies.

  A folder that isn't a repo shows DIFF1's per-turn list under it, as in the mock.
- **Clicking:** a file opens `DiffReader` (a new reader source, `repo-diff`, with the same component). A PR opens in the Browser tab (`WorkDock`'s URL reader).
- **Strings** in `web/src/locales/workbench.ts`, six languages.
- **The four cases from the mock:** signed in, not signed in, nothing changed, and a non-repo folder beside a repo.

## Four lines (`docs/sessions.md` §6)

1. **References:**
   - **Claude desktop's Changes / diff view:** the branch against its base, committed and uncommitted together, the PR and its checks. The user asked for the same.
   - **VS Code's Source Control:** it runs git in the workspace and relies on Workspace Trust for repo config.
   - **GitHub's PR checks rollup** (`statusCheckRollup`).
   - **Not done here:** Arslan has no workspace-trust step, so instead of trusting the repo it doesn't run the parts of git that read programs from config.
   - **Extras listed for the user, not built:**
     - the GitHub connector as a second sign-in path;
     - review comments on the PR;
     - opening a PR or committing from this view (the row says read-only);
     - a per-commit diff;
     - submodules (listed as one entry, not opened).
2. **Raw material:**
   - **No server code runs git today.** `command_policy.py:25` lists `git` and `gh` only for the model's commands; `env_snapshot.py:27` only checks that they're on PATH.
   - **DIFF1's diff and limits** (`checkpoints.py:661-770`) and its route (`runs.py`, `conversation_change_diff`).
   - **`checkpoints._in_git`** (`:239`) is why DIFF1 leaves `.git` alone.
   - **Probe, git 2.54, run in a scratch repo:**
     - `filter.evil.clean` in `.git/config`, with `*.txt filter=evil` in `.git/info/attributes`, ran under `git -c core.fsmonitor=false diff --no-ext-diff --no-textconv HEAD`;
     - `core.fsmonitor` in `.git/config` did not run with `-c core.fsmonitor=false`;
     - `ls-tree`, `cat-file -p` and `ls-files --others` ran neither.
   - **Before DIFF2-1,** a read-only count of the user's working and project folders that are repos, and of how many tracked files the largest has. These go in the PR without paths, and decide the cache's size.
3. **Method:**
   - **Server, failing tests first, on real repos made in `tmp_path`** (git is on CI's runners):
     - branch, base and merge base;
     - committed plus uncommitted changes since the base;
     - made / edited / deleted / untracked;
     - the "uncommitted" flag;
     - detached HEAD;
     - no default branch;
     - a symlink not read;
     - the 500 cap;
     - the cache hit.
   - **Server, the probe kept as a test:** a repo whose `.git/config` holds a filter driver, fsmonitor, a hook and a textconv. The listing and a diff run none of them (marker files stay absent).
   - **gh,** through a fake `gh` on PATH:
     - the four check states;
     - signed out;
     - missing;
     - a timeout;
     - the 60 s cache.
   - **Web:** vitest for the four cases, a file opening `DiffReader` with the repo source, and a PR opening the Browser tab.
   - **Mutants:**
     - a `diff` or `status` call slipped back in (the marker test goes red);
     - the `-c core.fsmonitor=false` dropped;
     - the uncommitted flag inverted;
     - the cache key without mtime.
4. **External evidence:**
   - CI run ids.
   - The marker test red with `git diff` used for the listing.
   - **Real-Mac smoke, for `SMOKE.md`:**
     - Arslan's own repo: branch, PR #, checks;
     - an edit shows as uncommitted;
     - a commit moves it to committed;
     - with gh signed out, the sign-in line.

## Known limits (no decision needed; said in the PR)

- **Filters aren't applied.** A file that git stores through a filter (git-lfs, `eol` conversion) can show as edited when only the filter's form differs. Arslan can't ask git without running the filter. For a git-lfs file, the reader says "stored by Git LFS" instead of a diff of the pointer.
- **Rename detection isn't done:** a rename shows as one deleted and one made file.

## Not here

- DIFF1's per-turn list and undo: unchanged.
- Committing, pushing, merging: read-only view (README row).
