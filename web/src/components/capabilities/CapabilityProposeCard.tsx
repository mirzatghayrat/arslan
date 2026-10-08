import { useState } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CapabilityCard } from "../../api/client.types";
import { AskCard, type AskQueuePosition } from "../kit";

const host = (url: string | null) => {
  try { return url ? new URL(url).host : ""; } catch { return url ?? ""; }
};

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="grid grid-cols-[64px_1fr] gap-2.5 border-b border-border py-2 text-[13px] leading-snug last:border-b-0" data-testid={testId}>
      <span className="text-muted-foreground">{label}</span><span className="min-w-0">{children}</span>
    </div>
  );
}

/**
 * "Arslan 想加一个能力" (0.1.57 §3.1, board Capability-Propose): what it does, where it comes
 * from, its license (read at the source), how it runs (sandbox, folders, network), what it
 * needs. "装上并重试" installs it pinned, scans and tests it, and only then switches it on;
 * Arslan then retries the step. A key typed here goes to the server with the answer, never to
 * the model. Answered only in this window.
 */
export default function CapabilityProposeCard({ card, callId, expiresAt, queue, onConfirm, onCancel }: {
  card: CapabilityCard; callId: string; expiresAt?: number | null; queue?: AskQueuePosition;
  onConfirm: (callId: string, keys: Record<string, string>, folders: string[]) => void;
  onCancel: (callId: string) => void;
}) {
  const { t } = useTranslation();
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [folders, setFolders] = useState<string[]>(card.folders);
  const missing = card.keys.filter(k => k.required && !(keys[k.name] ?? "").trim());
  const run = card.kind === "skill" ? t("discover.card_runSkill")
    : card.runtime === "remote" ? t("discover.card_runRemote", { host: host(card.remote_host) })
    : t(card.network ? "discover.card_runSandboxNet" : "discover.card_runSandbox");
  const detail = (
    <div className="flex flex-col" data-testid="capability-card-rows">
      <Row label={t("discover.card_does")}>{card.summary || card.name}</Row>
      <Row label={t("discover.card_source")}>
        {card.source_url ? <a href={card.source_url} target="_blank" rel="noopener noreferrer" className="underline">{card.repo ?? card.source_url}</a> : card.name}
        {card.stars != null && <span className="text-muted-foreground"> · ★ {card.stars}</span>}
        {card.pushed_days != null && <span className="text-muted-foreground"> · {t("discover.pushed", { count: card.pushed_days })}</span>}
        {card.version && <span className="text-muted-foreground"> · {card.version}</span>}
      </Row>
      <Row label={t("discover.card_license")} testId="capability-card-license">
        <span className="rounded-full bg-success/10 px-[7px] py-0.5 text-[11px] text-success">{card.license.spdx}</span>
        {card.license.read_from && <span className="text-muted-foreground"> {t("discover.lic_readFrom")}</span>}
      </Row>
      <Row label={t("discover.card_runs")} testId="capability-card-runs">
        {run}
        {card.runtime_download && <span className="block text-muted-foreground">
          {t("discover.card_download", { name: card.runtime_download.name, size: card.runtime_download.size_mb })}</span>}
        {folders.length > 0 && <span className="mt-1 flex flex-wrap gap-1">
          {folders.map(f => <span key={f} className="inline-flex items-center gap-1 rounded-md bg-fill px-1.5 py-0.5 font-mono text-[11.5px]">
            {f}<button type="button" aria-label={t("discover.card_dropFolder")} data-testid={`capability-folder-drop-${f}`}
              onClick={() => setFolders(folders.filter(x => x !== f))}><X size={11} /></button></span>)}
        </span>}
      </Row>
      <Row label={t("discover.card_checks")}>{t("discover.card_checksText")}</Row>
      {card.keys.length > 0 && <Row label={t("discover.card_needs")}>
        <span className="flex flex-col gap-1.5">
          {card.keys.map(k => <label key={k.name} className="flex flex-col gap-0.5">
            <span className="font-mono text-[11.5px]">{k.name}{k.required ? " *" : ""}</span>
            {k.description && <span className="text-[11.5px] text-muted-foreground">{k.description}</span>}
            <input type={k.secret ? "password" : "text"} autoComplete="off" value={keys[k.name] ?? ""}
              onChange={e => setKeys({ ...keys, [k.name]: e.target.value })} data-testid={`capability-key-${k.name}`}
              className="rounded-lg border border-border bg-background px-2 py-1 text-[12.5px]" />
          </label>)}
          <span className="text-[11.5px] text-muted-foreground">{t("discover.card_keyNote")}</span>
        </span>
      </Row>}
    </div>
  );
  return (
    <AskCard testId="capability-card" who={t("discover.card_who")}
      title={t(card.kind === "skill" ? "discover.card_titleSkill" : "discover.card_title", { name: card.name })}
      said={card.why || null} detail={detail}
      context={card.retry ? [{ text: t("discover.card_retry", { step: card.retry }) }] : undefined}
      extra={<span className="text-[11px] text-subtle-foreground">{t("discover.card_footer")}</span>}
      expiresAt={expiresAt} queue={queue} allowDisabled={missing.length > 0}
      allowLabel={t("discover.card_allow")} declineLabel={t("discover.card_decline")}
      allowTestId="capability-card-allow" declineTestId="capability-card-decline"
      onAllow={() => { if (!missing.length) onConfirm(callId, keys, folders); }}
      onDecline={() => onCancel(callId)} />
  );
}
