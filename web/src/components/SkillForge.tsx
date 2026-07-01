import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Hammer, RefreshCcw, Plus, X, Check, Rocket, FlaskConical } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { SkillCandidate, SpawnSummary } from "../api/client.types";

// Skill Forge — the self-authored end of the skills library.
// A human (or Arslan) packages a method into a SKILL.md → candidate (observing) →
// evaluate against a real spawn's scored runs (gate) → the human promote gate makes
// it a LIVE assignable skill. Frontend-only, against existing /skills/* endpoints.
// 🔒 SKILL.md body is shown ONLY in a <textarea> (plain text), never rendered as HTML.

const MAX_BODY_BYTES = 15 * 1024;

type Notice = { kind: "ok" | "err"; text: string } | null;

function statusBadgeCls(status: string): string {
  switch (status) {
    case "promoted":
      return "bg-success/15 text-success border-success/30";
    case "proposed":
      return "bg-primary/15 text-primary border-primary/30";
    case "rejected":
      return "bg-surface-raised text-subtle-foreground border-border";
    default: // observing
      return "bg-warning/15 text-warning border-warning/30";
  }
}

export default function SkillForge() {
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<SkillCandidate[]>([]);
  const [spawns, setSpawns] = useState<SpawnSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  // Create-form state.
  const [form, setForm] = useState({ key: "", name: "", category: "", description: "", body: "" });
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formNotice, setFormNotice] = useState<string | null>(null);

  // Per-candidate action state.
  const [busyId, setBusyId] = useState<number | null>(null);
  const [evalTarget, setEvalTarget] = useState<Record<number, number>>({});
  const [rowNotice, setRowNotice] = useState<Record<number, Notice>>({});
  const [confirmPromote, setConfirmPromote] = useState<number | null>(null);

  const reload = async () => {
    try {
      setCandidates(await api.listSkillCandidates());
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    void reload();
    api.listSpawns().then(setSpawns).catch(() => setSpawns([]));
  }, []);

  const bodyBytes = new TextEncoder().encode(form.body).length;
  const bodyTooBig = bodyBytes > MAX_BODY_BYTES;
  const canSubmit =
    form.key.trim() && form.name.trim() && form.category.trim() &&
    form.description.trim() && form.body.trim() && !bodyTooBig;

  const handleForge = async () => {
    setCreating(true);
    setFormError(null);
    setFormNotice(null);
    try {
      const cand = await api.forgeSkill({
        key: form.key.trim(),
        name: form.name.trim(),
        category: form.category.trim(),
        description: form.description.trim(),
        body: form.body,
      });
      setForm({ key: "", name: "", category: "", description: "", body: "" });
      setFormNotice(t("forge.create.ok", { name: cand.name }));
      setCandidates((prev) => [cand, ...prev.filter((c) => c.id !== cand.id)]);
    } catch (e) {
      // 400 validation string is surfaced via ApiError.message.
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  const setRow = (id: number, n: Notice) => setRowNotice((prev) => ({ ...prev, [id]: n }));

  const handleEvaluate = async (id: number) => {
    const target = evalTarget[id];
    if (!target) {
      setRow(id, { kind: "err", text: t("forge.eval.pickTarget") });
      return;
    }
    setBusyId(id);
    setRow(id, null);
    try {
      const res = await api.evaluateSkillCandidate(id, { target_spawn_id: target });
      if (res.gate.passed) {
        setRow(id, { kind: "ok", text: t("forge.eval.passed", { reason: res.gate.reason }) });
      } else {
        setRow(id, { kind: "err", text: t("forge.eval.failed", { reason: res.gate.reason }) });
      }
      await reload();
    } catch (e) {
      setRow(id, { kind: "err", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusyId(null);
    }
  };

  const handlePromote = async (id: number) => {
    setBusyId(id);
    setRow(id, null);
    setConfirmPromote(null);
    try {
      const res = await api.promoteSkillCandidate(id);
      if (res.ok) {
        setRow(id, { kind: "ok", text: t("forge.promote.ok", { key: res.key ?? "" }) });
      } else {
        setRow(id, { kind: "err", text: res.reason ?? t("forge.promote.blocked") });
      }
      await reload();
    } catch (e) {
      // 409 lands here — surface its reason honestly.
      const msg = e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);
      setRow(id, { kind: "err", text: msg });
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (id: number) => {
    setBusyId(id);
    setRow(id, null);
    try {
      await api.rejectSkillCandidate(id);
      await reload();
    } catch (e) {
      setRow(id, { kind: "err", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusyId(null);
    }
  };

  const inputCls =
    "w-full bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-3 py-2 text-[11px] text-foreground placeholder-subtle-foreground";
  const labelCls = "text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest block mb-1";

  return (
    <div className="space-y-5 select-text">
      <p className="text-[10px] text-subtle-foreground font-sans">{t("forge.intro")}</p>

      {/* ── Create Skill form ─────────────────────────────────────────── */}
      <div className="bg-background border border-border-strong rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2">
          <Hammer className="w-3.5 h-3.5 text-primary" />
          <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest">
            {t("forge.create.title")}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div>
            <span className={labelCls}>{t("forge.fields.key")}</span>
            <input
              type="text"
              value={form.key}
              onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
              placeholder="my-method"
              autoComplete="off"
              className={`${inputCls} font-mono`}
            />
          </div>
          <div>
            <span className={labelCls}>{t("forge.fields.name")}</span>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="My Method"
              autoComplete="off"
              className={`${inputCls} font-sans`}
            />
          </div>
          <div>
            <span className={labelCls}>{t("forge.fields.category")}</span>
            <input
              type="text"
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              placeholder="research"
              autoComplete="off"
              className={`${inputCls} font-mono`}
            />
          </div>
          <div>
            <span className={labelCls}>{t("forge.fields.description")}</span>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder={t("forge.fields.descriptionHint")}
              autoComplete="off"
              className={`${inputCls} font-sans`}
            />
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <span className={`${labelCls} mb-0`}>{t("forge.fields.body")}</span>
            <span className={`text-[9px] font-mono ${bodyTooBig ? "text-danger" : "text-subtle-foreground"}`}>
              {(bodyBytes / 1024).toFixed(1)} / 15 KB
            </span>
          </div>
          <p className="text-[9.5px] text-subtle-foreground font-sans mb-1">{t("forge.fields.bodyHint")}</p>
          <textarea
            value={form.body}
            onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
            rows={10}
            spellCheck={false}
            placeholder={"---\nname: My Method\n---\n\n## Trigger\n\n## Decision rules\n- …"}
            className={`${inputCls} font-mono resize-y`}
          />
        </div>

        {formError && (
          <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-lg px-3 py-2 text-[11px] text-danger font-sans">
            <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{formError}</span>
          </div>
        )}
        {formNotice && !formError && (
          <div className="flex items-start gap-2 bg-success/15 border border-success/40 rounded-lg px-3 py-2 text-[11px] text-success font-sans">
            <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{formNotice}</span>
          </div>
        )}

        <button
          type="button"
          onClick={handleForge}
          disabled={creating || !canSubmit}
          className="px-4 py-2 bg-primary hover:opacity-90 text-background text-[11px] font-bold font-mono uppercase rounded-lg flex items-center gap-1.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {creating ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          <span>{t("forge.create.submit")}</span>
        </button>
      </div>

      {/* ── Candidates list ───────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span className="text-[9.5px] font-mono text-subtle-foreground uppercase tracking-widest">
          {t("forge.list.title", { count: candidates.length })}
        </span>
        <button
          type="button"
          onClick={() => reload()}
          className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1"
        >
          <RefreshCcw className="w-3 h-3" />
          <span>{t("forge.list.refresh")}</span>
        </button>
      </div>

      {listError && (
        <div className="flex items-start gap-2 bg-danger/15 border border-danger/40 rounded-lg px-3 py-2 text-[11px] text-danger font-sans">
          <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{listError}</span>
        </div>
      )}

      {candidates.length === 0 ? (
        <div className="text-center py-4 bg-background border border-dashed border-border rounded-xl">
          <span className="text-[10px] text-subtle-foreground font-mono">{t("forge.list.empty")}</span>
        </div>
      ) : (
        <div className="space-y-2">
          {candidates.map((c) => {
            const busy = busyId === c.id;
            const notice = rowNotice[c.id] ?? null;
            const rejected = c.status === "rejected";
            const promoted = c.status === "promoted";
            const canAct = c.status === "observing" || c.status === "proposed";
            return (
              <div
                key={c.id}
                className={`bg-background border border-border-strong rounded-xl px-4 py-3 space-y-2 ${rejected ? "opacity-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[12px] font-bold text-foreground">{c.name}</span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[9px] font-bold font-mono uppercase tracking-wider border ${statusBadgeCls(c.status)}`}>
                        {t(`forge.status.${c.status}`, c.status)}
                      </span>
                      <span className="text-[9.5px] font-mono text-subtle-foreground">{c.key}</span>
                    </div>
                    <p className="text-[11px] text-subtle-foreground mt-0.5">{c.description}</p>
                    <p className="text-[9px] font-mono text-subtle-foreground mt-1">
                      {c.category} · {c.source} · {new Date(c.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  {promoted && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-mono text-success shrink-0">
                      <Check className="w-3.5 h-3.5" />
                      {t("forge.status.liveLabel")}
                    </span>
                  )}
                </div>

                {canAct && (
                  <div className="flex items-center gap-2 flex-wrap pt-1">
                    <select
                      value={evalTarget[c.id] ?? ""}
                      onChange={(e) =>
                        setEvalTarget((prev) => ({ ...prev, [c.id]: Number(e.target.value) }))
                      }
                      className="bg-surface border border-border-strong focus:border-primary focus:outline-none rounded-lg px-2 py-1.5 text-[10px] text-foreground font-mono max-w-[160px]"
                    >
                      <option value="">{t("forge.eval.target")}</option>
                      {spawns.map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => handleEvaluate(c.id)}
                      disabled={busy}
                      className="px-3 py-1.5 bg-surface hover:bg-foreground/[0.04] border border-border hover:border-border-strong text-muted-foreground hover:text-foreground text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {busy ? <RefreshCcw className="w-3 h-3 animate-spin" /> : <FlaskConical className="w-3 h-3" />}
                      <span>{t("forge.eval.button")}</span>
                    </button>
                    {confirmPromote === c.id ? (
                      <span className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => handlePromote(c.id)}
                          disabled={busy}
                          className="px-3 py-1.5 bg-success hover:opacity-90 text-background text-[10px] font-bold font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50"
                        >
                          <Rocket className="w-3 h-3" />
                          <span>{t("forge.promote.confirm")}</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmPromote(null)}
                          className="px-2 py-1.5 text-subtle-foreground hover:text-foreground text-[10px] font-mono uppercase transition-colors"
                        >
                          {t("forge.promote.cancel")}
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmPromote(c.id)}
                        disabled={busy}
                        className="px-3 py-1.5 bg-success/10 hover:bg-success/20 border border-success/30 text-success text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                        title={t("forge.promote.hint")}
                      >
                        <Rocket className="w-3 h-3" />
                        <span>{t("forge.promote.button")}</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleReject(c.id)}
                      disabled={busy}
                      className="px-3 py-1.5 bg-danger/10 hover:bg-danger/20 border border-danger/30 text-danger text-[10px] font-mono uppercase rounded-lg transition-all flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <X className="w-3 h-3" />
                      <span>{t("forge.reject.button")}</span>
                    </button>
                  </div>
                )}

                {confirmPromote === c.id && (
                  <p className="text-[9.5px] text-subtle-foreground font-sans">{t("forge.promote.hint")}</p>
                )}

                {notice && (
                  <div
                    className={`flex items-start gap-2 rounded-lg px-3 py-2 text-[11px] font-sans border ${
                      notice.kind === "ok"
                        ? "bg-success/15 border-success/40 text-success"
                        : "bg-danger/15 border-danger/40 text-danger"
                    }`}
                  >
                    {notice.kind === "ok" ? <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <X className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
                    <span>{notice.text}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
