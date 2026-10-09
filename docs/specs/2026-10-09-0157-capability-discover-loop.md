# 0.1.57 — Capabilities that grow: find → check → ask → test → retry

Status: approved 2026-10-09 — all six decisions as recommended (§13). Boards: round 3 "Capabilities-v3", "Capability-Propose",
"Capability-Dossier" (design canvas, approved direction 2026-10-08). Hands v2 (cua-driver) also rides
0.1.57 on its own spec (`2026-10-08-0157-hands-v2.md`); no file of this spec overlaps it.

The user's words (2026-10-08): keep the GitHub search; Arslan should *itself* find GitHub projects,
skills and MCP servers and use them in the user's projects or the capability library; "务必最优解 …
用户体验很重要". The boards: when a step fails for want of a capability, Arslan finds one, checks
it, asks with a card ("装上并重试"), installs it pinned and sandboxed, tests it once, and retries the
step; a rail "Arslan 找到的" keeps what it found for later; each capability has a dossier.

## 0. What exists today (read at `16f71da8`)

- **Switches (0.1.55)**: `capability_list.py:4-9` rows on / off / setup / na; MCP rows from
  `host_allowed`, skill rows from `SkillPack.enabled`; off = not offered to the model
  (`arslan.py:861`, `:1155-1170`; `executors.py:770`).
- **Discovery**: the Discover box (`ToolHubDiscover.tsx:44-50`) → `GET /discovery/search` =
  GitHub repository search, raw query, ranked by stars only (`github_eval.py:106-137`), or
  `POST /discovery/evaluate` (README + two model calls, `discovery_service.py:15-40`). **No MCP
  Registry client, no skill library index** anywhere. Presets: static `CONNECTORS`
  (`server/mcp/catalog.py:22-81`), all but playwright unpinned (`npx -y` / `uvx` latest).
- **Install**: skills via `skill_import.import_skill(ref, path)` — license gate server-side, per-skill
  LICENSE first (`skill_import.py:75-128`), **fetched from the default branch, nothing pinned, no
  checksum** (`:140-155`). MCP via `mcp_service.add_server` (`:50-82`); `MCPServer` has no
  source/version column (`models.py:319-336`).
- **Running**: MCP stdio servers start with a least-privilege *environment* only
  (`spawn_env.py:24-38`: "NOT filesystem/process isolation") — **no seatbelt, no cwd, network
  open** (`session.py:56-76`). The command sandbox (`command_sandbox.py`) confines writes, not the
  network. `run_python` (`code_sandbox.py`) denies the network.
- **Trust**: **no content scan** of skills; `read_skill` is not counted as outside content
  (`untrusted.py:50-61`), so an imported skill's text is read as if Arslan wrote it.
- **Supply-chain red lines** (`tests/server/test_capability_supply_chain.py`): the preset catalog is
  static; `import_skill` takes exactly `(ref, path)`; no search endpoint inside the importer; the
  license gate is server-side. *A discovery layer may exist; nothing goes from "results" to
  "installed" without a person reading the named source.* This spec keeps every one of them.
- **In-chat cards**: non-blocking tool cards (`propose_connect_mcp`, `plan_proposed`); blocking asks
  via the approvals registry (4 kinds, `approvals.py:37-105`, island rule 0.1.55). **No install-and-
  retry path** exists.
- **Outside facts (checked 2026-10-09)**: the official MCP Registry
  (`registry.modelcontextprotocol.io/v0/servers?search=`) answers, lists *every version* as its own
  entry, and gives `packages[]` with `registryType` pypi / npm / nuget / mcpb (+ `fileSha256` for
  mcpb), `runtimeHint` (uvx / npx), `transport`, and `remotes[]` for hosted servers; **no license
  field** (license must come from the source repository). `io.github.haris-musa/excel-mcp-server`
  = pypi `excel-mcp-server` 1.1.2, `uvx`. uv ships `uv-aarch64-apple-darwin.tar.gz` + `.sha256`
  per release (latest 0.12.23); Node LTS = v24.21.0 with `SHASUMS256.txt`. The packaged Arslan ships
  neither uv nor Node.

## 1. The loop

```
need ─▶ find ─▶ check ─▶ ask (card) ─▶ install pinned ─▶ test once ─▶ on ─▶ retry the step
          │        │         │ no                          │ fail
          │        │         └─▶ rail "Arslan 找到的"       └─▶ stays off, says where it failed
          │        └─ license at source · activity · runtime · scan
          └─ official MCP Registry · GitHub · skill libraries
```

- **Arslan only proposes.** Nothing is installed, switched on or updated without the user's click on
  a card that names the exact source, version and license. Search results never reach an installer
  (the red line above).
