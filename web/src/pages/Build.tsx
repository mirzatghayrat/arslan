import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import CreateSpawnCard from "../components/arslan/CreateSpawnCard";
import type { SuggestDraft } from "../types";

export default function Build() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const seeded = (location.state as { draft?: SuggestDraft } | null)?.draft ?? null;
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<SuggestDraft | null>(seeded);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doDraft = async () => {
    const d = description.trim();
    if (!d) return;
    setBusy(true); setError(null);
    try { setDraft(await api.draftSpawn(d)); }
    catch { setError(t("errors.server_error")); }
    finally { setBusy(false); }
  };

  const doCreate = async (d: SuggestDraft) => {
    const created = await api.createSpawn({
      name: d.name, domain: d.domain, capabilities: d.capabilities,
      persona_role: d.persona_role, persona_tone: d.persona_tone,
    });
    navigate(`/chat/${created.id}`);
  };

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-4 text-2xl font-semibold">{t("manual_create.title")}</h1>
      {error && <p className="mb-3 text-sm text-red-300">{error}</p>}
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder={t("manual_create.describe_placeholder")}
        className="h-28 w-full rounded-lg border border-white/15 bg-white/5 px-4 py-3"
      />
      <button onClick={() => void doDraft()} disabled={busy}
        className="mt-3 rounded-lg bg-amber px-5 py-2.5 font-medium text-black disabled:opacity-50">
        {busy ? t("manual_create.drafting") : t("manual_create.draft")}
      </button>

      {draft && (
        <div className="mt-6">
          <CreateSpawnCard
            draft={draft}
            onCreate={(d) => void doCreate(d)}
            onDismiss={() => setDraft(null)}
            onRefine={(instruction) => void (async () => {
              try { setDraft(await api.draftSpawn(`${description}\n\nRefine: ${instruction}`)); }
              catch { setError(t("errors.server_error")); }
            })()}
            onRouteToExisting={() => { /* manual create has no overlap routing */ }}
          />
        </div>
      )}
    </div>
  );
}
