# P1 paired bench: native vs legacy tool protocol — 2026-10-02

Approved $2 for this step. Spent **$1.17** in total at DeepSeek peak rates: $0.41 in the
interrupted first attempt (see `2026-10-02-p1-paired-bench-partial.md`) and **$0.76** in this full
rerun. Model deepseek-v4-pro; two Arslan test instances from `claude/0149-kernel` (P1 S1–S9 plus the
DSML fix `4686340c`): `arslan` = native tool protocol, `arslan-legacy` = `ARSLAN_TOOL_PROTOCOL=legacy`.
Throwaway HOME/data, bench sandbox, metering proxy; no upstream errors this time.

## Results (3 runs per cell)

| task | arm | Pass^3 | mean $ | mean model time | mean calls | mean output tok |
| --- | --- | --- | --- | --- | --- | --- |
| T5 organise Downloads | native | **3/3** | **0.064** | **87 s** | 8.3 | **12,643** |
| T5 | legacy | 3/3 | 0.093 | 140 s | 6.7 | 20,911 |
| T3 Apple financials table | native | 1/3 | 0.062 | 88 s | 10.0 | 10,284 |
| T3 | legacy | 0/3 (all scored 2) | 0.033 | 48 s | 7.0 | 5,747 |

Per run: native T3 3/0/0, legacy T3 2/2/2; native T5 3/3/3, legacy T5 3/3/3.

## What happened (read from traces and saved files)

- **T5**: both arms always correct. Native used 32% less money, 38% less model time and 40% fewer
  output tokens, with more (cheap, cached) input — consistent with the model not re-deriving its plan
  each step once its reasoning is passed back. This is the one clean protocol comparison here.
- **T3, legacy**: every run read the same stockanalysis.com excerpt, wrote all six numbers
  correctly (via `run_command`), and **never noted the data source** the task asked for → 2 each.
- **T3, native**: r1 full marks (file, numbers, source). r2 and r3 said net income was "not in the
  material" and saved no file (r2 even claimed it could not write to the folder; no write was
  attempted). The excerpt both arms read **does contain** net income (112,010 / 93,736 / 96,995):
  the native runs overlooked data they had read, then declined to save an incomplete table.
- **Environment defect affecting both arms**: Arslan's zero-key web search returned 0 results on
  every query. Measured outside the sandbox too: DuckDuckGo's HTML endpoint now answers **202 with
  a "prove you are human" challenge**, which `DuckDuckGoHtmlProvider` parses as "0 results". The
  model is told "0 results · best_effort", not "search is blocked". This is a product bug (users
  without a Tavily/SearXNG key get silently empty search) and it starves T3 of sources.

## Reading

- Native protocol: clearly more efficient on the task both arms can do (T5).
- On T3 neither arm is reliable in this environment; native passes once but fails differently
  (misses data, skips the save); legacy is consistent but always misses an explicit requirement.
  No protocol verdict on T3 until search works.
- Not attributable from this data: whether native's T3 misses come from the protocol itself.

## Must fix before the comparison against Hermes

1. Search challenge detection: a challenge/blocked page must be an explicit tool error
   ("search provider blocked; configure a search key"), never "0 results"; and a working
   zero-key search path (look at what mainstream agents ship).
2. T3 native failure modes: (a) "data not present" when it is — a tool-result attention/grounding
   issue; (b) declining to save a partial table and falsely claiming it cannot write. Candidate
   levers: P2 status bar (owned outputs, write ability stated each step) and tool descriptions.

## T3 rerun with search fixed (`918f445a`) — 2026-10-02

Approved $0.60; spent **$0.237** (one live verification search $0.0014 + six runs $0.2355).
Both arms used DeepSeek native search through the automatic order (13 searches, all 200; the
verification call returned 5 results in 2.7 s). No upstream errors.

| arm | Pass^3 | per run | mean $ | mean model time | mean calls |
| --- | --- | --- | --- | --- | --- |
| native | **3/3** | 3 / 3 / 3 | 0.046 | 64 s | 9.7 |
| legacy | 1/3 | 2 / 2 / 3 | 0.033 | 46 s | 9.0 |

All six runs saved a file with all six numbers correct. The two legacy misses are the same as
before: no data source noted although the task asks for it.

Reading: with search working, the native protocol is the reliable arm on T3 (Pass^3), at ~40% more
cost and time than legacy on this task; on T5 native was both reliable and cheaper. The earlier T3
native failures (overlooking data, skipping the save) did not recur once sources were available —
consistent with them being a symptom of starved research, not of the protocol; not proven.

Open: DeepSeek reports `web_search_requests` per native search; whether that is billed beyond
tokens is not stated on its pricing page (the proxy prices tokens only).
