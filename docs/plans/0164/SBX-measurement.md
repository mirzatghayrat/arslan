# SBX-M: the SBX-2 corpus on the user's Mac

> ③Hands, Claude Opus 5.5 (`claude-opus-5-5`), 2026-10-31.
> - **Source:** the run the user started with `scripts/dev/sbx_m.sh` (`docs/plans/0164/SBX-M-runbook.md`), the measurement in `docs/plans/0164/SBX-sandbox.md` §M.
> - **Contents:** ids, outcomes, counts and versions only. The corpus README forbids raw command arguments, profile text and service output, and those stay on the Mac.
> - **The bases:** **legacy** is `legacy-commands`, today's commands profile. **candidate** is `default-deny`, SBX-2's unused preset. **outside** is `outside-floor`, today's floor outside the sandbox.

## The run

| | |
|---|---|
| Commit | `ef6283b2` (main), no changed files |
| macOS | 26.6.2 (25G83), arm64, Mac16,8 |
| Tools | Python 3.11.15 · git 2.54.0 · node v22.22.3 · npm 10.9.8 · Swift 6.3.1 · Homebrew 7.0.9 · uv 0.11.14 |
| Firewall | off |
| Load | 6 other pytest processes were running at the start |
| Time | the corpus 943 s, the loop 57 s (30 runs) |

## At a glance

