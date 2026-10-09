/**
 * 0.1.59: a background job's card never shows a raw stop code ("Stopped (task_reconciliation_required)"
 * was on screen in an English promo take). Every code the server finishes a job with
 * (server/services/task_service.py, the `reason=` of repo.finish) has words in every language.
 */
import { describe, expect, it } from "vitest";
import { jobMessages } from "../locales/jobs";

const FINISH_CODES = ["task_reconciliation_required", "execution_failed", "task_validation_failed",
  "task_checks_not_run", "acceptance_review_required"];

describe("job stop reasons", () => {
  it("have words in every language", () => {
    for (const [lang, m] of Object.entries(jobMessages)) {
      const detail = (m as { detail: Record<string, string> }).detail;
      for (const code of FINISH_CODES) expect(detail[code]?.trim(), `${lang}.${code}`).toBeTruthy();
    }
    expect(Object.keys(jobMessages).sort()).toEqual(["de", "en", "es", "fr", "ja", "zh"]);
  });
});
