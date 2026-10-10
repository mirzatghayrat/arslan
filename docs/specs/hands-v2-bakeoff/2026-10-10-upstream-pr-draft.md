# Draft: pull request to lahfir/agent-desktop (not opened)

Waits for the user's OK (it is opened under their GitHub account). Branch on the fork:
`fix/stale-launchservices-record`, based on upstream `main` (`9d7ba42`); the same change as our fork's `c0aa285`
without Arslan's change notes.

---

**Title:** fix(macos): leave an application whose process is gone out of the complete inventory

## Problem

LaunchServices can keep a record of an application whose process no longer exists. We saw one on macOS 26.6:
Preview listed by `NSWorkspace.runningApplications` with a pid that `kill(pid, 0)` reports as gone and a null
launch time, until Preview was launched again (that cleared it). The workspace source resolves each listed app's process
identity; for this one it gets `Ok(None)` and returns the retryable "Selected application exited during inventory".
`stabilize_apps_until` retries until its deadline, so **every** complete inventory fails and `list-apps` answers
`TIMEOUT` ("macOS application inventory did not stabilize", `attempts == churn_events`) for as long as the record
stays — one stale record hides every running app.

## Change

In the complete inventory (`skip_cross_uid`), an application whose process is gone is left out, as an
application owned by another user already is. A scoped lookup still reports it (unchanged). This follows main's
handling of process-less applications (pid ≤ 0), which are left out of the workspace snapshot.

With #110's skipped-records contract, the natural form is to report this record as skipped rather than drop it
silently; happy to rework onto that branch if you prefer.

## Tests

- `complete_inventory_skips_an_app_whose_process_is_gone`: a snapshot with Finder, a record whose identity
  resolves to `None` (launch time null), and Safari gives Finder and Safari. Fails without the change.
- `scoped_lookup_still_reports_a_selected_app_whose_process_is_gone`: the scoped path still errors.

`cargo fmt --all -- --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test --lib --workspace` (2104
passed) and `cargo test -p agent-desktop` (203 passed, 3 ignored) on macOS 26.6. The E2E harness was not run.
Reproducing the record on purpose did not work (killing an app mid-launch leaves none), so the evidence is the
unit test plus the incident above.
