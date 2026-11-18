# 0.1.65: follow-ups from the 0.1.64 pre-tag bench

**Source.** The 0.1.64 pre-tag plain-mode rerun of 2026-11-18, on main `9fb8f7431`:
- 9 tasks ×3, goal off, `ask_risky`, a fresh instance per run;
- arms: DeepSeek `deepseek-v4-pro`, Claude Sonnet and Claude Opus 5.5;
- a rule rerun on DeepSeek of T1, T2 and T11.

**The release ruling.** 0.1.64 blocks only on a problem that is new in 0.1.64, affects real use, and hasn't been explained. Nothing met that bar. The items below are what the run left for 0.1.65.

The AppleScript items (comment stripping, and a Reminders/Calendar path) are in `2026-11-18-0165-mac-scripts-followups.md`, added with #1001.

## 1. Top priority after 0.1.64: "ask before doing"
- **What happens.** The user asks for an action, for example "clean up the .bak files in this folder". The model looks, writes the exact command in its reply, and asks in chat ("确认后我就执行") instead of calling the tool. No card is raised and nothing happens. The turn ends as if it were done.
- **Seen in the pre-tag run.**
  - DeepSeek: 2 of 6 T11 runs.
  - Sonnet: 0 of 3. It made the call, the card was declined with "move to Trash", and it moved the files.
  - Opus 5.5 didn't ask in chat. In all 3 T11 runs it asked through Arslan's own choice card (`clarify_options`), because 2 of the 5 `.bak` files have no original. That's a real question about the data, but the bench can't answer a choice card, so those runs end waiting.
- **What's known.**
  - No 0.1.64 prompt or memory text invites asking first. The only added line on asking says to ask only when a choice really needs the user.
  - Arslan tells the model nothing to the effect of "an action the user asked for raises its own card when it needs one; don't ask in chat first".
- **Measure first.**
  - T11 ×3 on DeepSeek, Sonnet and Opus.
  - Count three outcomes: ask-in-chat (no tool call), a choice card, or acting.
  - For Opus, judge separately whether the choice card was warranted (a destructive step on data with no copy) or over-asking.
- **Then change** the prompt, a tool description, or a host note that says a requested action goes through its card, not a chat question. Re-measure T11.
- **Then check for side effects:** all 9 tasks once on one model, so the change doesn't make the model skip a question it should ask (T8's three turns, T1's dates).
- **The bench** also needs an answer for `clarify_options` (pick the option that matches the task's intent, and log it), or T11 can't measure a model that asks this way.

## 2. T8 fails on every model
- In the pre-tag run: Sonnet 0/3, Opus 0/3, DeepSeek 1/3. In 0.1.63: Claude 0/3, DeepSeek 1/3.
- Every miss has score 2 with `section2_shortened: false`. Turn 2 asks to shorten section 2, and the checker wants it at most 60% of its length. The models keep it longer.
- **First decide** whether the 60% bar matches what a user means by "shorten". **Then decide** whether this is a model or prompt issue. Hand-check the turn-2 replies before changing anything.

## 3. T3: the model doesn't find the latest annual filing
- Apple filed its FY2026 10-K on 2026-11-03, so on the run date `check_t3` asks for FY2024–FY2026.
- Two of the three Sonnet runs listed FY2023–FY2025: the right values, from real sources, but one year behind. One found FY2026.
- DeepSeek and Opus were 1/3 too.
- **Look at** what the web search returned and whether the model looked for a newer filing than the one it already knew. A research note ("check for a filing newer than the one you remember") may be enough.
- **The checker moves with the calendar.** Compare T3 across versions only within the same filing window.

## 4. T1: should a later successful read-back settle an earlier unknown action? (design item)
- **What happened** (DeepSeek, rerun r1):
  - An approved bare Reminders script failed at run time partway through (`-1700`), after it had already created the list and the first reminder.
  - That action stays outcome-unknown, and `reconciliation_required` is sticky ("a later success elsewhere does not settle an earlier unknown outcome", `task_service.TaskRuntime.execute_tool`).
  - The model then read the list back, finished the reminders and verified them. All 3 are right, but the task ends `task_reconciliation_required`.
- **The question.** Should a later read that shows the intended end state settle the earlier unknown action?
- **Why it's a design item.** The sticky rule is the guard against repeating a write whose outcome is unknown. Any settling rule has to say:
  - which read counts (same app, same objects, after the unknown action);
  - who decides that it shows the intended state (host, judge, or the user);
  - that a settled action still can't be repeated.
- **Review.** Max.
- **A smaller, separate item.** A plain Reminders script with no write verbs is still labelled `external_write` (`effect_of`). A read-only listing script that failed at run time therefore also raised reconciliation in the same run. A labelling fix there is small, but on its own it wouldn't have saved this run.