- **Everything installed is pinned** (version + checksum) and **runs sandboxed** (§5).
- **A test decides "on"**, not the install (§6).

## 2. Finding (P1)

One backend, `capability_search.search(need, kinds)`, used by the model (tool `find_capability`)
and by the page (Discover). Sources, queried in parallel, each with its own timeout (8 s) and cache
(1 h per normalised query):

| Source | What | Kind |
|---|---|---|
| Official MCP Registry | `/v0/servers?search=` — keep the newest version per `name`; pypi / npm / mcpb packages, remotes | MCP server |
| GitHub | repository search with qualifiers (`topic:mcp-server`, `topic:claude-skills`/`agent-skills`, plain) — stars, pushed date, license from the API | MCP server / skill / project |
| Skill libraries | a static, reviewed list in the repository (`anthropics/skills` first), indexed by SKILL.md front matter | skill |

Every candidate carries: kind, name, one-line what-it-does, source URL, version, **license as read
from the source** (the repository's LICENSE at the version's commit/tag; per-skill LICENSE for
skills; PyPI/npm metadata is never the basis), stars + last commit (with the date it was checked),
**how it would run** (pypi→uv, npm→Node, mcpb, remote, skill, or "not here" with the reason: nuget,
docker, Windows-only), what it needs (keys marked secret, folders, network). Ranking is the model's
job in a conversation (it reads ≤ 8 candidates); the page orders by fit to the words, then license
usable, then activity.

**The model's tool** `find_capability(need)` returns those candidates as data (outside content,
`counts_as_external`). It is offered to the main assistant when the turn has hit a wall; it never
installs.

**Licenses**: usable = the existing allowlist (`skill_import.py:43-44`). Proprietary (e.g. the
`anthropics/skills` docx/pdf/pptx/xlsx skills) → "只看思路": readable as reference, never installed.
Unknown (no LICENSE at source) → shown, not installable.

## 3. Asking (P3)

### 3.1 In a conversation
When a step fails for want of a capability (a tool says it cannot, or the model concludes it lacks
one), the model may call `find_capability`, pick one, and call `propose_capability(candidate_id,
why, retry)`. That raises the card from the board (AskCard): what it does · source · license (with
"看的是仓库里的 LICENSE 文件") · how it runs (sandbox, network yes/no, which folders) · scan · what it
needs from you (a key → an inline secret field). Buttons: **不用了 (esc)** · 看详情 · **装上并重试
(⌘⏎)**. Under it: "装好先测一次，不通过就不打开。以后在 能力 › 我的能力 随时关掉。"

It is a **blocking ask in the turn** (new approvals kind `capability`), so that after install + test
the tool result goes back to the model and it retries the step in the same turn. The island may
show it but **may not answer it** ("Open in Arslan", the 0.1.55 rule for risky steps). Declined or
timed out → recorded as found (§4), the turn goes on without it.

### 3.2 In a background job
Jobs cannot wait on a card. A job that hits the wall records the gap and the best candidate on the
rail (§4) and says so in its result ("找到一个可能有用的能力：…，在 能力 › Arslan 找到的").

## 4. "Arslan 找到的" (P4)

A rail on the Capabilities page (board Capabilities-v3, right), each entry: **why it looked** (the
failed step, a project level, …), **what it found**, **license**, 看看 → dossier. Entries come from:

1. a declined or timed-out in-chat proposal, and job gaps (§3.2);
2. **a project level becoming current** (0.1.56 levels): one router-model call per level start —
   "does this level need something Arslan cannot do yet?" (yes/no + a need phrase); on yes, a search
   (§2), the best usable candidate goes on the rail;
3. not in 0.1.57: habits ("you use Things") — needs a source of habits we do not have yet.

Rail entries are **never notifications and never Inbox items** (Inbox = what waits for a decision;
these are optional). A count shows on the Capabilities nav item. An entry goes away when installed,
dismissed, or after 30 days.

## 5. Installing: pinned, sandboxed (P2)

### 5.1 Runtimes
Arslan keeps its own pinned runtimes under `data_dir/runtimes/`: **uv** (for pypi servers) and
**Node** (for npm servers), each pinned in code by version + SHA-256, downloaded on first need from
the official release URL, verified, never taken from PATH for installs. The card says it when a
download is part of the install ("要 uv：Arslan 下载固定版本放进自己的目录，约 20 MB，不用你装").

### 5.2 Pinning
- **pypi**: `uv` resolves `package==version` into a lock with hashes (`--generate-hashes`) inside
  `data_dir/capabilities/<id>/`; installs from the lock; the dossier keeps the lock's SHA-256.
- **npm**: `npm ci` against a lock produced at install (`--package-lock-only`, integrity hashes), in
  the same folder; lock SHA-256 kept.
