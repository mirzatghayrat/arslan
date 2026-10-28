# v0.1.64 smoke list

> ⓪Plan, 2026-10-28. Steps the user runs on a real Mac before v0.1.64 ships, beyond `scripts/hands_smoke.py` and the M3 list (`docs/plans/0162/M3-acceptance.md`). Each step names the card it checks. Record pass / fail and one sentence per step in the release's record; a step that is not run says so.

## FS1: closing the window in full screen (`docs/plans/0164/README.md` §3.6)

1. Open Arslan, put the main window in full screen, click ✕.
   - **Expected:** no black screen; you are back on the desktop you came from.
2. Reopen the window once from the menu bar and once from the Dock.
   - **Expected:** each time the window appears normally, on the current desktop.
3. **Extra:** full screen → ✕ → click the Dock icon at once.
   - **Expected:** the window stays shown.
4. **Extra (⑤CAP's review of #451):** press ✕ while the window is still animating into full screen.
   - **Expected:** no black screen. At worst, the window gives up after 3 s and stays shown.

## M3 halves the R63 verdict did not record (`docs/plans/0162/R63-verdict.md:94`, `:107-108`)

5. **M3 #7, the Mac half: streaming text in the Mac window** (`docs/plans/0162/M3-acceptance.md`, item 7; must use Claude).
   - Ask, in the Mac window, a question that needs no tools (for example "introduce the Great Wall in three paragraphs").
   - **Expected:** the text appears piece by piece, not all at once after a long wait.
6. **M3 #10a, timed** (`M3-acceptance.md`, item 10a).
   - Ask the three-page weather question from item 10a without interrupting; record the seconds from send to the finished answer.
   - **Expected:** the number is written down, with the previous version's seconds measured the same day (R63 could not judge it without that, `R63-verdict.md:57`). If you also time steering, note it under item 10b (interrupting from the iPhone mid-read), which is where M3 puts steering.
7. **M3 #12, the screenshot half** (`M3-acceptance.md`, item 12).
   - From the iPhone, then in the Mac window, ask Arslan for a screenshot of the Mac screen.
   - **Expected:** the image shows the real screen, not only the desktop background; in the window, a file card appears under the answer.
   - **Record:** whether macOS asked for Screen Recording the first time (the permission goes to Arslan, not Hands).
