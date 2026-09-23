# Isolated layout fixture

Run the existing frontend dev server from `web`, then open
`/acceptance/clean-layout.html` (Chinese) or append `?lang=en`.
Use a separate localhost origin/port from your normal Arslan web session:
the fixture overwrites that origin's synthetic thread/session selection.

This renders the real App with fixed synthetic conversation, project and task
data. API reads are mocked; API writes return 403; WebSocket sends are no-ops;
external fetch requests are rejected. Do not add real credentials or data.
The shell-enabled posture is a display fixture, not execution permission.

The HTML is not a Vite production build entry. This is a reproducible layout
check, **not** real-model, native desktop, permission or task-execution evidence.
When running with `DISABLE_HMR=true`, restart the dev server and reload after
fixture edits because file watching is disabled.

Check normal and narrow windows: diagnostics initially absent, project/task
status share one wrapping row, review task still visible, no empty expert
strip, attachment/microphone adjacent, and collapsed execution options still
show automatic-read-only versus confirm-all posture. Open/close diagnostics,
project controls and task details; expand execution options. Check overflow
and preserve composer reachability. Do not submit fixture actions as live work.
