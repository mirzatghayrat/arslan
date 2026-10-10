# 0.1.59 — "Desktop, Documents, Downloads: Off" also closes them to commands

Status: approved by the user 2026-10-10 ("真的挡住，放进 0.1.59"). Found while recording the promo on
v0.1.59-beta.3 (the recording session's report), checked in the code.

## 1. What went wrong

With **Desktop, Documents, Downloads** off (`default_read_enabled = false`), a question from the paired
iPhone — "How many duplicate files are in Downloads?" — made Arslan scan the user's real `~/Downloads`
with five `run_command` calls (ls, find, stat, a python hashlib walk), none asking, and answer from it.

- The toggle gates only the file tools and the reader (`file_tools.py:62`, `file_reader.py:50`).
- The command sandbox is `(allow default)` for reads and closes only `~/.ssh`, the keychains and Arslan's own
  data (`command_sandbox.py:80-118`); `ls`/`find`/`stat` are "run" level, so no card either.
- The setting promises more: "When off, Arslan still reads and writes its own folder"
  (`capabilityList.ts:25`).

`run_python` (default-deny compute profile) and installed capabilities (default-deny profile) already
cannot read these folders; the gap is `run_command`.

## 2. Change

- While the toggle is off, the command sandbox denies reading and writing `~/Desktop`, `~/Documents` and
  `~/Downloads` (`workspace_paths.green_roots()`, real paths). Inside them, the working folder (read and
  write, as today) and active project folders (read) stay open — a workspace or a project kept in
  Documents keeps working. Arslan's protected paths close last, as before.
  Measured on this Mac (seatbelt): a deny on a folder followed by an allow on a folder inside it works; the
  folder is also closed through `/System/Volumes/Data/…` and through a symlink; listing its parent still
  shows its name.
- A command stopped by this is told why (`command_sandbox.note`): those folders are closed in Settings; it
  may ask to run outside the sandbox, and the user decides with a click — that click is the only way past,
  one command at a time.
- The setting says what it does, in six languages: off keeps Arslan's file tools and its commands out of
  these folders; Arslan still uses its own folder.

## 3. Not covered (said in the setting's notes and here)

- A command the user lets run outside the sandbox (the re-run card), and every command when the terminal
  sandbox is off in Settings or unavailable on the system, is not confined.
- The iPhone's suggestion chips ("How many duplicate files are in Downloads?") live in the iOS app —
  ①Arslan iOS's area; passed to the user.

## 4. Tests

- Profile text: with the toggle off the three folders are denied, the workspace and project folders inside
  them re-opened, protected paths last; with it on, nothing changes.
- Real seatbelt (macOS-marked): a command cannot list or read a closed folder, can read and write the working
  folder inside it, and cannot reach it through `/System/Volumes/Data` or a symlink.
- The executor passes the toggle through (on → no extra rules; off → closed), and a denied read is reported
  as stopped by the sandbox with the folders named.

## 5. No evidence yet

- Not run in the packaged app with a real model (needs a beta build).
