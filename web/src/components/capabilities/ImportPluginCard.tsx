import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { CapabilityCard, ImportPluginCard as Card } from "../../api/client.types";
import { Escaped, isolate } from "../../lib/outsideText";
import { Button } from "../kit";
import { Row } from "./CapabilityProposeCard";
import { HooksRow } from "./HooksRow";
import { PluginContains } from "./PluginContains";
import { SecurityRow } from "./SecurityRow";

/** CAP7b's parts take the install card's shape; an imported plugin has no repository, stars or license to show. */
const asCapabilityCard = (card: Card): CapabilityCard => ({
  kind: "plugin", name: card.name, summary: card.summary, source_url: null, repo: null, version: null, license: card.license,
  stars: null, pushed_days: null, runtime: "plugin", runtime_download: null, remote_host: null, network: false,
  folders: [], keys: card.keys, why: "", retry: "", publisher: card.publisher, commit: card.commit, skills: card.skills,
  connections: card.connections });

/**
 * A plugin's card on the Import sheet (v0.1.64 CAP8-2, board 7): CAP7b's rows (what it does, what it contains, what
 * OSV.dev knows of its locks), with where Claude Code got it and, by the user's hook rule, each hook's event and that
 * it won't run. Shown after the other picks went in; "Add plugin" sends back this card's digest, "Skip this one" sends
 * nothing. A key typed here goes only with this plugin's add.
 */
export default function ImportPluginCard({ card, n, total, others, busy, onAdd, onSkip }: {
  card: Card; n: number; total: number; others: boolean; busy: boolean;
  onAdd: (keys: Record<string, string>) => void; onSkip: () => void;
}) {
  const { t } = useTranslation();
  const [keys, setKeys] = useState<Record<string, string>>({});
  const shaped = asCapabilityCard(card);
  const missing = card.keys.filter(k => k.required && !(keys[k.name] ?? "").trim());
  return <div data-testid="import-plugin-card" className="flex flex-col gap-2.5">
    <span className="text-[12px] text-muted-foreground">{t("capabilityList.import_cardOf", { n, total })}</span>
    <h2 className="text-[16px] font-semibold">{t("capabilityList.import_cardTitle", { name: isolate(card.name) })}</h2>
    <span className="text-[13px] text-muted-foreground">
      {others && <>{t("capabilityList.import_cardOthers")} </>}{t("capabilityList.import_cardIntro")}</span>
    <div className="flex flex-col">
      <Row label={t("discover.card_does")}><Escaped text={card.summary || card.name} /></Row>
      <Row label={t("discover.card_source")} testId="capability-card-source">
        {card.from ? t("capabilityList.import_cardSource", { from: isolate(card.from) }) : t("capabilityList.import_cardSourceSkills")}
      </Row>
      <Row label={t("discover.card_contains")} testId="capability-card-contains"><PluginContains card={shaped} /></Row>
      <HooksRow hooks={card.hooks} kind="plugin" />
      <SecurityRow card={shaped} />
      <Row label={t("discover.card_checks")}>{t("capabilityList.import_cardChecks")}</Row>
      {card.keys.length > 0 && <Row label={t("discover.card_needs")}>
        <span className="flex flex-col gap-1.5">
          {card.keys.map(k => <label key={k.name} className="flex flex-col gap-0.5">
            <span className="font-mono text-[11.5px]">{k.name}{k.required ? " *" : ""}</span>
            <input type="password" autoComplete="off" value={keys[k.name] ?? ""} data-testid={`capability-key-${k.name}`}
              onChange={e => setKeys({ ...keys, [k.name]: e.target.value })}
              className="rounded-lg border border-border bg-background px-2 py-1 text-[12.5px]" />
          </label>)}
          <span className="text-[11.5px] text-muted-foreground">{t("discover.card_keyNote")}</span>
        </span>
      </Row>}
    </div>
    <div className="flex flex-wrap items-center gap-2.5 pt-1">
      <Button tone="primary" data-testid="import-card-add" disabled={busy || missing.length > 0}
        onClick={() => onAdd(Object.fromEntries(Object.entries(keys).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v)))}>
        {t("capabilityList.import_cardAdd")}</Button>
      <Button data-testid="import-card-skip" disabled={busy} onClick={onSkip}>{t("capabilityList.import_cardSkip")}</Button>
    </div>
    <span className="text-[11px] text-subtle-foreground">{t("capabilityList.import_cardFoot")}</span>
  </div>;
}
