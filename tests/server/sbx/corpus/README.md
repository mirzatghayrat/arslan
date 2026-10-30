# SBX-2 corpus

The candidate is an **unused preset**, not a claim that the product is already
sandboxed this way. SBX-M measures it before SBX-3 connects any entry point.
The initial Mach-service and Unix-socket allowlists are empty. No service has
measurement evidence yet; additions require a named corpus result and Astra review.
Preference reads are an allowed operation, but no cfprefsd lookup is granted.

Run on macOS CI first. After its results have been reviewed, the SBX-M operator
runs on the user's Mac from the repository root:

```sh
.venv/bin/pytest tests/server/sbx -m sbx_mac -q -rfEs \
  --junitxml=sbx-results.xml --sbx-artifacts=sbx-profile-texts
```

The existing CI command (`pytest tests/ -m macos`) selects the same SBX-2 tests.
The platform skip applies only off macOS. A missing or nested Seatbelt, a syntax
error, or a broken Python interpreter **fails** on macOS. Do not change this to
an availability skip. The current set adds 290 cases: 71 assertion gates and
219 measurement rows. Together with the existing 69, the job must expect 359.
The workflow's exact-count update belongs to the separate non-Codex CI PR;
this branch intentionally leaves its mirror check failing until that change lands.

## Reading results

Kernel tests assert the policy and actual effects; compatibility rows measure
card costs and may pass as pytest rows while reporting `tool-failed`, `timeout`,
`tool-unavailable`, `not-supplied`, or `boundary-open`. Such a row is **not** a
successful compatibility or security result. The terminal summary and JUnit
properties preserve those distinctions. Inspect them before approving SBX-M.
A hard-link `boundary-open` requires a follow-up before SBX-3 merges.

Every executed row records its base name, network mode, exact profile SHA-256,
macOS release/build and architecture. Version probes also record tool versions.
The optional artifact directory saves the exact text under its SHA-256. These
files contain scratch paths and must not be committed. The report records ids,
versions, hashes, outcomes, gaps and card costs only; never raw service output.

`harness.py` selects `legacy-commands`, `default-deny`, or `outside-floor` by
name. Legacy uses today's real command builder and its writable/protected roots
with scratch HOME/TMPDIR, rather than a reconstructed policy. Proxy-mode rows on
the historical profiles mean their historical online behavior; they have no
proxy. On the candidate, the reserved proxy port has **no listener**: this tests
compatibility with the restriction, not end-to-end proxy forwarding (SBX-6).

Future p PRs add probe parameters and the surface's profile adapter. Their base
name remains outside `BUILT_BASES`, so `base_parameter()` applies
`xfail(strict=True)`. The corresponding a PR adds its name to `BUILT_BASES` and
must show zero skips and zero xfails on its own macOS job. An unknown adapter
raises; it never silently uses the candidate or a historical profile.

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
- Loopback gates use test-owned listeners, deny a supplied Arslan-port stand-in,
  and reject all-interface binds. Unix-socket gates use a controlled listener.
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
