# W11 — security boundary checkpoint (not complete)

Starting point: `c13668f6`. No real credentials, account requests, installed app
replacement or publication were used for this work.

## Closed legacy paths

The previous command proxy attached GitHub Basic credentials to any allowed
repository remote. Credentials are now bound to the exact GitHub service hosts;
client Authorization/Proxy-Authorization and Host headers are removed, and the
upstream Host is reconstructed. CONNECT parsing is strict, HTTPS port only;
malformed request lines and folded headers are rejected. Client tasks have a
deadline and are cancelled/closed with the proxy. Temporary TLS leaf files are
removed after loading.

More importantly, production network commands no longer acquire `gh auth token`
or give the in-process proxy a credential. The proxy is not an authenticated,
OS-isolated broker and must not be described as one. There is no configuration
escape hatch that re-enables automatic credential acquisition. Public,
unauthenticated transport remains implemented; private repositories and writes
requiring account authentication are unavailable pending the broker gate.

Commands previously had unrestricted filesystem access despite network isolation.
They now use default-deny Seatbelt: host-selected workspace and temporary files,
read-only runtime directories, selected executable/trusted git helpers, and an
explicit public CA file exception. Other network access, host IPC and external
file contents/writes are not granted. Global/system git configuration is disabled.
Dynamic-loader environment overrides are rejected. Local command calls currently
receive only their temporary workspace; broad user-folder command access is not
implicitly restored. Future project grants must bind an explicit host-selected
workspace before allowing project file operations.

## Evidence and limits

Loopback TLS fixtures assert GitHub-bound synthetic authentication, no credentials
on an allowed non-GitHub remote, canonical Host, port rejection and client cleanup.
No public endpoint or genuine token was contacted. An actual macOS command test
read an allowed workspace file, denied an outside canary and a symlink to it, and
denied overwriting the outside file. The added marked test and CI population were
updated together (41 to 42); this is not a new full Linux measurement.

The command workflow regression passed 58 tests; the actual macOS selection
passed all 42 tests with zero skips in 16.07 seconds. Production frontend build
passed (existing large-chunk warning remains). These checks do not certify
authenticated network operations or a release candidate.

## Credential-free approval checkpoint

Migration 0053 adds disconnected-by-default connection metadata and one-action
grants. No secret value or filesystem locator is accepted as a broker reference;
the broker reference is also omitted from presentation payloads. There is no
production activation endpoint, grant-minting model tool or authenticated ASC
connector in this checkpoint.

Trusted host approval storage binds owner, connection version, task attempt and
spec revision, project version, complete App-binding hash, prepared action version
and exact intent/diff hash. Confirmation checks the hashes from the displayed
snapshot. Grants expire within 15 minutes, are revocable and single-use. ASC action
admission rechecks the binding and consumes approval in the same SQLite transaction
as the durable action-start record. Submission, publication, tax and guessed privacy
actions cannot obtain a grant. Backup restoration revokes grants and invalidates
connection attestations. This is a storage/admission primitive, not a user approval
UI or a substitute for the pending isolated broker.

The approval, task-repository, migration-runner and task-service selection passed
113 tests (14.76 seconds), including rollback, concurrent single-use admission,
restore invalidation, forged references and high-impact-action refusal. One
existing Starlette/httpx deprecation warning remains. These are synthetic tests.

This is NOT W11 completion. Trusted confirmation UI and broker integration are
still unavailable. No independent security
review, authenticated broker identity, Keychain ACL, debugger isolation, or real
ASC credential acceptance has been established. ASC credential-backed actions
must remain disabled until those gates pass. Synthetic tests and file permissions
do not stand in for those guarantees.
