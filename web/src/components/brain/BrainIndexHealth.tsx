import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { EmbeddingStatus } from "../../api/client.types";

/** Slim embedding/index-health strip inside the Second Brain — active model,
 * embedded/pending chunk counts, and a reindex trigger. Brings the "索引健康"
 * that used to hide in Settings into the brain itself. Best-effort. */
export default function BrainIndexHealth() {
  const [s, setS] = useState<EmbeddingStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => { api.embeddingStatus().then(setS).catch(() => setS(null)); };
  useEffect(() => { load(); }, []);

  if (!s) return null;

  const done = s.embedded ?? 0;
  const total = done + (s.pending ?? 0);
  const pct = total ? Math.round((done / total) * 100) : 100;
  const running = s.reindex?.running;

  const reindex = async () => {
    setBusy(true);
    try { await api.reindexEmbeddings(); } catch { /* best-effort */ }
    finally { setBusy(false); setTimeout(load, 400); }
  };

  return (
    <div className="brain-health" data-testid="brain-health">
      <div className="brain-health__head">
        <span className="brain-health__title">索引健康</span>
        <span className="brain-health__model">{s.model ?? "未配置 · 纯 FTS"}</span>
      </div>
      <div className="brain-health__bar">
        <div className="brain-health__fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="brain-health__row">
        <span className="brain-health__meta">
          已嵌入 {done}/{total}{s.pending ? ` · ${s.pending} 待嵌` : ""}
        </span>
        {running ? (
          <span className="brain-health__meta">重建中 {s.reindex.done}/{s.reindex.total}</span>
        ) : s.pending ? (
          <button type="button" className="brain-health__reindex" disabled={busy} onClick={() => void reindex()}>
            {busy ? "启动中…" : "重建索引"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
