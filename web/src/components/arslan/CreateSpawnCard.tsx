import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { SuggestDraft } from "../../types";

export default function CreateSpawnCard({
  draft,
  onCreate,
  onDismiss,
}: {
  draft: SuggestDraft;
  onCreate: (draft: SuggestDraft) => void;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="mx-auto max-w-[75%] rounded-2xl border border-amber/30 bg-amber/5 p-4">
      <p className="mb-2 font-medium text-amber">{t("create_card.heading", { name: draft.name })}</p>
      <dl className="space-y-1 text-sm text-white/80">
        <div>
          <span className="text-white/40">{t("create_card.domain")}: </span>
          {draft.domain}
        </div>
        <div>
          <span className="text-white/40">{t("create_card.capabilities")}: </span>
          {draft.capabilities.join(", ")}
        </div>
        {draft.reason && (
          <div>
            <span className="text-white/40">{t("create_card.reason")}: </span>
            {draft.reason}
          </div>
        )}
      </dl>
      <div className="mt-3 flex gap-2">
        <button
          onClick={() => onCreate(draft)}
          className="rounded-lg bg-amber px-4 py-1.5 text-sm font-medium text-black"
        >
          {t("create_card.create")}
        </button>
        <button
          onClick={() => navigate("/build", { state: { draft } })}
          className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10"
        >
          {t("create_card.tweak")}
        </button>
        <button onClick={onDismiss} className="rounded-lg px-4 py-1.5 text-sm text-white/60 hover:bg-white/10">
          {t("create_card.dismiss")}
        </button>
      </div>
    </div>
  );
}
