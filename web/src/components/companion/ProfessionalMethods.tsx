import { useEffect, useState } from "react";
import { BookOpen, Pencil, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { professionalMethodsApi, type ProfessionalMethod } from "../../api/professionalMethods";
import CompanionDialog, { buttonClass, inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

export default function ProfessionalMethods() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ProfessionalMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<ProfessionalMethod | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setLoading(true); setError(null);
    professionalMethodsApi.list().then(value => { if (alive) setRows(value); })
      .catch(() => { if (alive) setError("brain.read_failed"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [refresh]);
  async function save() {
    if (!editing || busy || !name.trim() || !instructions.trim()) return;
    setBusy(true); setError(null);
    try {
      const updated = await professionalMethodsApi.revise(editing, name.trim(), instructions.trim());
      setRows(old => old.map(row => row.key === updated.key ? updated : row));
      setEditing(null);
    } catch (failure) { setError(companionError(failure)); }
    finally { setBusy(false); }
  }
  return <section className="relative mb-6 space-y-4 rounded-xl border border-border bg-surface/50 p-5 select-text">
    <div className="flex items-center justify-between gap-3"><h2 className="flex items-center gap-2 font-semibold"><BookOpen size={17} />{t("methods.title")}</h2>
      <button className={buttonClass} disabled={loading || busy} aria-label={t("companion.refresh")} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={14} /></button></div>
    <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{t("methods.intro")}</p>
    {loading && <p role="status">{t("companion.loading")}</p>}
    {error && !editing && <p role="alert" className="text-destructive">{t(error)}</p>}
    <div className="grid gap-3 md:grid-cols-3">{rows.map(row => <article key={row.key} className="flex flex-col gap-3 rounded-lg border border-border bg-background p-4">
      <h3 className="font-medium">{row.revision === 1 ? t(`methods.${row.key}`) : row.name}</h3>
      <p className="text-xs text-muted-foreground">{t("methods.version", { number: row.revision })}</p>
      <button className={`${buttonClass} mt-auto self-start`} onClick={() => { setEditing(row); setName(row.name); setInstructions(row.instructions); setError(null); }}>
        <Pencil size={14} />{t("methods.viewEdit")}</button>
    </article>)}</div>
    {editing && <CompanionDialog title={t("methods.viewEdit")} busy={busy} onClose={() => { setEditing(null); setError(null); }}>
      <form className="space-y-4" onSubmit={event => { event.preventDefault(); void save(); }}>
        <p className="text-sm text-muted-foreground">{t("methods.editHint")}</p>
        {error && <p role="alert" className="text-destructive">{t(error)}</p>}
        <label className="block text-sm">{t("methods.name")}<input className={`${inputClass} mt-1`} value={name} maxLength={120} disabled={busy} onChange={event => setName(event.target.value)} /></label>
        <label className="block text-sm">{t("methods.instructions")}<textarea className={`${inputClass} mt-1`} rows={10} value={instructions} maxLength={20000} disabled={busy} onChange={event => setInstructions(event.target.value)} /></label>
        <button type="submit" className={primaryClass} disabled={busy || !name.trim() || !instructions.trim()}>{t("methods.saveVersion")}</button>
      </form>
    </CompanionDialog>}
  </section>;
}