- **mcpb**: download, verify the registry's `fileSha256`, unpack into the folder.
- **remote**: nothing to install; the URL and the host are recorded; data goes to that host (said on
  the card).
- **skills**: imported at the **commit SHA** the dossier names (not the default branch); SHA-256 of
  every fetched file kept. `import_skill(ref, path)` keeps its signature — `ref` gains an optional
  `@sha`.

### 5.3 Sandbox for local MCP servers
Every local server Arslan installs starts under a seatbelt profile (built like `command_sandbox`,
real paths, JSON-quoted):
- read + write: its own folder and a temp dir; **read + write: only the folders granted to it**
  (granted at install from the failed step — "这次是 ~/Downloads" — changeable in the dossier);
- read-only: system and runtime paths it needs; **no read of the home folder otherwise**, and the
  protected paths of `command_sandbox` stay closed;
- **network: denied** unless the candidate declares it needs the network (shown on the card as
  "要联网"); seatbelt cannot limit to one host, so "要联网" means any host, and the card says so.

Servers the user adds by hand (Settings / presets) keep today's behaviour in 0.1.57; moving them
under the sandbox is a separate decision (§13).

### 5.4 Data
Migration **0064**: table `capability_sources` (id, kind skill/mcp, name, source_url, registry_name,
version, commit_sha, artifact_sha256, lock_sha256, license_spdx, license_path, stars, pushed_at,
checked_at, runtime, needs JSON (keys, network, folders), grants JSON, scan JSON, test JSON, state
proposed/installed/failed/removed, mcp_server_id / skill_pack_key, created_at) and table
`capability_finds` (id, need, why kind failed_step/job/project_level, conversation_id, project_id,
level_id, candidate JSON, state open/dismissed/installed, created_at). `projects.version` and the
existing MCP/skill tables are untouched except `skill_packs.source_id` (nullable).

## 6. Checking and testing (P3)

**Scan** (deterministic, before the card; result shown honestly as "查了已知的危险写法，不能证明
安全，所以在沙箱里跑"):
- skills: hidden-instruction patterns (instructions to ignore the user / exfiltrate / run commands),
  invisible Unicode, long base64 blobs, URLs in instructions, scripts calling the network or
  `subprocess`/`os.system`, destructive shell (`rm -rf`, `curl | sh`);
- packages: the same patterns over the installed source files (Python / JS), plus install-time hooks
  (`postinstall`, setup scripts that fetch).
A finding is shown on the card and in the dossier; a "high" finding blocks install (the user sees
why).

**Test once** before the switch goes on: start in the sandbox, `initialize`, `tools/list` within
30 s, at least one tool, and — when the proposal named the tool the retry needs — that tool present.
Skills: parse + scan. Pass → switch on, the tool result says what it can now do, the model retries.
Fail → the switch stays off, the card says where it stopped ("启动了，但没有列出工具"), the
dossier keeps the log tail. The retry itself is the real proof; if it fails, the turn says so and
the capability stays on (switchable) — Arslan does not remove things by itself.

Imported skills' text is from now on **outside content** (`counts_as_external` gains `read_skill`
for skills whose source is not Arslan): reading one counts like reading a web page for the rules that
follow outside content.

## 7. The dossier (P4)

Board Capability-Dossier: license (file and commit it was read from) · activity (stars, last commit,
checked date) · scan · how it runs · what it needs (keys, folders, network) · version (pinned +
checksum) · after install (test result). Actions: 收藏, 加进能力库 (install), 用进项目 ⌄, and for
installed ones: change folders, switch, remove (moves its folder to Trash).

**Updates**: "看看有没有新版本" (on request, and on the dossier open at most daily) compares the
registry / repository; a newer version shows **what changed** (release notes, or the commit list
between the two tags) and installs only on click, through the same scan + test; the old version
stays until the new one passes.

## 8. Using it in a project (P4)

"用进项目 ⌄" on a candidate, three ways (board): **当资料** — its README and description go into
the project's materials; **当依赖** — opens a project conversation with the request typed ("把
openpyxl 加进这个项目的依赖"), not sent, so the normal approvals apply; **当能力** — install (§5),
as everywhere else.

## 9. Discover page (P1/P4)

Keep the box; it now searches by what you want done across the three sources (§2), filters 全部 /
技能 / MCP 服务 / 开源项目, each result with license, activity, scan state when known and the
three actions. The rail on the right (§4). Tabs and the switch list from 0.1.55 stay.

## 10. Not changed

Existing presets, existing installed MCP servers and skills keep working as today. The supply-chain
red lines stay (the search code lives in a new module; the importer still takes an explicit ref).

## 11. Small fixes on the way

- Presets: pin versions for the `npx -y`/`uvx` presets (today latest at every start).
- `server-github` / `server-brave-search` presets point at deprecated npm packages: replace with the
  maintained ones or drop (checked at implementation, license at source).
