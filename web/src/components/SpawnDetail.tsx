import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../api/client";
import type { EvolveRepeatRefusal } from "../api/client";
import type { EvolveEstimate, KnowledgeSource } from "../api/client.types";

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
  const [estimate, setEstimate] = useState<EvolveEstimate | null>(null);
  const [enqueued, setEnqueued] = useState<string | null>(null);
  // the spend gate reaches this surface too — see enqueueEvolve
  const [refusal, setRefusal] = useState<EvolveRepeatRefusal | null>(null);

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

  // Evolution is a background job now (spec §E5/E7): show the honest cost estimate first,
  // then enqueue. The gate + human promotion happen on the "进化" inbox card, not here.
  async function loadEstimate() {
    setBusy(true);
    setError(null);
    setEnqueued(null);
    try {
      setEstimate(await api.getEvolveEstimate(spawnId));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function enqueueEvolve(force = false) {
    setBusy(true);
    setError(null);
    try {
      const res = await api.runEvolve(spawnId, { force });
      setRefusal(null);
      setEnqueued(
        res.attempt_id != null
          ? t("evolution.inbox.enqueued", { id: res.attempt_id })
          : t("evolution.inbox.already_running"),
      );
      setEstimate(null);
    } catch (e) {
      // This is the SECOND enqueue surface. It gets the server's fail-closed gate whether
      // or not it handles it, so without this branch its Evolve button became an
      // unrecoverable dead end: a raw "same_corpus_as_failed_attempt" in the error slot
      // and no way to proceed. Same rule as the inbox — render the SERVER's facts.
      if (e instanceof ApiError && e.status === 409 && e.detail) {
        setRefusal(e.detail as EvolveRepeatRefusal);
      } else {
        setError(String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="spawn-detail" data-testid="spawn-detail">
      <header className="spawn-detail__head">
        <span className="spawn-detail__title">{spawnName}</span>
        <button className="spawn-detail__close" onClick={onClose} aria-label="close">✕</button>
      </header>

      {error && <div className="spawn-detail__error" role="alert">{error}</div>}

      <section className="spawn-detail__section">
        <h4>{t("spawn.knowledge_panel")}</h4>
        {sources.length === 0 ? (
          <p className="spawn-detail__empty">{t("spawn.knowledge_none")}</p>
        ) : (
          <ul className="kb-list">
            {sources.map((s) => (
              <li key={s.source} className="kb-list__row">
                <span className="kb-list__src">{s.source}</span>
                <span className="kb-list__count">{t("spawn.chunks_n", { n: s.chunks })}</span>
                <button className="kb-list__del" disabled={busy}
                        onClick={() => removeSource(s.source)}>{t("spawn.delete_short")}</button>
              </li>
            ))}
          </ul>
        )}
        <div className="kb-add">
          <input className="kb-add__url" placeholder={t("spawn.url_placeholder")} value={url}
                 onChange={(e) => setUrl(e.target.value)} />
          <input className="kb-add__label" placeholder={t("spawn.label_placeholder")} value={label}
                 onChange={(e) => setLabel(e.target.value)} />
          <textarea className="kb-add__text" placeholder={t("spawn.text_placeholder")} value={text}
                    onChange={(e) => setText(e.target.value)} />
          <label className="kb-add__compress">
            <input type="checkbox" checked={compress} onChange={(e) => setCompress(e.target.checked)} />
            {t("spawn.llm_compress")}
          </label>
          <div className="kb-add__actions">
            <button disabled={busy} onClick={addUrl}>{t("spawn.fetch")}</button>
            <button disabled={busy} onClick={addText}>{t("spawn.add_text")}</button>
            <label className="kb-add__file">
              {t("spawn.upload_file")}
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
        <h4>{t("evolution.inbox.tab")}</h4>
        <p className="spawn-detail__empty">{t("evolution.inbox.spawn_hint")}</p>
        <button className="evo-propose" disabled={busy} onClick={loadEstimate}>
          {t("evolution.inbox.estimate_title")}
        </button>
        {estimate && (
          <div className="evo-result">
            <div className="evo-counts">
              {t("evolution.card.estimate_line", {
                judge: estimate.judge_calls_max ?? estimate.judge_calls,
                dispatches: estimate.dispatches_max ?? estimate.dispatches,
              })}
            </div>
            <div className="evo-counts">
              {t("evolution.inbox.estimate_detail", {
                pairs: estimate.pairs,
                dispatches: estimate.dispatches_max ?? estimate.dispatches,
              })}
            </div>
            {/* Only when a projection exists. Null means the `actual` ledger is empty —
                rendering 0 there would read as "free", the failure this round exists to
                end. Absent is the honest presentation of unknown. */}
            {estimate.tokens_projected != null && (
              <div data-testid="estimate-tokens">
                {t("evolution.card.estimate_tokens", { tokens: estimate.tokens_projected })}
              </div>
            )}
            <button className="evo-confirm" disabled={busy} onClick={() => enqueueEvolve(false)}>
              {t("evolution.inbox.enqueue")}
            </button>
          </div>
        )}
        {refusal && (
        <div className="evo-refusal" role="alertdialog" data-testid="sd-repeat-confirm">
          <div className="evo-refusal__title">{t("evolution.inbox.confirm_title")}</div>
          <div className="evo-refusal__body">
            {t("evolution.inbox.confirm_body", {
              id: refusal.last_attempt_id,
              reason: refusal.last_reason,
            })}
          </div>
          {refusal.est_dispatches_max != null && (
            <div className="evo-refusal__body">
              {t("evolution.inbox.confirm_cost", { dispatches: refusal.est_dispatches_max })}
            </div>
          )}
          <div className="evo-refusal__actions">
            <button onClick={() => setRefusal(null)} data-testid="sd-repeat-cancel">
              {t("evolution.inbox.confirm_cancel")}
            </button>
            <button
              className="evo-confirm"
              disabled={busy}
              onClick={() => enqueueEvolve(true)}
              data-testid="sd-repeat-force"
            >
              {t("evolution.inbox.confirm_run")}
            </button>
          </div>
        </div>
      )}
      {enqueued && <div className="evo-promoted">{enqueued}</div>}
      </section>
    </div>
  );
}
