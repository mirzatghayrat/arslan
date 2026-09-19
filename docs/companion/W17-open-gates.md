# Remaining release gates — triage, not completion certification

Snapshot: packaged reader verification after `3a0d6177`, 2026-09-19. This index complements the chronological
`W17-release-audit.md`; it does not replace the approved v1.2 plan, task-package
acceptance checklist or v1.3 browser/input/language amendment in `README.md`.
An engineering regression passing does not make the candidate releasable.

| Gate | Current evidence / gap | Evidence required to close it |
| --- | --- | --- |
| Safe user-facing recovery (I01/I05, W17) | Native cancellation/activation/restart, pause/bound rollback and wrong-key checks pass with retained data/credentials. Six pending-recovery language sheets/notices and cross-language rollback are observed. Dedicated read-only maintenance presentation and native voice/link admission guards exist; Chinese prepare/keep-paused and missing-component refusal pass. Refusal preserves the running service and draft. | Remaining filesystem/timeout/error native branches; full six-language maintenance layout acceptance; custom durable key configuration. |
| Isolated credentials and approvals (W11) | Approval storage/admission and command boundaries have synthetic evidence. ASC contracts still return `isolated_credential_broker_review_required`; no production credential transport. | Trusted broker identity and OS boundary evidence, approval UI, hostile file/process/port/debugger canaries, revocation races and independent security review before genuine secrets. |
| Account workflow (W12/W13) | Preparation and host-only single-field execution exist; fixture transport is not real account support. | After W11: authorized target binding, real read-only account validation, approved test draft write and independent readback; screenshot/partial-write handling. Submission and publication remain separately disabled unless authorized. |
| Interactive browser and dock (W19) | Public bounded navigation and dock have component/app/native evidence. Failed-capture link rebinding is fixed; the refreshed bundle passes actual reader APIs and a Chinese/dark native navigate/fail/recover/stop path with no owned children left. Authenticated interaction is not certified. | Finish the approved interaction/permission scope, ownership/cancellation and sensitive-action boundaries; runtime provisioning and remaining native browser/dock/artifact acceptance. Do not substitute static previews for interaction. |
| Input fidelity (W20) | Shared format registry, bounded extraction, source locators and sampled video frames exist. Three frames are not full-motion understanding; transcription is disclosed unavailable. | Current packaged real-format/codec cases; supported preview/extraction/visual-understanding distinctions; model-visible inputs and output quality where authorized; explicit unavailable capabilities rather than fabricated results. |
| Six-language native UX and old-data compatibility (W16/W21) | Web/component matrices and actual six-language pending-recovery sheets/menus/notices exist. Cross-language rollback refresh is verified. Earlier disappearing-greeting finding is not causally closed. | Full six-locale narrow/wide and light/dark runtime checks, rapid switch/back/reload, other native menus/dialogs, old entry points/data, keyboard focus and restart behavior on the current bundle. |
| Design/media workflows (W15) | Versioned style references and a restricted local-media adapter exist. Execution provisioning/review and real D01–D08 outcomes are not complete. | Editable/runnable output evidence, verified artifacts/cancellation, authorized pinned backend when available, human assessment of visual dimensions and honest unavailable-backend fallback. No unapproved weights/cloud costs. |
| Memory and task quality (W01/W04/W05/W17) | Runtime evidence covers aspects of 25 memory scenarios, not all 60. `catalog.json` still labels real task inputs pending. | Remaining multi-turn bindings plus authorized real behavior evaluation; freeze real inputs/hashes and configuration; run all 30 families × 3 attempts without best-of-three selection; preserve missing/unsupported denominator and cost/latency accounting. |
| Packaging and final human acceptance (W17) | Full regression baselines pass 5,267 Python and 77 native cases; current frontend passes 1,918 cases. Reader changes are packaged and verified through frozen APIs/native UI; five added driver safety tests pass. Recorded temporary-app checks remain bounded synthetic-profile evidence. | Keep package/regressions current; remaining native first boot/upgrade/recovery and configuration retention matrix; applicable signing/notarization and human installation/security/UX review. No installed-app replacement or public release under the current authorization. |

## Next dependency order

1. The full `81949a01` regression finished with 5,197 passed, one old test-harness
   failure and 14 skipped; its `combined.xml` is retained. `7bd142c6` corrects
   that test without weakening production checks (61 focused cases passed).
   The corrected full run passed 5,198 cases with 14 skips and 19 warnings in
   601.28s; `corrected.xml` is retained beside the failed first report. Runtime
   changes after this baseline need their own proportional verification. The
   subsequent full Python run on `dfe02692` passed 5,248 cases with 14 skips and
   20 warnings in 570.00s; see the retained `full.xml` in the release audit.
   Current Python/test source at `ee20392a` passed 5,267 cases, 14 skips and
   21 warnings in 621.39s. Current frontend/native selections are recorded above;
   retained reports and the initial Node storage failure are in the release audit.
2. Resolve recovery key-source persistence **before** wiring a successful trial
   to normal restart. Existing bootstrap precedence and lock-and-box separation
   are constraints, not details to bypass. A selected backup key must work on a
   subsequent fresh launch without overwriting the original installation key or
   silently putting key material in the profile/backup. Any new storage/reference
   mechanism needs its own consent, rollback and tamper/error tests.
   `W17-recovery-key-restart.md` records a candidate-only credential re-encryption
   primitive, native durable default-file proof and bounded rewrap transport.
   Real frozen-backend tests now cover two independent normal default-key boots
   after native rewrap/trial/finalize. Consent/coordinator integration is now
   implemented but native acceptance remains unfinished, as does durable recovery
   configuration for custom key locations;
   this is not native-window acceptance or blanket consent to rewrite secrets.
3. Connect the trusted native recovery coordinator and UI. Include exclusivity
   against startup/update/another recovery, owned-child shutdown, explicit pending
   state after uncertainty, and retained original/candidate folders. Keep all
   operations unavailable to web/model IPC.
4. Rebuild and inspect the actual native UX when the desktop is available, while
   continuing independent remaining runtime/input/memory/broker work. A locked
   desktop blocks click evidence, not all engineering work.
5. Request real inputs/accounts/cost authority only when the corresponding safe
   implementation and review gates are ready. No synthetic success can replace
   those approvals or measurements. Notify publication readiness only after the
   full requirement-by-requirement audit, not after this triage table is green.

## Source anchors

- Approved external checklist: `Arslan-实施任务包与验收清单-v1.md`, especially
  I01–I12 and W11–W17; repository amendment: `README.md`.
- Native runtime and menu: `desktop/src-tauri/src/lib.rs`, `native_menu.rs`,
  `recovery_control.rs`, `recovery_trial.rs`, `recovery_shutdown.rs`.
- Key contract: `server/secret_bootstrap.py`; account gates:
  `server/connectors/app_store_connect/contracts.py` and `client.py`.
- Quality evidence: `evals/companion/README.md`, `catalog.json`,
  `memory-runtime-bindings.md`; feature limitations: W11/W12-W13/W15/W19/W20/W21
  checkpoint documents. Older sections are historical, not current blanket claims.

Attachment-fidelity source follow-up (2026-09-19, after `3a5cab09`): W20 now
records model-bound and sent-echo extraction-limit notices for both composers,
with 249 frontend files / 1,930 tests passing, TypeScript and production build.
The existing temporary native bundle has not yet been refreshed for this
frontend-only change. No release gate or real-model acceptance is closed by it.

W18's expanded 100-task improvement phase remains later; it is not a reason to
postpone W19/W20/W21 or to rename current engineering tests as real task success.
