# SBX-2 corpus

The candidate is an **unused preset**, not a claim that the product is already
sandboxed this way. SBX-M measures it before SBX-3 connects any entry point.
The initial Mach-service and Unix-socket allowlists are empty. No service has
measurement evidence yet; additions require a named corpus result and Astra review.
Preference reads are an allowed operation, but no cfprefsd lookup is granted.

Run on macOS CI first. After its results have been reviewed, the SBX-M operator
runs on the user's Mac from the repository root:

```sh
sbx_output="$(mktemp -d "${TMPDIR:-/tmp}/arslan-sbx-evidence.XXXXXX")"
.venv/bin/pytest tests/server/sbx -m sbx_mac -q -rfEs \
  --junitxml="$sbx_output/results.xml" --sbx-artifacts="$sbx_output/profiles"
```

The existing CI command (`pytest tests/ -m macos`) selects the SBX-2 corpus and
the two compile checks in `test_sbx2_tcp_ports.py`.
The platform skip applies only off macOS. A missing or nested Seatbelt, a syntax
error, or a broken Python interpreter **fails** on macOS. Do not change this to
an availability skip. The `sbx_mac` corpus has 293 cases: 71 assertion gates and
222 measurement rows. With two compile checks and the existing 69, those cases
total 364, as set by PR #576. Widening the port sample within the same
two compile cases does not change that count.

SBX-3p adds 56 commands cases, making the macOS selection 420. They strictly
xfail with `raises=AssertionError` until `commands` is registered in the harness's
`BUILT_BASES` adapter table. A separate Claude CI change must raise `EXPECTED`
from 364 to 420; the count-mirror guard fails until then. Once SBX-3a registers
its real commands adapter, these cases must run with zero skips and zero xfails.

The compile checks compare libsandbox bytecode with/without each deny over the
fixed regression ports plus every 65th port starting at 1: 1,018 ports for proxy
and 1,017 for port-22. The regression ports include the original dropped ports
and the proxy port itself. CI publishes the macOS pytest step's total duration,
not per-case timings or its JUnit file. Report that total with the CI run id;
it includes the whole selected suite and does not isolate compilation cost.
They exercise the exact proxy and port-22 allow pairs; removing either mode's
port allow can lose denies. They do not apply a sandbox or replace runtime gates.
The portable check compares the complete network allow list, including any new
filter spelling or bare grant, and requires all TCP port denies to follow it.
Port-22 rejects an exclusion of port 22 before generating a profile, because its
non-localhost `*:22` grant also covers mapped addresses that `localhost:22` misses.

## Reading results

Kernel tests assert the policy and actual effects; compatibility rows measure
card costs and may pass as pytest rows while reporting `tool-failed`, `timeout`,
`tool-unavailable`, `not-supplied`, or `boundary-open`. Such a row is **not** a
successful compatibility or security result. The terminal summary and JUnit
properties preserve those distinctions. Inspect them before approving SBX-M.
A hard-link `boundary-open` requires a follow-up before SBX-3 merges. That row
now targets scratch Arslan data and first requires a direct write to be denied
under the exact same profile. The outside-floor profile uses scratch HOME too.
An already-writable target fails this precondition instead of reporting an
invented boundary crossing; the old report's historical rows remain unchanged.

Every row records macOS release/build and architecture. Its `executions` JUnit
property is a JSON list with one entry per sandboxed subprocess launched by the
harness (unsandboxed host-side setup and cleanup checks are not entries): sequence number,
probe label, base, configured network mode, whether the profile was overridden,
exact profile SHA-256, completion/timeout result and return code. The test id plus
sequence identifies the invocation. This includes the fixture smoke probe,
historical controls, custom port-denial profiles and every mode in a multi-mode
test. The mode is adapter context; an explicit override's exact text is authoritative.
A completed subprocess is not necessarily an accepted operation; interpret its
return code together with the named probe's assertions or measurement outcome.
Unexecuted optional/tool-unavailable probes have no execution entry beyond smoke.
Version probes also record tool versions. The optional artifact directory saves
each captured profile text under its SHA-256, never a profile regenerated at
teardown. These files contain local paths and must not be committed. The report
records ids, versions, hashes, outcomes, gaps and card costs only; never raw
command arguments, profile text or service output.

`harness.py` selects `legacy-commands`, `default-deny`, or `outside-floor` by
name. Legacy uses today's real command builder and its writable/protected roots
with scratch HOME/TMPDIR, including the parent's cached `tempfile` root. The real
builder still includes its historical shared temp roots and Darwin user directory;
the legacy comparison is not confined to scratch. Proxy-mode rows on
the historical profiles mean their historical online behavior; they have no
proxy. On the candidate, the reserved proxy port has **no listener**: this tests
compatibility with the restriction, not end-to-end proxy forwarding (SBX-6).