- Rate limit: GitHub search unauthenticated is 10/min — cache + say "set a GitHub token" once.

## 12. Phases (one PR)

- **P1 Finding**: `capability_search` (registry client, GitHub qualifiers, skill-library index),
  license-at-source for candidates, `find_capability` tool, Discover box rewired. No installs.
- **P2 Installing**: runtimes (uv, Node) pinned + verified; pinned installs (pypi, npm, mcpb, remote,
  skills at SHA); sandboxed launch with grants; migration 0064; preset pins.
- **P3 Ask and test**: scan; `propose_capability` + approvals kind `capability` (island: open in
  Arslan); install → test → tool result → retry; jobs record gaps.
- **P4 Rail, dossier, projects, updates**: "Arslan 找到的" (from declines, jobs, level starts), dossier
  page, use in project, update check with what changed, nav count.

## 13. Decisions (user, 2026-10-09: "都按你的建议" — each as recommended)

1. **Runtimes**: download pinned **uv and Node** on first need (recommended — most registry servers
   are pypi or npm), or uv only (npm servers then show "要 Node").
2. **Network for installed local servers**: denied unless the server declares it (recommended), or
   open like hand-added servers today.
3. **Proactive sources in 0.1.57**: failed steps + jobs + **project level start** (recommended; one
   small router call per level start), or failed steps + jobs only.
4. **Where found items live**: Capabilities rail + nav count, not Inbox, no notification
   (recommended), or also in Inbox.
5. **Imported skills as outside content** from now on (recommended; it also applies to skills
   already imported, which then count like a web page when read).
6. **Hand-added MCP servers under the same sandbox**: not in 0.1.57 (recommended — it could break
   servers people already rely on; measure first), or now.

## 14. Acceptance

- No search result reaches an installer; every install follows a click on a card naming source,
  version, license (tests over the code paths, plus the existing red-line tests unchanged).
- Every install is pinned (version + checksum recorded) and reinstalls bit-for-bit from the lock.
- An installed local server cannot read `~/Documents` unless granted, and cannot reach the network
  unless declared (measured with a probe server under the profile).
- A failing test leaves the switch off; a passing one switches on and the turn retries the step.
- A proprietary or unknown license is never installable.
- No find produces a notification or an Inbox item.
- Real Mac: ask Arslan to check formulas in an .xlsx → it proposes excel-mcp-server (or the best at
  the time) → install with uv downloaded → test → retry reads the formula.

## 15. Model cost

`find_capability` / `propose_capability` run inside the user's own turn (no extra call). One router
call per project level start (§4.2). No model call for scanning or testing.

## 16. As built: where the implementation differs (flagged, not waiting)

1. **The registry's search is slow** (13–60 s per query, measured 2026-10-09). It still runs, with
   a 30 s budget and a 6 h cache, and two faster paths feed the same results: GitHub repositories
   tagged as MCP servers are looked up in the registry **by name** (`io.github.<owner>/<repo>`,
   ≈0.9 s), and licenses/stars for many registry entries come from **one** GitHub search with
   `repo:` qualifiers. One ranking score (fit, usable license, runs here, installable, popularity,
   staleness) replaced "fit first", which buried the right server under small repositories.
2. **Skill libraries are read from one archive** (codeload, its pax header names the commit)
   instead of the GitHub API (60 calls an hour without a token; the per-file way spent ~40).
3. **A package's license is read from its repository's LICENSE at HEAD** (raw file, recognised by
   its wording), not at the version's tag — the registry does not say which commit a version is.
4. **The scan reads a package's own files**, not its dependencies (HTTP clients there phone home by
   design). Rules were checked against excel-mcp-server 1.1.2 and all 20 anthropics/skills; one
   false alarm found and fixed.
5. **Partial: mcpb bundles of type `python` are not installed** (they need their own interpreter
   set-up); `node` and `binary` bundles are. Said in code and here.
6. **The card is answered only in the Arslan window that asked** — not the Inbox, the phone or the
   island (it may carry a key). Declining works from anywhere.
7. **Network for an installed local server** is allowed only when it needs a secret key (the
   registry declares no network need; a secret key means a remote service). The card says so.
8. **Decision 5 is narrow**: `read_skill` on an imported skill wraps it and marks the turn as having
   read outside content. Other tools that return `external: True` (Hands) are unchanged — that is
   the Hands session's area.
9. **Updates link to GitHub's compare of `v<old>...v<new>`** for "what changed" (release notes are
   not in the registry); the update itself installs beside, scans, tests, and only then removes the
   old one.
10. **"收藏" on a candidate** still uses the existing evaluate-and-save path (GitHub repositories).
