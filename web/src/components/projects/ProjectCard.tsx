import { useTranslation } from "react-i18next";
import type { BoardCard } from "../../api/projects";
import { Button, Tag } from "../kit";
import { templateOf } from "./NewProject";
import { BAND_DOT, daysSince, evidenceText } from "./projectUi";

/** The level bar: one segment per level — cleared dark, current outlined, to do faint. */
export function LevelBar({ levels }: { levels: BoardCard["levels"] }) {
  return (
    <div className="flex gap-0.5" aria-hidden="true">
      {levels.map((lv, i) => (
        <span key={i} className={`h-1.5 flex-1 rounded-full ${lv.state === "cleared" ? "bg-foreground"
          : lv.state === "current" ? "bg-foreground/35" : "bg-fill-strong"}`} />
      ))}
    </div>
  );
}

/**
 * A project on the board (0.1.56 §1): what it is, what "done" means, how far, how long in
 * this level — and, when Arslan thinks a level is cleared, the proposal with its evidence.
 * The card is never dragged: where it sits follows its level.
 */
export default function ProjectCard({ card, onOpen, onDecide, onPlan, busy }: {
  card: BoardCard; onOpen: () => void; onDecide: (accept: boolean) => void; onPlan: () => void; busy?: boolean;
}) {
  const { t } = useTranslation();
  const days = daysSince(card.current?.started_at);
  const done = card.column === "done";
  const p = card.proposal;
  return (
    <article data-testid={`project-card-${card.id}`} data-column={card.column}
      className="flex flex-col gap-2 rounded-xl border border-border bg-background p-3 shadow-sm">
      <button type="button" onClick={onOpen} className="flex flex-col gap-2 text-left">
        <span className="flex items-start justify-between gap-2">
          <span className="text-[14px] font-semibold leading-snug">{card.name}</span>
          <span className="flex shrink-0 gap-1">
            {card.paused && <Tag>{t("projectsUI.pausedTag")}</Tag>}
            <Tag>{t(`projectsUI.type_${templateOf(card.template, card.kind)}`)}</Tag>
          </span>
        </span>
        {card.finish_line && <span className="text-[12px] leading-snug text-muted-foreground">
          <span className="text-subtle-foreground">{t("projectsUI.finishLine")}</span>{card.finish_line}</span>}
        {card.has_plan && <LevelBar levels={card.levels} />}
        {card.has_plan ? (
          <span className="flex items-baseline justify-between gap-2 whitespace-nowrap text-[12px]">
            {card.current ? <span className="truncate"><b>{t("projectsUI.level", { n: card.current.position })}</b>
              <span className="text-muted-foreground"> · {card.current.name}</span></span> : <span />}
            <span className={`font-semibold ${done ? "text-success" : "text-muted-foreground"}`}>
              {done || card.left === 0 ? t("projectsUI.allClear") : t("projectsUI.left", { count: card.left })}</span>
          </span>
        ) : <span className="text-[12px] text-subtle-foreground">{t("projectsUI.noPlan")}</span>}
        {card.current && days !== null && !done && (
          <span className="text-[11px] text-subtle-foreground">{t("projectsUI.dayIn", { days: days + 1 })}</span>)}
      </button>
      {!card.has_plan && <Button size="sm" onClick={onPlan} data-testid={`project-plan-${card.id}`}>{t("projectsUI.planIt")}</Button>}
      {p && (
        <div data-testid={`project-proposal-${card.id}`} className="flex flex-col gap-2 rounded-lg bg-info-soft p-2.5">
          <span className="flex gap-2 text-[12px] leading-snug">
            <span aria-hidden="true" className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${BAND_DOT.doing}`} />
            <span>{p.last ? t("projectsUI.proposalLast", { evidence: evidenceText(t, p.evidence) })
              : t("projectsUI.proposalMove", { level: p.level, next: p.next ?? "", evidence: evidenceText(t, p.evidence) })}
              {p.moves_column ? ` ${t("projectsUI.proposalColumn")}` : ""}</span>
          </span>
          <span className="flex gap-1.5 pl-3.5">
            <Button size="sm" tone="primary" disabled={busy} onClick={() => onDecide(true)}
              data-testid={`project-accept-${card.id}`}>{t(p.last ? "projectsUI.gotIt" : "projectsUI.accept")}</Button>
            {!p.last && <Button size="sm" disabled={busy} onClick={() => onDecide(false)}
              data-testid={`project-decline-${card.id}`}>{t("projectsUI.decline")}</Button>}
          </span>
        </div>
      )}
    </article>
  );
}
