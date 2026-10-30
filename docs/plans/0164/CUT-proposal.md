# v0.1.64 cut: a proposal for the user

⓪Plan, 2026-10-30, at the user's request relayed by ④参谋: "push the project; we need progress, not percentages". For the user to decide. Nothing here changes a gate or the scope until the user says so (`docs/sessions.md`: the plan's gates and scope are the user's).

## Where it stands

- **Merged since the plan (#434, `3759f57b`):** 66 PRs on main. 30 of them are product code; the rest are docs, cards, bench and tests.
- **Done (the "must" cards that are complete or nearly so):**
  - PRJ0;
  - F5b-2;
  - C5b;
  - S64-0b plus S64-0c;
  - LANG1;
  - FS1 (code; the real-Mac check is still open);
  - BR1 and BR2;
  - CAP1a–c, CAP2a–b, CAP3a-1/-2, plus the gh- follow-up;
  - INB1;
  - Q1a and Q1b.
- **About to land** (reviewed, waiting on a sync or the user):
  - #475 INB2;
  - #490 Q1 #3;
  - #512 FRONT1.
- **The longest path is serial:** SBX-2 (Codex, #507; its macOS job has 3 real failures to fix) → SBX-M (the user's Mac) → SBX-3…6, each half p then a → SBX-7 → S2a-3 → HR → CLS → S5a → S5b. That is at least 12 PRs in a row, two of them needing the user (SBX-M and the classifier pass lines' measurement), plus Astra reviews. Everything in the security chain waits on it.

## Proposal

**Ship v0.1.64 without the tail of the security chain.** Cut it when the "ship" list below is merged and the release gates pass. Move what isn't done to v0.1.65, rather than holding the release for it.

### Ship in v0.1.64 (remaining PRs, estimated)

| Card | Lane | Left |
|---|---|---|
| Q1: Quick Chat (Mac + iPhone Q1c, pocket deletion) | ②Main, ①iOS | #490, pocket deletion (1), Q1c (iOS repo), TestFlight |
| INB2 (#475) + MEM1 | ②Main | #475, MEM1 (1) |
| INB3–INB9 (scheduled entry, sidebar dots, inbox out, run records, progress brief, push, acceptance sheet) | ②Main / another session | about 7 |
| CAP4–CAP7, CAP8, CAP8b, CAP9 | ⑤CAP | about 8 |
| SKF1, UNI1a | ⑤CAP | 2 |
| STY + STY2 (#452) | ⑥Helper | 1–2, after the read test and a bench run |
| SB1 (sidebar), WB1-1/-2/-3 (workbench), SIDE (side chat) | ⑥Helper | about 6, after the mocks |
| FRONT1 (#512), NAME1 | ③Hands | 2 |
| SBX-2 and SBX-M | Codex, the user | 2 (they are not wired, so they ship as staged code) |
| C7c-2…, #298b (SECURITY / ARCHITECTURE match the shipped model) | ②Main | about 3 |

About 35 PRs in all, spread over five lanes that don't depend on each other.

### Move to v0.1.65 if not merged by the cut

- **The security chain's tail:** SBX-3…SBX-8, S2a-3, HR, CLS, S5a, S5b. Until it lands, v0.1.64 keeps today's model: "ask before every command" is the default and the parser is the first line. That is safe, just not faster.
- **SUB** (sub-sessions, SUB2–SUB7) and **SIDE's** dependence on SUB2. If SUB2 misses the cut, SIDE moves with it.
- **ACM** (the cards' look and wording merge). It waits on S5a's modes anyway.
- **L6, L7, L11 + K10** ("should" items in the execution-lead rows).
- **CAP10 (verify), CAP11 (iPhone install cards), CAP6b and CAP5's runtime parts that need SBX.**
- **SEC1, TITLE1, MCPOUT1, EXC1** ("could" items).
- **BRW1, BRW2** were already v0.1.65 candidates.

## What the user decides

1. **Cut without the security chain's tail?** Recommended: yes. Otherwise v0.1.64 waits on SBX-2's fixes, SBX-M on the user's Mac, and about 10 more serial PRs.
2. **SUB and SIDE:** keep them in v0.1.64 if SUB2 lands in time, or move both now. Recommended: decide after SUB2's first PR is open. If it isn't open within the next round, move both.
3. **Release gates (R64):** keep them as written, with the security-chain items marked "v0.1.65" instead of "failed". Recommended: yes.
4. **The pocket deletion:** it stays conditional on Q1c shipping with Mac 0.1.64 (user, 2026-10-29). No change.
