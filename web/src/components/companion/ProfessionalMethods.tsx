import { useState } from "react";
import { useTranslation } from "react-i18next";
import { professionalMethodsApi, type ProfessionalMethod } from "../../api/professionalMethods";
import CompanionDialog, { inputClass, primaryClass } from "./CompanionDialog";
import { companionError } from "./errors";

/**
 * A professional method's editor: its name and instructions, saved as a new version. v0.1.64 CAP3a: the methods
 * are rows in the Capabilities list's skills section, and their details sheet opens this ("View or edit").
 */
export function MethodEditor({ method, onClose, onSaved }: {
  method: ProfessionalMethod; onClose: () => void; onSaved: (updated: ProfessionalMethod) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(method.name);
  const [instructions, setInstructions] = useState(method.instructions);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    if (busy || !name.trim() || !instructions.trim()) return;
    setBusy(true); setError(null);
    try { onSaved(await professionalMethodsApi.revise(method, name.trim(), instructions.trim())); }
    catch (failure) { setError(companionError(failure)); }
    finally { setBusy(false); }
  }
  return <CompanionDialog title={t("methods.viewEdit")} busy={busy} onClose={onClose}>
    <form className="space-y-4" onSubmit={event => { event.preventDefault(); void save(); }}>
      <p className="text-sm text-muted-foreground">{t("methods.editHint")}</p>
      <p className="text-xs text-muted-foreground">{t("methods.version", { number: method.revision })}</p>
      {error && <p role="alert" className="text-destructive">{t(error)}</p>}
      <label className="block text-sm">{t("methods.name")}<input className={`${inputClass} mt-1`} value={name} maxLength={120} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <label className="block text-sm">{t("methods.instructions")}<textarea className={`${inputClass} mt-1`} rows={10} value={instructions} maxLength={20000} disabled={busy} onChange={event => setInstructions(event.target.value)} /></label>
      <button type="submit" className={primaryClass} disabled={busy || !name.trim() || !instructions.trim()}>{t("methods.saveVersion")}</button>
    </form>
  </CompanionDialog>;
}
