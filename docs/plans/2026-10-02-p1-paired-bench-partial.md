# P1 paired bench (native vs legacy), partial — 2026-10-02

Budget approved: $2. Spent: **$0.41** at DeepSeek peak rates (metering proxy), deepseek-v4-pro.
Two Arslan test instances from `claude/0149-kernel` (P1 S1–S9): `arslan` (native tool protocol)
and `arslan-legacy` (`ARSLAN_TOOL_PROTOCOL=legacy`), throwaway HOME and data, bench sandbox.

**Stopped after 7 complete runs**: from 08:04 the upstream answered `402 Payment Required` (some
requests still 200, then 402 — insufficient DeepSeek balance on the spike key; neither proxy cap
was reached). The two runs that hit it (`arslan-legacy-T5-r2`, `arslan-T3-r3`) spent $0 and are
**excluded** — they measure the account, not the agent.

| run | score | $ (peak) | model time | calls | output tok | cache hit | cache miss |
| --- | --- | --- | --- | --- | --- | --- | --- |
| arslan-T3-r1 | **3** | 0.0883 | 112 s | 14 | 12,982 | 182,016 | 21,918 |
| arslan-legacy-T3-r1 | 0 | 0.0404 | 61 s | 8 | 4,926 | 34,688 | 14,673 |
| arslan-T5-r1 | **3** | 0.0631 | 82 s | 9 | 12,034 | 125,696 | 7,489 |
| arslan-legacy-T5-r1 | **3** | 0.0946 | 134 s | 9 | 20,967 | 71,552 | 6,376 |
| arslan-T3-r2 | 0 | 0.0268 | 52 s | 9 | 2,561 | 59,776 | 10,640 |
| arslan-legacy-T3-r2 | 2 | 0.0540 | 100 s | 8 | 8,405 | 49,664 | 14,050 |
| arslan-T5-r2 | **3** | 0.0390 | 66 s | 6 | 8,009 | 40,192 | 4,196 |

What the failures were (read from the records, not inferred):
- `arslan-legacy-T3-r1` (0): found only quarterly figures, said so honestly, saved no file.
- `arslan-legacy-T3-r2` (2): all six numbers right, but no source noted in the table.
- `arslan-T3-r2` (0): **bug** — DeepSeek wrote its chat-template tool-call markup
  (`<｜｜DSML｜｜tool_calls>…`) into content instead of native tool_calls, and the answer guard did
  not recognise it, so the markup became the final answer. Fixed after the run (the guard now
  treats DeepSeek template tokens as protocol text: bounced, never shown, never executed;
  `tests/server/test_dsml_leak.py`).

Reading (deliberately limited — n is 1–2 per cell):
- **T5 (the sample's failure)**: native 2/2 full marks; on the paired repeat native was faster and
  cheaper (82 s / $0.063 and 66 s / $0.039 vs legacy 134 s / $0.095). The 0.1.48 sample scored T5
  0/2; P1 changes beyond the protocol (output budget, truncation handling) apply to both arms, so
  this improvement cannot be credited to the native protocol alone.
- **T3**: one native full pass, one native failure from the markup bug; legacy 0 and 2. Native r1
  used more calls and far more cached input (182k) — cheap per token, but the cost of T3 r1 was
  still the highest of all runs.
- No Pass^3 claim is possible from this data.

Remaining (needs the balance topped up, ~$1.6 of the approval left): T3 ×3 and T5 ×3 per arm again
from scratch with the markup fix, so every cell has three comparable runs.