- **293 cases:** 293 passed, 0 failed, 0 error, 0 skipped, 0 xfailed.
- **71 kernel gates** (assertions): all passed. The gates are listed below.
- **222 measurement rows:** 119 ok, 2 refused, 80 tool-failed, 10 timeout, 9 not-supplied, 2 boundary-open. A measurement row passes as a pytest case whatever it measured (corpus README, "Reading results"). The outcomes are the result.
- **On the candidate**, 48 rows need a look: 42 tool-failed and 6 timeout. Each is classified below with its card cost. None is boundary-open.
- **The two boundary-open rows** are the hard-link measurement on legacy and outside, today's shipped bases. On the candidate it is refused. ⓪Plan's assessment ([#592 comment](https://github.com/mirzatghayrat/arslan/pull/592#issuecomment-6545067946)) found them a measurement artifact, not a shipped gap; the probe fix is Codex's. This report doesn't analyse it.
- **Listener-refusal loop:** 30 of 30 for each of the three cases:
  - any-declared, where the builder refuses the port exclusion (#570);
  - port-22;
  - proxy.

## Kernel gates (71, all passed)

All are in `tests/server/sbx/test_sbx2_kernel.py`, on the candidate.

| Gate | Cases |
|---|---|
| `test_service_policy_and_reachability`: 15 services × 4 network modes (none, proxy, any-declared, port-22), each refused. The services: `launchd`, `launchservices`, `launchservices-map`, `shortcuts`, `shortcuts-events`, `pasteboard`, `windowserver`, `tcc`, `tcc-system`, `keychain`, `keychain-agent`, `notifications`, `notifications-agent`, `background-network`, `background-network-system` | 60 |
| `test_listener_refusal_and_arslan_port_exclusion` | 3 |
| `test_launch_submission_is_refused` | 1 |
| `test_apple_events_refused_without_contacting_an_app` | 1 |
| `test_device_writes_are_narrow` | 1 |
| `test_posix_ipc_is_confined_to_the_run_prefix` | 1 |
| `test_preference_policy_distinguishes_reads_from_writes` | 1 |
| `test_read_write_and_protected_paths` | 1 |
| `test_same_sandbox_signals_and_pty` | 1 |
| `test_unlisted_unix_socket_is_refused_in_every_network_mode` | 1 |

These gates are SBX-M's part of the card's acceptance line "every denied service in §2 is refused from inside the commands preset … in SBX-M on the user's Mac". They include the security server (`keychain`, `keychain-agent`; card item f) and the daemons that do network work for the caller (`background-network`, `background-network-system`), in every mode.

## Measurement rows (222)

### Outcomes by base

| Base | ok | refused | tool-failed | timeout | not-supplied | boundary-open |
|---|---|---|---|---|---|---|
| legacy | 48 | 0 | 20 | 2 | 3 | 1 |
| candidate | 21 | 2 | 42 | 6 | 3 | 0 |
| outside | 50 | 0 | 18 | 2 | 3 | 1 |

### The compatibility matrix (204 rows)

- **The ids:** each row is `tests/server/sbx/corpus/test_sbx2_corpus.py::test_compatibility_measurement[<probe>-<mode>-<base>]`.
- **Reading a cell:** it shows legacy / candidate / outside.
- **The codes:** FAIL is `tool-failed` and TIME is `timeout`.
- **The empty columns:** the probes that use no network ran in mode `none` only.

| Probe | none | proxy | any-declared |
|---|---|---|---|
| user-lookup | ok / ok / ok | | |
| preference-read | FAIL / FAIL / FAIL | | |
| git-version | ok / ok / ok | | |
| git-local | ok / ok / ok | | |
| git-clone-https | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| git-keychain-helper | ok / FAIL / ok | ok / FAIL / ok | ok / FAIL / ok |
| ssh-remote | FAIL / FAIL / FAIL | FAIL / FAIL / FAIL | FAIL / FAIL / FAIL |
| python-version | ok / ok / ok | | |
| python-compute | ok / ok / ok | | |
| python-venv | ok / ok / ok | | |
| pip-download | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| node-version | ok / ok / ok | | |
| node-script | ok / ok / ok | | |
| node-watch | ok / FAIL / ok | | |
| node-workers | ok / ok / ok | | |
| npm-view | TIME / TIME / TIME | ok / TIME / ok | ok / TIME / ok |
| sdk-path | ok / ok / ok | | |
| swift-version | ok / ok / ok | | |
| swiftc | ok / ok / ok | | |
| swift-package | FAIL / FAIL / FAIL | | |
| brew-version | ok / ok / ok | | |
| brew-prefix | ok / ok / ok | | |
| brew-list | FAIL / FAIL / FAIL | | |
| brew-info | FAIL / FAIL / FAIL | | |
| dns | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| curl-certificate | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| python-certificate | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| git-certificate | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| swift-certificate | FAIL / FAIL / FAIL | FAIL / FAIL / ok | FAIL / FAIL / ok |
| zsh | ok / ok / ok | | |
| bash | ok / ok / ok | | |
| multiprocessing | ok / FAIL / ok | | |
| pty | ok / ok / ok | | |
| tempfile | ok / ok / ok | | |
| mktemp | ok / ok / ok | | |
| mktemp-template | ok / ok / ok | | |
| hardcoded-tmp | ok / FAIL / ok | | |
| darwin-user-temp | FAIL / FAIL / FAIL | | |
| darwin-user-cache | FAIL / FAIL / FAIL | | |
| pip-cache-two-runs | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |
| npm-cache-two-runs | TIME / TIME / TIME | ok / TIME / ok | ok / TIME / ok |
| uv-cache-two-runs | FAIL / FAIL / FAIL | ok / FAIL / ok | ok / FAIL / ok |

In mode `none`, legacy's network cells are today's offline cut (S2a-1): no network on any base, by design. Legacy's proxy and any-declared cells mean its historical online behaviour; it has no proxy (corpus README).

### The other measurement rows (18)

All are `tests/server/sbx/corpus/test_sbx2_corpus.py::<test>[<base>]`.

| Test | legacy | candidate | outside |
|---|---|---|---|
| `test_localhost_dev_server_measurement` | ok | refused | ok |
| `test_hardlink_measurement` | boundary-open | refused | boundary-open |
| `test_background_child_measurement` | ok | ok | ok |
| `test_real_socket_reachability[ssh-agent-…]` | not-supplied | not-supplied | not-supplied |
| `test_real_socket_reachability[gpg-agent-…]` | not-supplied | not-supplied | not-supplied |
| `test_real_socket_reachability[docker-…]` | not-supplied | not-supplied | not-supplied |

- **Localhost dev server:** refused on the candidate. That is the user's decision of 2026-10-30, listening denied for now (card §3).
- **Hard link:** refused on the candidate. On today's shipped bases the row reports boundary-open, which ⓪Plan's assessment (linked above) found a measurement artifact. The card's acceptance line asked for that follow-up before SBX-3 merges; the probe fix is Codex's.
- **Background child:** measures a child's temp access, not the run's cleanup (corpus README).
- **Real agent sockets:** not supplied. The runbook leaves `SBX_SSH_AGENT_SOCKET`, `SBX_GPG_AGENT_SOCKET` and `SBX_DOCKER_SOCKET` to the operator. The stand-in gate (`test_unlisted_unix_socket_is_refused_in_every_network_mode`) passed.

## The candidate's 48 rows, classified

The card asks that every failure on the new profile be listed with its card cost (acceptance, "Compatibility"). It also asks the report to name:
- the services the corpus shows are needed (§2);
- how much of the corpus writes a hardcoded `/tmp` (§1a);
- the tools whose cache can't be redirected (§1c);
- the toolchain that breaks (Risks).

A row lands in one of three classes.

| Class | Rows | Tool-failed | Timeout |
|---|---|---|---|
| A. The same on today's commands profile | 22 | 20 | 2 |
| B. Refused by design on the candidate | 14 | 12 | 2 |
| C. Candidate only, not by design | 12 | 10 | 2 |
| **Total** | **48** | **42** | **6** |

### A. The same on today's commands profile (22)

In these rows legacy fails in the same mode, so the candidate adds no card cost.

- **The offline cut, mode `none`** (12):
  - git-clone-https, pip-download, dns;
  - curl-, python-, git- and swift-certificate;
  - pip-cache-two-runs and uv-cache-two-runs;
  - ssh-remote;
  - npm-view and npm-cache-two-runs, both timeouts.

  There is no network in this mode on any base (S2a-1).
- **Failing on every base, the outside floor included** (6). These rows don't measure the candidate:
  - **swift-package:** consistent with the card's nested-sandbox risk ("SwiftPM starts its own sandbox for manifests, and seatbelt does not nest"; every base here is a seatbelt profile). That card cost exists today.
  - **preference-read:** the card's service probes use names that don't exist (§M), and this row fails on every base, the outside floor included. So tool-failed is what the probe measures as written. The read/write policy itself is asserted by `test_preference_policy_distinguishes_reads_from_writes`, which passed.
  - **brew-list, brew-info, darwin-user-temp, darwin-user-cache:** these fail on the outside floor too. They need a probe fix (Codex) before they can name a cost. Until then the card's "shared Darwin cache" question (Risks) stays open.
- **ssh-remote in proxy and in any-declared** (2): it fails on every base, since the corpus has no authenticated SSH remote. An ssh remote costs a re-run card, as the card states (§2, Risks).
- **swift-certificate in proxy and in any-declared** (2): legacy fails too, and only outside passes. The cost exists on today's commands profile.

### B. Refused by design on the candidate (14)

The card states each cost.

- **Proxy mode's network** (10):
  - git-clone-https, pip-download, dns;
  - curl-, python- and git-certificate;
  - pip-cache-two-runs and uv-cache-two-runs;
  - npm-view and npm-cache-two-runs, both timeouts.

  The reserved proxy port has no listener until SBX-6 (corpus README), and DNS from inside is denied in proxy mode (card §3). The cost: every network command in proxy mode, until SBX-6.
- **git-keychain-helper in none, proxy and any-declared** (3): the security server is refused inside (card item f; the `keychain` and `keychain-agent` gates passed). The cost: an https remote that needs a stored credential costs a re-run card.
- **hardcoded-tmp** (1), card §1a. Of the corpus's temp probes, it is the only one that fails on the candidate alone:
  - tempfile, mktemp and mktemp-template pass;
  - darwin-user-temp fails on every base (class A).

  This is the expected largest source of re-run cards, and `/private/tmp` stays closed without a decision.

### C. Candidate only, not by design (12)

These become allowlist entries or build items, or the cost stays.

- **any-declared's network** (10):
  - dns, git-clone-https, pip-download;
  - curl-, python- and git-certificate;
  - pip-cache-two-runs and uv-cache-two-runs;
  - npm-view and npm-cache-two-runs, both timeouts.

  `dns` fails on the candidate and passes on legacy and outside, and every https row fails with it.
  - **DNS:** the named corpus item for the allowlist's DNS entry is `dns-any-declared-default-deny`. Card §2 lists it as "the DNS service only when network mode is not 'proxy'".
  - **The certificate trust service** (§2 candidate) can't be told apart from DNS in this run, because the https rows fail at name resolution first. Re-measure once a DNS entry exists.
- **node-watch** (1): fails on the candidate only. It is the named corpus item for FSEvents (§2 candidate).
- **multiprocessing** (1): fails on the candidate only, while the IPC gate (`test_posix_ipc_is_confined_to_the_run_prefix`) passes. This run doesn't say which operation the Pool was refused. It is an SBX-3 item (card §1, IPC): either the build half allows it, or the cost stays in the next report.

The system-service allowlist is Codex's, with Astra's review, in a follow-up of at most 50 lines (card ownership table). This report only names the corpus items.

### The caches (§1c)

Every two-run cache row on the candidate fails before it uses its cache: offline in `none`, no proxy in proxy, DNS in any-declared. **So this run doesn't confirm which tools honour the redirection.** Re-measure with the DNS entry.

## Profile hashes

- **715 sandboxed runs:** 305 on the candidate, 205 on legacy, 205 outside. 8 of the candidate's runs use an overriding profile (a test's own port-denial or control text).
- **Exact hashes are per run:** each profile text holds its test's scratch paths. They stay in the run's local JUnit file, and the texts in its local profiles folder; neither is committed.
- A hash per preset with those paths normalised was not computed. The card's "the profile text's hash per preset" is still open.

## Not measured

- **From the corpus README:**
  - real Arslan listener discovery;
  - the run lifecycle, the boot sweep and post-run background cleanup (SBX-3);
  - the final closed Mail, Messages, Safari and Photos paths (SBX-3);
  - cross-preset cache isolation and link attacks (SBX-5);
  - real proxy forwarding and DNS routing (SBX-6);
  - Xcode GUI builds, QUIC, and an authenticated SSH git remote.
- **Not in the corpus:**
  - §M's two listening checks with Codex's rules (#549): no corpus probe yet, and a new kind of probe is Codex's;
  - the real version of the LAN check, which needs a second machine;
  - deny detection through tagged rules in the unified log ("The two numbers", detection).
- **Not reached in this run:**
  - the certificate trust service and cache redirection, both behind DNS on the candidate;
  - the real ssh-agent, `gpg-agent` and Docker sockets, which were not supplied.

## Follow-ups this report names

- **Hard link:** ⓪Plan's assessment ([#592 comment](https://github.com/mirzatghayrat/arslan/pull/592#issuecomment-6545067946)) found the two boundary-open rows a measurement artifact, not a shipped gap. The probe fix is Codex's.
- **Allowlist** (Codex, Astra; at most 50 lines):
  - DNS, from `dns-any-declared-default-deny`;
  - FSEvents, from `node-watch-none-default-deny`;
  - the trust service, after re-measuring with DNS.
- **SBX-3:** `multiprocessing-none-default-deny`. The hardcoded `/tmp` cost stands (§1a).
- **Probe fixes** (Codex), for rows that fail on every base: brew-list, brew-info, darwin-user-temp and darwin-user-cache.
- **The SBX-2 harness's `legacy-commands` adapter** may go now: its DELETE-BY reads "after SBX-M records the historical baseline", and this report records it. It must go before SBX-3 replaces the commands preset.

## Gate 4 follow-up for SBX-8 (Codex, 2026-11-01; Astra decision pending)

`multiprocessing-none-default-deny` is now isolated by
`test_pool_refusal_is_sem_open_outside_the_run_namespace`. On macOS 26.6.2
(25G83), arm64, CPython 3.11.15, stock `multiprocessing.get_context('fork').Pool(2)`
fails at its first `SemLock` allocation. A direct libc call using that same
fresh test-owned name confirms **`sem_open(O_CREAT | O_EXCL)` returns EPERM**.
It fails before worker computation, not at process fork or file access.

With the exact same profile, a test-local change generating semaphore names
inside the existing run namespace lets the Pool map complete (six allocations).
This is a diagnostic control, not a product adapter or a deployed naming hook.
The existing IPC confinement gate still passes. A mutation granting the shared
stock semaphore namespace makes the new refusal test red even though the older
confinement gate stays green; a blanket namespace mutation makes both red.

**Recommendation: option (b), retain the IPC rule and record the cost.** A shared
stock semaphore namespace does not separate runs or protect other processes'
objects. Option (a) needs a reviewed runtime design that gives each supported
process tree run-specific names, including its child processes and libraries;
a service allowlist entry or a blanket IPC grant cannot supply that isolation.
Astra decides whether this compatibility cost is acceptable before SBX-3a moves
commands onto the base. No IPC product rule changes in this follow-up.

**Cost for SBX-8:** Python tools using a stock multiprocessing Pool cannot start
that pool inside the sandbox. The measured user-visible result is a
`PermissionError: [Errno 1] Operation not permitted` traceback and a nonzero
command exit; the model may offer the existing re-run-outside card. Parallel
Python work using semaphore-backed locks/queues is also at risk (inferred from
the shared primitive, not separately measured). Ordinary computation, worker
threads and tools that do not need those IPC objects are not shown to break.

Verification uses pytest with a pinned scratch HOME, a test-owned namespace,
full-path backup restoration and SHA-256 checks. The new diagnosis and existing
IPC gate pass after restoration. This covers the measured fork Pool and syscall,
not spawn/forkserver, all Python versions, a run-name integration, or the other
SBX-3a lifecycle gates. macOS CI run id: pending. This entry preserves the
original report's results; it does not change its historical counts or claim
that the corpus's multiprocessing row now passes.

## Port-22 DNS (Codex, 2026-11-01)

Measured on macOS 26.6.2 (25G83), arm64, OpenSSH 10.3p1 / LibreSSL 3.3.6,
against the candidate before gate 2 added its service grants. The original
pytest logs were retained; the stderr below is copied from those logs, not
reconstructed. Only the hostname and resolved address are replaced by
`<HOST>` and `<RESOLVED_ADDRESS>`. UID 501 is retained as printed.

The exact command was identical in all three stages (the profile changed):

```sh
/usr/bin/sandbox-exec -p '<PROFILE>' /usr/bin/ssh -vv -F /dev/null -o BatchMode=yes -o IdentityAgent=none -o IdentityFile=none -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes -o ConnectTimeout=1 '<HOST>'
```

`<PROFILE>` was the harness's default-deny profile in PORT_22 mode, with the
stage's exact additions below. Harness execution used its scratch HOME and
working folder, DEVNULL stdin and a ten-second process-group timeout. The
measurement ran only through pytest with the outer HOME pinned to
`/private/tmp/arslan-sbx-check-home`. No user name, key, agent or known-hosts
file was supplied. All three SSH processes returned 255.

1. **Original profile, no directory-service grant.** This stops before DNS,
   both with and without the resolver socket:

```text
No user exists for uid 501
```

2. **Add only `com.apple.system.opendirectoryd.libinfo` as an exact test-only
   Mach lookup grant.** This removes the earlier lookup obstacle; without the
   resolver socket, SSH reaches its hostname lookup and is refused:

```text
debug1: OpenSSH_10.3p1, LibreSSL 3.3.6
debug1: Reading configuration data /dev/null
Pseudo-terminal will not be allocated because stdin is not a terminal.
debug1: Authenticator provider $SSH_SK_PROVIDER did not resolve; disabling
debug2: resolving "<HOST>" port 22
ssh: Could not resolve hostname <HOST>: nodename nor servname provided, or not known
```

3. **Hold that directory-service grant constant and add the exact resolver
   socket `/private/var/run/mDNSResponder`.** SSH resolves the name and reaches
   connection setup; it then times out during banner exchange:

```text
debug1: OpenSSH_10.3p1, LibreSSL 3.3.6
debug1: Reading configuration data /dev/null
Pseudo-terminal will not be allocated because stdin is not a terminal.
debug1: Authenticator provider $SSH_SK_PROVIDER did not resolve; disabling
debug2: resolving "<HOST>" port 22
debug1: Connecting to <HOST> [<RESOLVED_ADDRESS>] port 22.
debug2: fd 5 setting O_NONBLOCK
debug1: fd 5 clearing O_NONBLOCK
debug1: Connection established.
debug1: Local version string SSH-2.0-OpenSSH_10.3
Connection timed out during banner exchange
Connection to <RESOLVED_ADDRESS> port 22 timed out
```

This is evidence for the port-22 resolver channel, not a successful SSH login
or authenticated session. The directory-service grant was a test-only
constant in stages 2 and 3 and **is not in the product allowlist**. The stock
user-lookup restriction therefore remains. The separate preference-daemon
case is also unaddressed: the historical preference-read row fails on every
base and does not justify opening that daemon. No new SSH-running test or
product grant is added by this documentation follow-up. CI run id for the
gates branch remains pending.

The D2 transition adds 16 commands any-declared denial cases (15 services and
one listener/unsupported-port-exclusion case), alongside NONE and PROXY and
without PORT_22. DELETE-BY: v0.1.64 when SBX-6's proxy mode lands: remove those
16 transitional cases. Product online-mode wiring remains SBX-3a's work.
