# W00 — historical ten-task classification

Evidence: the existing 2026-09-14 “Arslan 设置改版与真实复测” report, application 0.1.38, configured model name `deepseek-v4-flash`. This review does not rerun that model, inspect credentials, or establish causality from missing traces.

| Historical task | Observed result | Classification |
| --- | --- | --- |
| Arithmetic | 480 | Passed; no failure observed |
| JSON with ambiguous name field | Valid JSON, “book” interpreted as name | Evaluation design ambiguity; excluded before aggregate score |
| Date from provided material | Wednesday | Passed |
| Missing person in material, exact response requested | Correct words plus a full stop | Format/instruction-following failure; model vs prompt contribution unknown |
| Three-line TODO with length constraint | Correct order and lengths | Passed |
| JSON with explicit buyer field | Correct fields and arithmetic | Passed |
| Priority sorting | Correct order, comma whitespace | Passed under the stated format rule |
| Translation | Correct English sentence | Passed |
| Box-color rule, color only | Correct final color plus inaccurate explanation | Format and unsupported-explanation failure; underlying reasoning cause unknown |
| READY only | READY | Passed |

Observed denominator: 9 scored, 7 fully passing, 2 failing; one ambiguous item excluded. All 10 returned; historical latency approximately 2.1–4.6 seconds. The report recorded 10 routing and 10 answer calls with 131,169 input tokens and 2,128 output tokens in aggregate. This reveals routing/context overhead worth testing, not proof that routing or memory caused the two failed answers.

No tool execution, external authorization, or multi-worker performance was exercised. No environment failure was reported. There is no evidence to attribute a failure to a specific tool or grant. Detailed model/prompt/route root cause remains unknown.

Follow-up acceptance requirements: freeze punctuation/whitespace rules up front; capture actual model requests in synthetic tests; avoid unnecessary routing/context for exact-response tasks; reject additional commentary when the user requests an exact answer. Do not rescore the old outputs under new rules.
