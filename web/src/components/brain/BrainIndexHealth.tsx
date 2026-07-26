import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { EmbeddingStatus } from "../../api/client.types";

/** Slim embedding/index-health strip inside the Second Brain — active model,
 * embedded/pending chunk counts, and a reindex trigger. Brings the "索引健康"
 * that used to hide in Settings into the brain itself. Best-effort. */
export default function BrainIndexHealth() {
  const { t } = useTranslation();
  const [s, setS] = useState<EmbeddingStatus | null>(null);
  const [busy, setBusy] = useState(false);

  // 🔴 A failed status call used to be indistinguishable from "no status": both set null
  // and the whole strip returned null, so the panel VANISHED silently. Disappearing is a
  // claim too — the user reads it as "nothing to report".
  const [failed, setFailed] = useState(false);
  const load = () => {
    setFailed(false);
    api.embeddingStatus().then(setS).catch(() => { setS(null); setFailed(true); });
  };
  useEffect(() => { load(); }, []);

  if (failed) {
    return (
      <div className="brain-health" data-testid="brain-health">
        <span className="brain-health__meta brain-health__warn">
          {t("brain.health_unreadable")}
        </span>
      </div>
    );
  }
  if (!s) return null;

  const done = s.embedded ?? 0;
  // `embedded + pending` is only a real total when they are disjoint, and they are NOT:
  // with a provider active, `pending` counts NULL-or-stale rows and a stale row also
  // counts as embedded, so after a model switch the sum overshoots the corpus and the
  // bar reads about half of true progress. `total` is the real corpus size; fall back to
  // the old sum only when an older backend does not send it.
  const total = s.total ?? done + (s.pending ?? 0);
  // 🔴 `total ? … : 100` reported 100% on an install with ZERO chunks — a full green bar
  // for a brain that has nothing indexed, which is the most reassuring possible rendering
  // of the least reassuring possible state. An empty corpus has no percentage.
  const pct = total ? Math.round((done / total) * 100) : 0;
  const empty = total === 0;
  const running = s.reindex?.running;

  const reindex = async () => {
    setBusy(true);
    try { await api.reindexEmbeddings(); } catch { /* best-effort */ }
    finally { setBusy(false); setTimeout(load, 400); }
  };

  return (
    <div className="brain-health" data-testid="brain-health">
      <div className="brain-health__head">
        <span className="brain-health__title">{t("brain.index_health")}</span>
        <span className="brain-health__model">{s.model ?? t("brain.health_no_model")}</span>
      </div>
      {!s.model && (
        <div className="brain-health__meta" data-testid="fts-note">
          {t("brain.health_fts_note")}
        </div>
      )}
      <div className="brain-health__bar">
        <div className="brain-health__fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="brain-health__row">
        <span className="brain-health__meta" data-testid="brain-health-meta">
          {empty ? t("brain.health_empty") : t("brain.health_embedded", { done, total }) + (s.pending ? t("brain.health_pending_suffix", { n: s.pending }) : "")}
        </span>
        {running ? (
          <span className="brain-health__meta">{t("brain.health_rebuilding", { done: s.reindex.done, total: s.reindex.total })}</span>
        ) : s.pending ? (
          <button type="button" className="brain-health__reindex" disabled={busy} onClick={() => void reindex()}>
            {busy ? t("brain.health_starting") : t("brain.health_rebuild")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