The commands gate fails explicitly before any smoke or probe while its adapter
is absent. CI already distinguishes strict xfails from skips (#542). The adapter
table is the only registration point: SBX-3a adds a callable using its real product
preset and the harness's scratch HOME/TMPDIR, work/temp paths, protected fixture,
IPC prefix, network mode and supplied listener-port exclusions. It must not return
the candidate profile. Unknown adapters raise; there is no historical fallback.

`test_sbx3_commands.py` reuses the SBX-2 service, IPC, device, pty/signal,
filesystem, Unix-socket, Apple Event and loopback gates. It adds scratch closed-app
paths (including symlink aliases), offline loopback refusal, six shared/other-run
temp locations and two hard-link boundaries, with a workspace-link positive
control. The IPC test is a confinement check, not a claim that SBX-M's failed
Python Pool row now works. Hardcoded temp writes remain an expected refusal.
Run creation/lifetime/boot sweep and classifier helpers belong to SBX-3a; cache
isolation and proxy forwarding belong to SBX-5p/6p. These tests do not implement
those surfaces or resolve the postponed localhost-server decision.

## Safety and coverage

- Children get a clean environment, scratch HOME, private TMPDIR, fake secret,
  scratch data path, disabled git prompting and no inherited credential/proxy
  variables. Each subprocess group is killed and reaped on completion or timeout.
- Service probes query the kernel policy and request/release a send right. They
  send no service messages. A failed lookup alone cannot prove a denial: the
  test also requires a kernel deny and an allowed-policy historical control.
  Pasteboard and screen probes never read content or capture a screen.
- Only the candidate attempts launch-job and preference writes. Unique probe
  domains/labels are removed in `finally`, including after a timeout. The job
  runs only `true`, with neither RunAtLoad nor KeepAlive. Baselines perform no
  daemon-mediated writes. The credential helper uses a nonexistent `.invalid`
  host, no prompt, and discarded output; no real keychain item is requested.
- Git, Python, node, Swift, brew, HTTPS/DNS, IPC, ptys, temp paths and two cache
  runs are represented. Remote fetches are small public fixtures, not model calls.
  Failed network/toolchain probes remain visible measurements, never skips.
- Loopback gates use test-owned listeners. Proxy and port-22 refuse a supplied
  Arslan-port stand-in over IPv4 and IPv4-mapped IPv6; any-declared rejects the
  requested port exclusion before generating a profile. All three cases still
  reject IPv4/IPv6 wildcard and loopback binds plus implicit listens. Every
  candidate network mode denies binds/listens. The separate localhost dev-server
  measurement still binds, serves and fetches under each base; it records `ok`,
  `refused` (expected under the candidate), or `tool-failed`, without making
  localhost server availability a pass gate. CI run 41002402918 measured that
  Seatbelt's localhost bind filter also permits wildcard binds. The card's §3
  localhost dev-server promise is deferred by the user's decision; restoring it
  needs a card decision before SBX-3 wires the preset (for example a brokered
  listener or another approach). Unix-socket gates use a controlled listener.
  For optional real connect-only measurements, the operator may supply
  `SBX_SSH_AGENT_SOCKET`, `SBX_GPG_AGENT_SOCKET`, and `SBX_DOCKER_SOCKET` explicitly.
  No directories are searched and no protocol bytes are sent. Missing inputs
  are reported as `not-supplied`, not as a refusal.
- New service names must be measured, not inferred from a missing service on a
  headless runner. The service-name list is representative, not an inventory of
  every alias on every supported OS. The default-deny boundary covers unlisted
  names; actual launch submission also tests the inherited launchd channel.

Still outside this candidate's measurements: real Arslan listener discovery,
Run lifecycle/boot sweep and post-run background cleanup (SBX-3), the final closed
Mail/Messages/Safari/Photos paths (SBX-3), cross-preset cache isolation and link
attacks (SBX-5), real proxy forwarding/DNS routing (SBX-6), Xcode GUI, QUIC, and
an authenticated SSH git remote. The background row measures child temp access,
not Run cleanup. Device tests exercise selected nodes, not a syscall trace of
all toolchains. These gaps must stay in the SBX-M report.

DELETE-BY: v0.1.64 after SBX-M records the historical baseline, before SBX-3
replaces that preset: remove the `legacy-commands` adapter and its parameters.
The outside floor remains a comparison because it remains a product policy.

ABI references (facts only, no copied implementation or profile):
[Apple launchd bootstrap declarations](https://github.com/apple-oss-distributions/launchd/blob/main/liblaunch/bootstrap_priv.h)
and [WebKit's Sandbox SPI declarations](https://github.com/WebKit/WebKit/blob/main/Source/WTF/wtf/spi/darwin/SandboxSPI.h).
Policy filter syntax was checked against the installed macOS profiles; none is
included or copied wholesale into the candidate.
