import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { capabilitiesApi, type CapabilityRow, type SkillFolderCard as Card } from "../../api/capabilities";
import { Escaped, isolate } from "../../lib/outsideText";
import { Button, Dialog, Notice } from "../kit";
import { Row } from "./CapabilityProposeCard";

/**
 * v0.1.64 CAP6a: the card before a skill from ~/.agents/skills is first used (another tool put it there), or after
 * its files changed since the last yes. CAP4's facts: the scan's findings first, the whole SKILL.md as plain text,
 * every file. It says the folder is shared by several tools. A yes approves exactly the files shown (the server
 * refuses one that changed since, or that the scan blocks); a no leaves it off.
 */
export default function SkillFolderCard({ card, onClose, onApproved }: {
  card: Card; onClose: () => void; onApproved: (row: CapabilityRow) => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const high = card.scan.findings.filter(f => f.level === "high");
  const blocked = card.scan.level === "blocked";
  async function allow() {
    setBusy(true); setError(null);
    try { onApproved(await capabilitiesApi.approveSkillFolder(card.key, card.digest)); }
    catch (failure) {
      const code = failure instanceof ApiError ? (failure.detail as { code?: string } | undefined)?.code : undefined;
      setError(t(code === "changed" ? "capabilityList.folderCard_changedAgain" : code === "blocked"
        ? "capabilityList.folderCard_blocked" : "capabilityList.failed"));
    } finally { setBusy(false); }
  }
  return <Dialog open onClose={onClose} width={640} testId="skill-folder-card" padded busy={busy}
    title={t(card.changed ? "capabilityList.folderCard_titleChanged" : "capabilityList.folderCard_title", { name: isolate(card.name) })}
    footer={<div className="flex justify-end gap-2">
      <Button onClick={onClose} disabled={busy} data-testid="skill-folder-decline">{t("capabilityList.folderCard_decline")}</Button>
      <Button tone="primary" onClick={() => void allow()} disabled={busy || blocked} data-testid="skill-folder-allow">
        {t("capabilityList.folderCard_allow")}</Button></div>}>
    <div className="flex flex-col gap-2">
      {/* The scan's high findings first, in red (CAP4). */}
      {high.length > 0 && <Notice tone="error" testId="skill-folder-findings">
        {t("capabilityList.folderCard_findings", { rules: [...new Set(high.map(f => f.rule))].join(", ") })}</Notice>}
      {error && <Notice tone="error" role="alert">{error}</Notice>}
      <div className="flex flex-col">
        <Row label={t("capabilityList.folderCard_from")} testId="skill-folder-origin">
          {t(card.origin === "other_tool" ? "capabilityList.origin_other_tool" : "capabilityList.origin_installed")}
          {card.changed && <span className="text-ask"> · {t("capabilityList.folderCard_changed")}</span>}
          <span className="block font-mono text-[11.5px] text-muted-foreground">{card.folder}</span>
        </Row>
        <Row label={t("discover.save_purpose")}><Escaped text={card.description} /></Row>
        <Row label={t("capabilityList.folderCard_files")} testId="skill-folder-files">
          <span className="flex flex-wrap gap-1">{card.files.map(f => <span key={f}
            className="rounded-md bg-fill px-1.5 py-0.5 font-mono text-[11.5px]">{f}</span>)}</span>
          {card.unscanned.length > 0 && <span className="mt-1 block text-[11.5px] text-ask">
            {t("capabilityList.folderCard_unscanned", { count: card.unscanned.length })}</span>}
        </Row>
        <Row label={t("discover.save_body")}>
          <pre data-testid="skill-folder-body"
            className="m-0 max-h-[220px] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface-raised px-2.5 py-2 font-mono text-[11.5px] leading-normal [overflow-wrap:anywhere]">
            <Escaped text={card.skill_md} block /></pre>
          {card.hidden.count > 0 && <Notice tone="warn" className="mt-1.5">{t("discover.save_hidden", { count: card.hidden.count })}</Notice>}
        </Row>
        {/* CAP6a: the folder is shared, so what is installed there, other tools may read and use. */}
        {card.shared_folder && <Row label={t("capabilityList.folderCard_where")} testId="skill-folder-shared">
          {t("capabilityList.sharedFolder")}</Row>}
      </div>
    </div>
  </Dialog>;
}
