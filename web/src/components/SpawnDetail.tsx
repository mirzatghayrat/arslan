import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import type { EvolveProposal, KnowledgeSource } from "../api/client.types";

interface Props {
  spawnId: number;
  spawnName: string;
  onClose: () => void;
}

export default function SpawnDetail({ spawnId, spawnName, onClose }: Props) {
  const { t } = useTranslation();
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [prefs, setPrefs] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [compress, setCompress] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<EvolveProposal | null>(null);
  const [promoted, setPromoted] = useState<number | null>(null);

  async function loadSources() {
    try {
      setSources(await api.getKnowledge(spawnId));
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadPrefs() {
    try {
      const res = await api.getPreferences(spawnId);
      setPrefs(res.preferences);
    } catch (e) {
      setError(String(e));
    }
  }

  async function removePref(fact: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.deletePreference(spawnId, fact);
      setPrefs(res.preferences);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    loadSources();
    loadPrefs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spawnId]);

  async function addText() {
    if (!label.trim() || !text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.ingestKnowledgeText(spawnId, label.trim(), text, compress);
      setLabel("");
      setText("");
      await loadSources();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function addFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      await api.ingestKnowledgeFile(spawnId, file, compress);
      await loadSources();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function addUrl() {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.ingestKnowledgeUrl(spawnId, url.trim(), compress);
      setUrl("");
      await loadSources();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeSource(source: string) {
    setBusy(true);
    setError(null);
    try {
      await api.deleteKnowledge(spawnId, source);
      await loadSources();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function propose() {
    setBusy(true);
    setError(null);
    setPromoted(null);
    try {
      setProposal(await api.evolveSpawn(spawnId));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!proposal?.proposal_id) return;
    setBusy(true);
    try {
      const res = await api.confirmProposal(proposal.proposal_id);
      if (res.ok) setPromoted(res.generation_level ?? null);
      else setError(res.reason ?? "promote failed");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const agg = proposal?.gate.aggregate as
    | { overall?: { better: number; worse: number; tie: number } }
    | null
    | undefined;
  const overall = agg?.overall;

  return (
    <div className="spawn-detail" data-testid="spawn-detail">
      <header className="spawn-detail__head">
        <span className="spawn-detail__title">{spawnName}</span>
        <button className="spawn-detail__close" onClick={onClose} aria-label="close">✕</button>
      </header>

      {error && <div className="spawn-detail__error" role="alert">{error}</div>}

      <section className="spawn-detail__section">
        <h4>知识库</h4>
        {sources.length === 0 ? (
          <p className="spawn-detail__empty">还没喂过资料</p>
        ) : (
          <ul className="kb-list">
            {sources.map((s) => (
              <li key={s.source} className="kb-list__row">
                <span className="kb-list__src">{s.source}</span>
                <span className="kb-list__count">{s.chunks} 块</span>
                <button className="kb-list__del" disabled={busy}
                        onClick={() => removeSource(s.source)}>删</button>
              </li>
            ))}
          </ul>
        )}
        <div className="kb-add">
          <input className="kb-add__url" placeholder="网址 (https://…)" value={url}
                 onChange={(e) => setUrl(e.target.value)} />
          <input className="kb-add__label" placeholder="标签 (source)" value={label}
                 onChange={(e) => setLabel(e.target.value)} />
          <textarea className="kb-add__text" placeholder="粘贴要喂给它的文本…" value={text}
                    onChange={(e) => setText(e.target.value)} />
          <label className="kb-add__compress">
            <input type="checkbox" checked={compress} onChange={(e) => setCompress(e.target.checked)} />
            LLM 压缩
          </label>
          <div className="kb-add__actions">
            <button disabled={busy} onClick={addUrl}>抓取</button>
            <button disabled={busy} onClick={addText}>添加文本</button>
            <label className="kb-add__file">
              上传文件
              <input type="file" accept=".pdf,.docx,.txt,.md" style={{ display: "none" }}
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) addFile(f); }} />
            </label>
          </div>
        </div>
      </section>

      <section className="spawn-detail__section">
        <h4>{t("spawn.learned_prefs")}</h4>
        {prefs.length === 0 ? (
          <p className="spawn-detail__empty">{t("spawn.no_prefs")}</p>
        ) : (
          <ul className="pref-list">
            {prefs.map((p) => (
              <li key={p} className="pref-list__row">
                <span className="pref-list__text">{p}</span>
                <button className="pref-list__del" disabled={busy} aria-label="delete"
                        onClick={() => removePref(p)}>✕</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="spawn-detail__section">
        <h4>进化</h4>
        <button className="evo-propose" disabled={busy} onClick={propose}>提出进化提案</button>
        {proposal && (
          <div className="evo-result">
            <div className={`evo-badge evo-badge--${proposal.gate.passed ? "pass" : "fail"}`}>
              {proposal.gate.passed ? "通过" : "未通过"} · {proposal.gate.reason}
            </div>
            {overall && (
              <div className="evo-counts">
                更好 {overall.better} · 更差 {overall.worse} · 持平 {overall.tie}
              </div>
            )}
            {proposal.candidate_prompt && (
              <details className="evo-candidate">
                <summary>候选 system prompt</summary>
                <pre>{proposal.candidate_prompt.slice(0, 400)}{proposal.candidate_prompt.length > 400 ? "…" : ""}</pre>
              </details>
            )}
            {proposal.gate.passed && proposal.proposal_id != null && promoted == null && (
              <button className="evo-confirm" disabled={busy} onClick={confirm}>采纳</button>
            )}
            {promoted != null && <div className="evo-promoted">已采纳 · 第 {promoted} 代</div>}
          </div>
        )}
      </section>
    </div>
  );
}
