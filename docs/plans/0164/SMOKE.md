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

## F5b-2 (#456): Hands still works without the Cua files

- Build a development Hands with its own bundle id (not `.dev`, which old builds hold), grant Accessibility and Screen Recording when asked, and run `hands_smoke.py`. Expected: the same pass list as #249's smoke. The user is at the Mac for the permission prompts.

## SB1 (#543, #550): the sidebar's order, collapse, pin and drag

The card's external evidence (`docs/plans/0164/SB1-sidebar.md`, Four lines §4) and the "Not covered" lines of #543 and #550: no test renders `App`, and jsdom's drag events are synthetic.

1. **Order:** open a conversation that sits low in the list (under "Previous 7 days" or "Older") and send a message.
   - **Expected:** it moves to the top of "Today" as soon as you send, not after the reply.
2. **A reply moves it too:** while that reply streams, switch to another conversation.
   - **Expected:** when the reply ends, the first conversation is still at the top. A new conversation also appears at the top.
3. **Collapse:** press ⌃⌘S, then press it again; then use the button at the top of the sidebar.
   - **Expected:** the sidebar hides and comes back each time. While hidden, the show button sits beside the traffic lights without covering them, and the title bar's content doesn't run under either (#543 placed it at 78 px from the left, 9 px from the top, unchecked on a Mac).
4. **Collapse is remembered:** collapse it, quit Arslan, reopen.
   - **Expected:** it opens collapsed.
5. **Pin:** pin an older conversation from its row menu ("Pin"), quit Arslan, reopen.
   - **Expected:** it is under "Pinned" at the very top, above the projects. "Unpin" puts it back in its place by time.
6. **Pin while a reply streams:** pin a conversation while its reply is still coming.
   - **Expected:** the pin holds; no error notice.
7. **Drag into a project:** drag a conversation onto a project in the sidebar.
   - **Expected:** it moves into that project, as "Move to project…" does.
8. **Drag one that is running:** drag a conversation onto a project while its reply is still coming.
   - **Expected:** it stays where it was, and the notice says it couldn't move because it may be working ("Couldn't move it — it may be working right now.").

## K10 + L11 (#594, #603; `docs/plans/0164/L11-3-rule-followups.md` §L11-3c)

1. **Rules load:** in a project folder that has an `AGENTS.md`, start a conversation and open Overview.
   - **Expected:** Environment shows "Folder rules · 1 file"; expanding it lists the file, and clicking it opens the reader.
2. **The card:** in that conversation, correct Arslan on the same thing twice (for example "write the summary as a bullet list", two turns apart).
   - **Expected:** after the second correction, a card asks "Make this a rule for this folder?" with the line and the file, and the buttons Add and Not now.
3. **Add:** click Add.
   - **Expected:** the file ends with `- <the line>`, and nothing else in it changed (compare with a copy made before).
4. **Remove after a reload:** reload the window, open Overview, and click Remove under the file.
   - **Expected:** the line is gone and the file is byte for byte the copy from step 3's "before".
5. **The switch:** Settings → Advanced, turn "Follow folder rules" off.
   - **Expected:** Overview says "Folder rules: off", and the next turn doesn't follow the file's rules.
6. **Language (L11-1):** in a folder whose `AGENTS.md` says "Write files in English", ask in Chinese for a short note saved as a file.
   - **Expected:** the reply is in Chinese and the file is in English.
