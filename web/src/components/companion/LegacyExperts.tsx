import { useEffect, useState } from "react";
import { Check, Wand2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../../api/client";

type Expert = { id: number; name: string; domain: string; skill_key: string; converted: boolean };

// 0.1.44 one Arslan: experts are no longer a runtime path. Each former expert can
// be turned into a skill (its prompt becomes the method Arslan reads when the
// work matches). Nothing is deleted here.
export default function LegacyExperts() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<Expert[] | null>(null);
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const [failed, setFailed] = useState<Record<number, string>>({});
  async function load() {
    try { setRows((await request<{ experts: Expert[] }>("/experts/legacy")).experts); }
    catch { setRows([]); }
  }
  useEffect(() => { void load(); }, []);
  async function convert(id: number) {
    try {
      await request(`/experts/${id}/to-skill`, { method: "POST" });
      setFailed(old => { const next = { ...old }; delete next[id]; return next; });
    } catch (error) {
      setFailed(old => ({ ...old, [id]: String((error as Error).message || "failed") }));
    }
  }
  async function convertOne(id: number) { setBusy(id); await convert(id); await load(); setBusy(null); }
  async function convertAll() {
    setBusy("all");
    for (const row of rows ?? []) if (!row.converted) await convert(row.id);
    await load(); setBusy(null);
  }
  if (rows === null) return <p className="text-sm text-muted-foreground">{t("companion.loading")}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground" data-testid="legacy-empty">{t("workspace.legacyExpertsNone")}</p>;
  const pending = rows.filter(row => !row.converted).length;
  return <section data-testid="legacy-experts" className="space-y-4 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-4">
      <p className="max-w-2xl text-muted-foreground">{t("workspace.legacyExpertsHint")}</p>
      {pending > 0 && <button type="button" disabled={busy !== null} onClick={() => void convertAll()}
        className="rounded-lg border border-border px-3 py-2 hover:border-primary disabled:opacity-50">{t("workspace.convertAll", { count: pending })}</button>}
    </div>
    <ul className="divide-y divide-border rounded-lg border border-border">{rows.map(row => <li key={row.id} className="flex items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1"><div className="font-medium">{row.name}</div>
        <div className="text-xs text-muted-foreground">{row.domain}</div>
        {failed[row.id] && <div role="status" className="text-xs text-danger">{t("workspace.convertFailed")}</div>}</div>
      {row.converted
        ? <span className="inline-flex items-center gap-1 text-xs text-success" data-testid={`converted-${row.id}`}><Check size={13} />{t("workspace.converted")}</span>
        : <button type="button" disabled={busy !== null} onClick={() => void convertOne(row.id)} data-testid={`to-skill-${row.id}`}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:border-primary disabled:opacity-50">
            <Wand2 size={12} />{t("workspace.toSkill")}</button>}
    </li>)}</ul>
  </section>;
}
