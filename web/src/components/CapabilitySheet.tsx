import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { capabilitiesApi, type CapabilityRow, type CapabilitySource } from "../api/capabilities";
import { professionalMethodsApi, type ProfessionalMethod } from "../api/professionalMethods";
import McpServers from "./McpServers";
import { SourceDossier } from "./capabilities/AddedCapabilities";
import { MethodEditor } from "./companion/ProfessionalMethods";
import { Button, Dialog, Notice, Tag } from "./kit";

/**
 * One row's details on the Capabilities list (v0.1.64 CAP3a, the mock the user approved): what it does, where
 * it came from, when it was last used. Also, by kind:
 * - a method: its version, and the editor;
 * - something installed from a card: its dossier;
 * - a connection: its card (sign in, connect, tools). "MCP" is named only here.
 * Delete only on a `deletable` row; the server refuses the rest too.
 */
export default function CapabilitySheet({ row, name, what, used, error, onClose, onDelete, onChanged }: {
  row: CapabilityRow; name: string; what: string; used: string;
  /** A failed delete, said here: the list behind the sheet cannot be seen (#500 review). */
  error?: string | null;
  onClose: () => void; onDelete: (row: CapabilityRow) => void; onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [method, setMethod] = useState<ProfessionalMethod | null>(null);
  const [source, setSource] = useState<CapabilitySource | null>(null);
  const [failed, setFailed] = useState(false);
  const kind = row.section === "connections" ? "mcp" : row.section === "skills" ? "skill" : "builtin";
  const server = row.key.startsWith("mcp:") ? Number(row.key.slice(4)) : undefined;
  async function open<T>(load: () => Promise<T>, show: (value: T) => void) {
    setFailed(false);
    try { show(await load()); } catch { setFailed(true); }
  }
  const line = (label: string, value: ReactNode, testId: string) => (
    <div data-testid={testId} className="flex gap-3 border-t border-border py-2 text-[13px] first:border-t-0">
      <span className="w-36 shrink-0 text-muted-foreground">{label}</span><span className="min-w-0 flex-1">{value}</span>
    </div>);
  const link = (label: string, testId: string, onClick: () => void) => (
    <button type="button" data-testid={testId} className="underline hover:text-foreground" onClick={onClick}>{label}</button>);
  return <Dialog open onClose={onClose} width={600} testId="cap-sheet" padded
    title={<span className="flex items-center gap-2"><Tag>{t(`capabilityList.kind_${kind}`)}</Tag><bdi>{name}</bdi></span>}>
    <div className="flex flex-col gap-4">
      <div>
        {what && line(t("capabilityList.sheetWhat"), <bdi>{what}</bdi>, "cap-sheet-what")}
        {line(t("capabilityList.sheetOrigin"), <>{t(`capabilityList.origin_${row.origin}`)}
          {row.source_id && <> · {link(t("capabilityList.sheetDossier"), "cap-sheet-dossier",
            () => void open(() => capabilitiesApi.source(row.source_id!), setSource))}</>}</>, "cap-sheet-origin")}
        {line(t("capabilityList.sheetLastUsed"), used, "cap-sheet-used")}
        {row.revision !== undefined && line(t("capabilityList.sheetVersion"), <>
          {t("capabilityList.versionNumber", { number: row.revision })} · {link(t("capabilityList.sheetEdit"), "cap-sheet-edit",
            () => void open(professionalMethodsApi.list, all => setMethod(all.find(m => `method:${m.key}` === row.key) ?? null)))}
        </>, "cap-sheet-version")}
      </div>
      {failed && <p role="alert" className="text-[12px] text-danger-strong">{t("capabilityList.loadFailed")}</p>}
      {error && <Notice tone="error" role="alert" testId="cap-sheet-error">{error}</Notice>}
      {server !== undefined && <McpServers only={server} onChanged={onChanged} />}
      {row.origin === "builtin" && row.switch !== null &&
        <p className="text-[12px] text-subtle-foreground" data-testid="cap-sheet-builtin">{t("capabilityList.builtinHint")}</p>}
      {row.deletable && <div className="flex justify-end border-t border-border pt-3">
        <Button size="sm" tone="destructive" data-testid="cap-sheet-delete" onClick={() => onDelete(row)}>
          {t("capabilityList.delete")}</Button></div>}
    </div>
    {method && <MethodEditor method={method} onClose={() => setMethod(null)}
      onSaved={() => { setMethod(null); onChanged(); }} />}
    {source && <SourceDossier source={source} onClose={() => setSource(null)} onChanged={onChanged} />}
  </Dialog>;
}
