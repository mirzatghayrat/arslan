# Stage 2 — bounded real-model evidence, 2026-09-23

This supplements, not replaces, the earlier offline and public-input records.
It is a development pilot, not an independent audit or a 12/12 product score.
The user subsequently authorized continued bounded delivery and a new preview
candidate, plus the configured primary model with **36 requests / US$5 maximum**.
No real chats, personal documents, accounts or installed profile migrations were
used. Only the primary provider configuration and its decryption material were
read locally; they were not logged or copied into evidence.

## Model and spend boundary

- Requested primary: DeepSeek `deepseek-v4-flash`, official API endpoint.
  The provider's [current pricing page](https://api-docs.deepseek.com/quick_start/pricing/)
  says this old model name serves DeepSeek-V4.1-Flash. This is not a pinned model
  weight revision. Prices checked 2026-09-23: peak cache-miss input US$0.30/M,
  output US$1.20/M; cheaper cache/off-peak rates are not assumed.
- `evals/companion/live_guard.py` requires explicit opt-in, caps each serialized
  request at 100,000 UTF-8 bytes and output at 8,192 tokens, reserves US$0.10
  before each request, and never refunds failed/interrupted reservations.
  One durable locked ledger covers all attempts; no automatic model retries.
  Unknown or out-of-bound usage stops further calls. CI skips live calls.
- **32 requests**, including baseline, harness error and selected repair checks;
  **68,590 input / 20,006 output tokens**. Peak-rate estimate **US$0.0445842**,
  not an invoice. Durable conservative reservations total **US$3.20**.
  Four authorized requests remain unused; a new ledger must not reset the cap.

## Reviewed outcomes and limitations

The synthetic pack remains revision 1, with its original hashes and original
zero-authorization historical metadata unchanged. Live authorization is above.
All answers came through the real host/provider path and isolated SQLite data.
Passing harness assertions establishes execution and persistence, not quality.
The following is Codex's source/output review, not independent human sign-off.

| Case | Observed result | Boundary still retained |
| --- | --- | --- |
| R1 | Real reads of three pinned public READMEs; purposes distinguished and Arslan benefits not represented as measured. Direct source links retained. | Two reads truncated; no complete license/security audit or universal claim-level proof. |
| R2 | Frozen synthetic same-date contradictory sources were both retained without inventing a winner. | Genuine public same-scope conflict not selected; full public case remains blocked, not dropped from denominator. |
| R3 | Synthetic update analysis plus pinned legacy/current Lightning excerpts: old integration advice treated as unverified; commit dates not confused with releases. | Public run received short supplied excerpts, not full independently read pages or verified API migration. |
| R4 | Synthetic bilingual task plus pinned English/Chinese OpenSquilla excerpts: local classification not expanded into all-local inference. | Supplied excerpts only; answer overly verbose and adds an unnecessary alternative reading. Not a clean full-task pass. |
| D1 | Synthetic PDF answer distinguishes page 1/page 3 and absent page-2 extracted text. | Text-layer evidence, not visual PDF acceptance. |
| D2 | Baseline incorrectly inferred a three-day change from Friday/Monday. Repair check preserves unknown direction/interval without calendar dates. | Word revision filtering has separate parser regression evidence, not a complete revision renderer. |
| D3 | USD 12 / CNY 23.50 computed correctly, missing amount disclosed; actual approved `totals.csv` written, read back and independently parsed; artifact manifest present. | Initial persistence assertion used the wrong role name; original model output was valid and retained. This harness error is not counted as a product failure or erased. |
| D4 | Unsupported input acknowledged; supported CSV used without inventing unread content. | Live input was prepared by the real reader; frontend attachment-retention path tested separately, not a native end-to-end upload recording. |
| M1 | Project A uses its confirmed orange rule; B reports unknown. | Isolated projects and explicitly saved synthetic rule, no personal profile. |
| M2 | Proposed blue guess not used; confirmed green correction used. Initial decorative invented report status removed in repair check. | UI/repository confirmation, not unrestricted natural-language intent certification. |
| M3 | Deleted violet preference excluded; actual real-model compaction regenerates a summary and later answer without that preference. | One isolated deletion/compaction trajectory, not all paraphrases or concurrency permutations. |
| M4 | Live continuation retains owner, repaired answer avoids invented calendar date. Additional simulated process-loss run preserves saved output references and budget ID across explicit resume; two attempts, cumulative request count, still awaiting acceptance review. | Read-only live interruption; uncertain writes and duplicate-effect fencing tested separately with deterministic executors. No real OS crash or external account mutation. |

## Focused repairs

1. Word reader excludes deleted/moved-from subtrees and discloses tracked
   revisions while retaining original paragraph locators (offline baseline).
2. Malformed source traces fail closed as unread rather than raising; separate
   valid receipts remain usable (public-input baseline).
3. Research output grounding: no inferred calendar dates/intervals or invented
   project facts; direct source navigation has deterministic read/unread/partial
   labels in six locales. A link list is explicitly **not claim verification**.
   Only supplied URLs and validated read receipts qualify; credential-bearing
   links are excluded, entries bounded to 12. Explicit output-only requests
   suppress the appended footer so strict formats are not knowingly corrupted.

The first prompt-only source-link repair still omitted URLs. That failure is
retained; deterministic streaming/persistence regression now covers omission.
The final partial-read footer was replayed against the saved real read trace:
one fully read source and two partial sources. No additional paid call was used
to relabel this replay as a fresh model result.

## Evidence and verification

Raw isolated outputs, provider usage, all attempts and read traces are retained
locally in `stage2-live-evidence-20260923` beside the development worktrees;
they are not automatically uploaded as feedback. There are 61 files. Digest of
sorted `filename + space + file SHA-256` lines joined with newline (no trailing
newline): `d93d9cc5369a1ae36a1dc0e0467fff73de55fcd52c85f0f51846798d48162cda`.
The original `/tmp/arslan-stage2-live-20260923/reservations.jsonl` remains the
single budget ledger; the durable copy is evidence, not a fresh spending grant.

- Focused backend lifecycle/memory/documents/source/guard group: **137 passed**;
  16 live tests skipped in that offline invocation. Two later public-excerpt
  tests were added and separately executed under the same live ledger.
- Frontend identity and mixed-input retention: **24 passed**; TypeScript and
  production web build passed (existing large-chunk warning remains).
- Final release-workflow, packaging-entry, fresh-install probe and source
  persistence checks: **73 passed**, all 18 opt-in live tests skipped. This is
  source-level coverage, not acceptance of a newly built installer.
- Gitleaks directory scan: no leaks found across the checked working tree.
- Ruff and whitespace checks passed at source verification; final same-source
  CI and packaged verification are separate release gates.
- A local pytest 9.1.1 invocation interleaving root/server file arguments lost
  server fixtures on the second directory traversal. Same tests grouped by
  directory passed (79), and task repository alone passed (19). No product
  workaround or fixture bypass was added; full CI uses normal tree discovery.

No claim is made that all 12 full pilot cases passed. Remaining public conflict,
complete-source research, native UI and independent safety/usefulness review
remain visible work. This preview may deliver the bounded repairs without
advertising completed v1.2, autonomous account actions or measured cost savings.
