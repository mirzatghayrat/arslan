import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { Advisory, CapabilityCard, Severity } from "../../api/client.types";
import { Escaped, isolate } from "../../lib/outsideText";
import { Row } from "./CapabilityProposeCard";

/** An advisory's page on OSV.dev. Built from a fixed prefix: an id may hold a colon (`RHSA-2023:1234`), so it is never
 *  used as a link on its own (#661 review). */
export const osvLink = (id: string) => `https://osv.dev/vulnerability/${encodeURIComponent(id)}`;

function Advisories({ list }: { list: Advisory[] }) {
  const { t } = useTranslation();
  return <>{list.map(a => (
    <span key={a.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 text-[12px]" data-testid="vuln-advisory">
      <a href={osvLink(a.id)} target="_blank" rel="noopener noreferrer" className="font-mono underline"><Escaped text={a.id} /></a>
      <span className={a.severity === "CRITICAL" || a.severity === "HIGH" ? "font-semibold text-danger" : "text-muted-foreground"}>
        {t(`discover.sev_${a.severity}`)}</span>
      {a.summary ? <span className="text-muted-foreground"><Escaped text={a.summary} /></span> : <span />}
      <span className="text-muted-foreground">{!a.loaded ? t("discover.card_vulnNotLoaded")
        : a.fixed.length ? t("discover.card_vulnFixed", { versions: a.fixed.join(", ") }) : t("discover.card_vulnNoFix")}</span>
    </span>))}</>;
}

/**
 * CAP9's row on the install card (the board the user OK'd, 2026-11-02): what OSV.dev knows of every locked package, the
 * package itself first. "Not checked" never reads as "none known". The facts come from the server
 * (`osv_check.check`); the card's buttons for a hit in the package itself are the install card's own.
 */
export function SecurityRow({ card }: { card: CapabilityCard }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const v = card.vulns;
  if (card.kind === "skill") {
    return <Row label={t("discover.card_security")} testId="capability-card-security">{t("discover.card_vulnSkill")}</Row>;
  }
  if (!v) return null;
  if (v.state === "skipped") {
    const why = v.why === "remote" ? "card_vulnRemote" : v.why === "bundle" ? "card_vulnBundle"
      : v.why === "no_lock" ? "card_vulnNoLock" : "card_vulnNotChecked";
    return <Row label={t("discover.card_security")} testId="capability-card-security">{t(`discover.${why}`)}</Row>;
  }
  if (v.state === "not_checked") {
    return <Row label={t("discover.card_security")} testId="capability-card-security">
      <span className="flex flex-col gap-1">
        <span className="text-ask" data-testid="vuln-not-checked">
          {t(v.why === "empty_lock" ? "discover.card_vulnEmptyLock" : "discover.card_vulnNotChecked")}</span>
        <span className="text-[12px] text-muted-foreground">{t("discover.card_vulnStillApply")}</span>
      </span>
    </Row>;
  }
  // #661 max review: the counts include what the lists leave out, and the package's own worst is told apart from
  // its dependencies'.
  const sev = (s: Severity | null) => (s ? t(`discover.sev_${s}`) : "");
  const ownCount = v.own.length + v.own_more;
  const depCount = v.count - ownCount;
  const name = isolate(card.name);
  const part = v.asked < v.packages;
  return (
    <Row label={t("discover.card_security")} testId="capability-card-security">
      <span className="flex flex-col gap-1.5">
        {v.count === 0 ? <span data-testid="vuln-summary">
          {part ? t("discover.card_vulnNonePart", { count: v.asked }) : t("discover.card_vulnNone", { count: v.packages })}</span>
          : <span data-testid="vuln-summary" className={ownCount ? "font-semibold text-danger" : "text-ask"}>
            {ownCount ? t("discover.card_vulnOwn", { name, count: ownCount, severity: sev(v.own_highest) })
              : t("discover.card_vulnDeps", { name, count: depCount, severity: sev(v.deps_highest) })}</span>}
        {ownCount > 0 && depCount > 0 && <span className="text-ask" data-testid="vuln-also-deps">
          {t("discover.card_vulnAlsoDeps", { count: depCount, severity: sev(v.deps_highest) })}</span>}
        {v.count > 0 && <>
          <button type="button" data-testid="vuln-toggle" aria-expanded={open} onClick={() => setOpen(!open)}
            className="self-start text-[12px] text-primary hover:underline">
            {t(open ? "discover.card_vulnHide" : "discover.card_vulnShow")}</button>
          <span hidden={!open} data-testid="vuln-list" className="flex flex-col gap-2 rounded-lg border border-border bg-background px-2.5 py-2">
            <Advisories list={v.own} />
            {v.own_more > 0 && <span className="text-[12px] text-muted-foreground">{t("discover.card_vulnMore", { count: v.own_more })}</span>}
            {v.deps.map(d => <span key={`${d.name}@${d.version}`} className="flex flex-col gap-1" data-testid="vuln-dep">
              <span className="font-mono text-[12px]"><Escaped text={`${d.name} ${d.version}`} />
                {d.alias ? <span className="text-muted-foreground"> (<Escaped text={d.alias} />)</span> : null}</span>
              <Advisories list={d.advisories} />
              {d.more > 0 && <span className="text-[12px] text-muted-foreground">{t("discover.card_vulnMore", { count: d.more })}</span>}
            </span>)}
            {v.deps_more > 0 && <span className="text-[12px] text-muted-foreground" data-testid="vuln-more-deps">
              {t("discover.card_vulnMoreDeps", { count: v.deps_more })}</span>}
          </span>
        </>}
        {!v.complete && <span className="text-[12px] text-ask" data-testid="vuln-incomplete">{t("discover.card_vulnIncomplete")}</span>}
        <span className="text-[12px] text-muted-foreground" data-testid="vuln-asked">
          {part ? t("discover.card_vulnAskedPart", { asked: v.asked, count: v.packages })
            : t("discover.card_vulnAsked", { count: v.packages })}</span>
      </span>
    </Row>
  );
}

/** Whether the package being installed has a known vulnerability of its own (the user's question 5, as the board
 *  draws it: then "Don't install" is the safe answer and installing is a deliberate click). */
export const ownVulnerable = (card: CapabilityCard) => card.vulns?.state === "checked" && card.vulns.own.length > 0;
