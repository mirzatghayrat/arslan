import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import type { OverlapInfo, SuggestDraft } from "../../types";

export default function CreateSpawnCard({
  draft,
  overlaps,
  onCreate,
  onDismiss,
  onRefine,
  onRouteToExisting,
}: {
  draft: SuggestDraft;
  overlaps?: OverlapInfo | null;
  onCreate: (draft: SuggestDraft, differentiation?: string) => void;
  onDismiss: () => void;
  onRefine: (instruction: string) => void;
  onRouteToExisting: (spawnId: number) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tweaking, setTweaking] = useState(false);
  const [tweakText, setTweakText] = useState("");
  const [creatingAnyway, setCreatingAnyway] = useState(false);
  const [diff, setDiff] = useState("");

  const submitTweak = () => {
    const v = tweakText.trim();
    if (v) onRefine(v);
    setTweakText("");
    setTweaking(false);
  };

  return (
    <div className="mx-auto max-w-[75%] rounded-2xl border border-amber/30 bg-amber/5 p-4">
      {overlaps && (
        <p className="mb-2 rounded-lg border border-amber/40 bg-amber/10 px-3 py-1.5 text-xs text-amber">
          {t("create_card.overlap_warning", { name: overlaps.name })}
        </p>
      )}
      <p className="mb-2 font-medium text-amber">{t("create_card.heading", { name: draft.name })}</p>
      <dl className="space-y-1 text-sm text-white/80">
        <div><span className="text-white/40">{t("create_card.domain")}: </span>{draft.domain}</div>
        <div><span className="text-white/40">{t("create_card.capabilities")}: </span>{draft.capabilities.join(", ")}</div>
        {draft.reason && <div><span className="text-white/40">{t("create_card.reason")}: </span>{draft.reason}</div>}
      </dl>

      {tweaking && (
        <input
          autoFocus
          value={tweakText}
          onChange={(e) => setTweakText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submitTweak()}
          placeholder={t("create_card.refine_placeholder")}
          className="mt-2 w-full rounded-lg bg-white/10 px-3 py-2 text-sm"
        />
      )}

      {creatingAnyway && (
        <input
          autoFocus
          value={diff}
          onChange={(e) => setDiff(e.target.value)}
          placeholder={t("create_card.differ_placeholder", { name: overlaps?.name ?? "", axis: overlaps?.axes?.[0] ?? "" })}
          className="mt-2 w-full rounded-lg bg-white/10 px-3 py-2 text-sm"
        />
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {overlaps && !creatingAnyway ? (
          <>
            <button onClick={() => onRouteToExisting(overlaps.spawn_id)} className="rounded-lg bg-amber px-4 py-1.5 text-sm font-medium text-black">
              {t("create_card.route_to", { name: overlaps.name })}
            </button>
            <button onClick={() => setCreatingAnyway(true)} className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10">
              {t("create_card.create_new")}
            </button>
          </>
        ) : (
          <button onClick={() => onCreate(draft, creatingAnyway ? diff.trim() || undefined : undefined)} className="rounded-lg bg-amber px-4 py-1.5 text-sm font-medium text-black">
            {t("create_card.create")}
          </button>
        )}
        <button onClick={() => (tweaking ? submitTweak() : setTweaking(true))} className="rounded-lg border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10">
          {t("create_card.tweak")}
        </button>
        <button onClick={() => navigate("/build", { state: { draft } })} className="rounded-lg px-4 py-1.5 text-sm text-white/60 hover:bg-white/10">
          {t("create_card.advanced")}
        </button>
        <button onClick={onDismiss} className="rounded-lg px-4 py-1.5 text-sm text-white/60 hover:bg-white/10">
          {t("create_card.dismiss")}
        </button>
      </div>
    </div>
  );
}
