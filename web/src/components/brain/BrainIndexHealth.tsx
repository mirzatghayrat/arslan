import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { EmbeddingStatus } from "../../api/client.types";

/** Slim embedding/index-health strip inside the Second Brain — active model,
 * embedded/pending chunk counts, and a reindex trigger. Brings the "索引健康"
 * that used to hide in Settings into the brain itself. Best-effort. */
export default function BrainIndexHealth() {
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
          读不到索引状态 — 这不代表索引没问题,只是这次没查到。
        </span>
      </div>
    );
  }
  if (!s) return null;

  const done = s.embedded ?? 0;
  const total = done + (s.pending ?? 0);
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
        <span className="brain-health__title">索引健康</span>
        <span className="brain-health__model">{s.model ?? "未配置 · 纯 FTS"}</span>
      </div>
      {!s.model && (
        <div className="brain-health__meta" data-testid="fts-note">
          纯 FTS 检索:中文长词召回可能偏弱。原始资料不会被改动。
        </div>
      )}
      <div className="brain-health__bar">
        <div className="brain-health__fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="brain-health__row">
        <span className="brain-health__meta" data-testid="brain-health-meta">
          {empty ? "还没有可索引的内容" : `已嵌入 ${done}/${total}${s.pending ? ` · ${s.pending} 待嵌` : ""}`}
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
