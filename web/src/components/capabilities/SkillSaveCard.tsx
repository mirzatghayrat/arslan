import { useTranslation } from "react-i18next";
import type { AuthoredSkillCard } from "../../api/client.types";
import { AskCard, type AskQueuePosition } from "../kit";
import { Escaped, isolate } from "../../lib/outsideText";
import { Row } from "./CapabilityProposeCard";

/**
 * "Arslan 想存一个技能" (v0.1.64 CAP2a): the SKILL.md the model wrote for a way of working the user
 * asked to keep, shown whole (it scrolls inside its box) and as plain text, never rendered: what is
 * read here is exactly what is saved. A yes saves it, on at once; a no or no answer saves nothing.
 * The install card's channel: answered only in this window.
 */
export default function SkillSaveCard({ card, callId, expiresAt, queue, onConfirm, onCancel }: {
  card: AuthoredSkillCard; callId: string; expiresAt?: number | null; queue?: AskQueuePosition;
  onConfirm: (callId: string) => void;
  onCancel: (callId: string) => void;
}) {
  const { t } = useTranslation();
  const detail = (
    <div className="flex flex-col" data-testid="skill-save-rows">
      <Row label={t("discover.save_purpose")}><Escaped text={card.description} /></Row>
      <Row label={t("discover.save_key")}>
        <span className="rounded-md bg-fill px-1.5 py-0.5 font-mono text-[11.5px]">{card.key}</span>
      </Row>
      <Row label={t("discover.save_body")}>
        <pre data-testid="skill-save-body"
          className="m-0 max-h-[190px] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface-raised px-2.5 py-2 font-mono text-[11.5px] leading-normal [overflow-wrap:anywhere]">
          {/* UNI1: the text as stored; a bidi control shows as a marker, never reorders what is read. */}
          <Escaped text={card.body} block />
        </pre>
        {/* #472 review F5: how much there is, so a long text is read to its end. */}
        <span data-testid="skill-save-lines" className="mt-1 block text-[11px] text-subtle-foreground">
          {t("discover.save_lines", { count: card.body.replace(/\n$/, "").split("\n").length })}
        </span>
      </Row>
      <Row label={t("discover.save_what")}>{t("discover.save_whatText")}</Row>
    </div>
  );
  return (
    <AskCard testId="skill-save-card" who={t("discover.save_who")} title={t("discover.save_title", { name: isolate(card.name) })}
      said={card.why || null} risk={card.outside ? t("discover.save_outside") : null} detail={detail}
      extra={<span className="text-[11px] text-subtle-foreground">{t("discover.save_footer")}</span>}
      expiresAt={expiresAt} queue={queue}
      allowLabel={t("discover.save_allow")} declineLabel={t("discover.save_decline")}
      allowTestId="skill-save-allow" declineTestId="skill-save-decline"
      onAllow={() => onConfirm(callId)} onDecline={() => onCancel(callId)} />
  );
}
