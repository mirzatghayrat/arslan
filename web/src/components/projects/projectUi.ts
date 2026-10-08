import type { TFunction } from "i18next";
import type { Band, Column, Evidence } from "../../api/projects";

/** Board columns in order (Dropped is folded under the board, not a column). */
export const BOARD_COLUMNS: Exclude<Column, "dropped">[] = ["idea", "shaping", "doing", "done"];

/** Colour of a band / column: Shaping amber, Doing blue, Done green (the boards' legend). */
export const BAND_DOT: Record<Band | "idea", string> = {
  idea: "bg-subtle-foreground", shaping: "bg-ask", doing: "bg-info-strong", done: "bg-success",
};
export const BAND_SOFT: Record<Band, string> = {
  shaping: "bg-ask-soft", doing: "bg-info-soft", done: "bg-success/10",
};

/** Whole days since an ISO time (UTC from the server), never negative. */
export function daysSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.floor((now - at) / 86_400_000));
}

/** One line saying what Arslan saw: "you said “…”", "build/game.app appeared". */
export function evidenceText(t: TFunction, evidence: Evidence | null | undefined): string {
  if (!evidence) return "";
  switch (evidence.kind) {
    case "said": return t("projectsUI.ev_said", { quote: evidence.quote ?? "" });
    case "file": {
      const path = evidence.path ?? evidence.paths?.[0] ?? evidence.pattern ?? "";
      return (evidence.count ?? 1) > 1
        ? t("projectsUI.ev_files", { count: evidence.count, pattern: evidence.pattern ?? path })
        : t("projectsUI.ev_file", { path });
    }
    case "run": return evidence.goal ? t("projectsUI.ev_runGoal", { goal: evidence.goal }) : t("projectsUI.ev_run");
    case "checkpoints": return t("projectsUI.ev_checkpoints");
    default: return evidence.quote ?? evidence.path ?? "";
  }
}
