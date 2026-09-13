import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { recipeApi, type RecipeExecution, type RecipeSpec, type RecipeStep, type RecipeVersion } from "../api/recipes";
import RunReplay from "./RunReplay";

const control = "rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground disabled:opacity-40";
const button = control + " hover:border-primary transition-colors";

export default function RecipePanel({ spawns }: { spawns: { id: string; name: string }[] }) {
  const { t } = useTranslation();
  const [versions, setVersions] = useState<RecipeVersion[]>([]);
  const [executions, setExecutions] = useState<RecipeExecution[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [key, setKey] = useState("");
  const [draft, setDraft] = useState<RecipeSpec>({ name: "", max_parallel: 2, steps: [] });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [retry, setRetry] = useState<RecipeExecution | null>(null);
  const pendingStart = useRef<{ signature: string; key: string } | null>(null);

  const reload = useCallback(async () => {
    const [saved, runs] = await Promise.all([recipeApi.versions(), recipeApi.executions()]);
    setVersions(saved); setExecutions(runs); setError(false); setLoading(false);
  }, []);
  useEffect(() => { reload().catch(() => { setError(true); setLoading(false); }); }, [reload]);
  const running = executions.some(e => ["running", "queued"].includes(e.status));
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => reload().catch(() => setError(true)), 1500);
    return () => clearInterval(timer);
  }, [running, reload]);

  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(false);
    try { await operation(); await reload(); } catch { setError(true); }
    finally { setBusy(false); }
  }
  function editStep(index: number, update: Partial<RecipeStep>) {
    setDraft(d => ({ ...d, steps: d.steps.map((s, i) => i === index ? { ...s, ...update } : s) }));
  }
  function addStep() {
    let n = 1;
    while (draft.steps.some(s => s.key === `step${n}`)) n++;
    setDraft(d => ({ ...d, steps: [...d.steps, { key: `step${n}`, name: t("recipes.step_name", { n }),
      spawn_id: Number(spawns[0]?.id || 0), task: "", depends_on: [], requires_approval: false }] }));
  }
  function choose(version: RecipeVersion) {
    setSelected(version.id); setKey(version.key); setDraft(structuredClone(version.spec));
  }
  const valid = draft.name.trim() && draft.steps.length > 0
    && draft.steps.every(s => s.task.trim() && s.name.trim() && s.spawn_id > 0);

  return <section className="relative border border-border rounded-2xl bg-surface/70 p-5 mb-8 space-y-5 select-text" aria-label={t("recipes.title")}>
    <div><h2 className="text-lg font-semibold">{t("recipes.title")}</h2>
      <p className="text-sm text-muted-foreground mt-1 max-w-3xl">{t("recipes.description")}</p></div>
    {loading && <p role="status">{t("recipes.loading")}</p>}
    {error && <div role="alert" className="text-danger flex gap-3 items-center"><span>{t("recipes.operation_failed")}</span>
      <button className={button} onClick={() => act(reload)} disabled={busy}>{t("recipes.refresh")}</button></div>}
    <div className="flex flex-wrap gap-2 items-center">
      <select className={control} aria-label={t("recipes.saved")} value={selected ?? ""}
        onChange={e => { const found = versions.find(v => v.id === Number(e.target.value)); if (found) choose(found); }}>
        <option value="">{t("recipes.saved")}</option>
        {versions.map(v => <option key={v.id} value={v.id}>{v.name} · v{v.version}</option>)}
      </select>
      <button className={button} onClick={() => { setSelected(null); setKey(""); setDraft({ name: "", max_parallel: 2, steps: [] }); }}>{t("recipes.new")}</button>
    </div>
    <div className="flex flex-wrap gap-3 items-end">
      <label className="flex flex-col gap-1 text-sm flex-1">{t("recipes.name")}
        <input className={control} maxLength={100} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
      <label className="flex flex-col gap-1 text-sm">{t("recipes.parallel")}
        <select className={control} value={draft.max_parallel} onChange={e => setDraft({ ...draft, max_parallel: Number(e.target.value) })}>
          {[1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></label>
    </div>
    {draft.steps.length === 0 && <p className="text-sm text-muted-foreground">{t("recipes.empty")}</p>}
    <ol className="space-y-3">{draft.steps.map((step, index) => <li key={step.key} className="border border-border rounded-xl p-4 space-y-3">
      <div className="flex flex-wrap gap-2 items-center"><span className="text-primary font-mono">{index + 1}</span>
        <input className={control + " flex-1"} aria-label={t("recipes.step_label", { n: index + 1 })} value={step.name} maxLength={100}
          onChange={e => editStep(index, { name: e.target.value })} />
        <select className={control} aria-label={t("recipes.assignee")} value={step.spawn_id} onChange={e => editStep(index, { spawn_id: Number(e.target.value) })}>
          <option value={0}>{t("recipes.assignee")}</option>{spawns.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <button className={button} onClick={() => setDraft(d => ({ ...d, steps: d.steps.filter(s => s.key !== step.key)
          .map(s => ({ ...s, depends_on: s.depends_on.filter(k => k !== step.key) })) }))}>{t("recipes.remove")}</button></div>
      <textarea className={control + " w-full min-h-20"} aria-label={t("recipes.task", { n: index + 1 })} value={step.task} maxLength={4000}
        onChange={e => editStep(index, { task: e.target.value })} placeholder={t("recipes.task_hint")} />
      {index > 0 && <fieldset className="flex flex-wrap items-center gap-3 text-sm"><legend className="text-muted-foreground mb-1">{t("recipes.depends")}</legend>
        {draft.steps.slice(0, index).map(prior => <label key={prior.key} className="flex gap-2 items-center"><input type="checkbox"
          checked={step.depends_on.includes(prior.key)} onChange={e => editStep(index, { depends_on: e.target.checked
            ? [...step.depends_on, prior.key] : step.depends_on.filter(k => k !== prior.key) })} />{prior.name}</label>)}</fieldset>}
      <label className="flex gap-2 items-center text-sm"><input type="checkbox" checked={step.requires_approval}
        onChange={e => editStep(index, { requires_approval: e.target.checked })} />{t("recipes.approval_gate")}</label>
    </li>)}</ol>
    <div className="flex gap-2 flex-wrap">
      <button className={button} disabled={draft.steps.length >= 16 || spawns.length === 0} onClick={addStep}>{t("recipes.add_step")}</button>
      <button className={button} disabled={!valid || busy} onClick={() => act(async () => {
        const saved = await recipeApi.save(key || `recipe-${crypto.randomUUID().slice(0, 12)}`, draft); choose(saved);
      })}>{t("recipes.save_version")}</button>
    </div>
    {selected && <div className="border-t border-border pt-4 space-y-2">
      <label className="block text-sm">{t("recipes.input")}<textarea className={control + " block w-full mt-1"} value={input} maxLength={8000} onChange={e => setInput(e.target.value)} /></label>
      <p className="text-xs text-muted-foreground">{t("recipes.run_notice")}</p>
      <button className={button + " bg-primary/10"} disabled={busy || !input.trim()} onClick={() => act(() =>
        (async () => {
          const signature = JSON.stringify([selected, input]);
          if (pendingStart.current?.signature !== signature) pendingStart.current = { signature, key: crypto.randomUUID() };
          await recipeApi.start(selected, input, pendingStart.current.key);
          pendingStart.current = null;
        })())}>{t("recipes.run_saved")}</button>
    </div>}
    <div className="border-t border-border pt-4 space-y-3"><h3 className="font-semibold">{t("recipes.history")}</h3>
      {!loading && executions.length === 0 && <p className="text-sm text-muted-foreground">{t("recipes.no_runs")}</p>}
      {executions.map(execution => <article key={execution.id} className="border border-border rounded-xl p-4 space-y-3">
        <div className="flex justify-between gap-3"><span>#{execution.id} · {versions.find(v => v.id === execution.recipe_id)?.name}</span>
          <span role="status" className="text-primary text-sm">{t(`recipes.status_${execution.status}`)}</span></div>
        <p className="text-sm text-muted-foreground line-clamp-2">{execution.input}</p>
        {Object.entries(execution.checkpoint.steps || {}).map(([nodeKey, node]) => <div key={nodeKey} className="rounded-lg bg-background p-3 space-y-1">
          <div className="flex justify-between gap-2 text-sm"><span>{versions.find(v => v.id === execution.recipe_id)?.spec.steps.find(s => s.key === nodeKey)?.name || nodeKey}</span>
            <span>{t(`recipes.status_${node.status}`)}</span></div>
          {node.output && <details><summary className="text-sm cursor-pointer text-muted-foreground">{t("recipes.output")}</summary>
            <pre className="whitespace-pre-wrap text-xs max-h-64 overflow-auto mt-2">{node.output}</pre></details>}
          {node.error && <p className="text-xs text-danger">{node.error}</p>}
          {node.run_id && <button className="text-xs text-primary underline" onClick={() => setRunId(node.run_id!)}>{t("recipes.trace")}</button>}
          {node.status === "waiting_approval" && <button className={button} disabled={busy} onClick={() => act(() => recipeApi.resume(execution.id, [nodeKey], false))}>{t("recipes.approve")}</button>}
        </div>)}
        <div className="flex gap-2 flex-wrap">
          {["running", "queued"].includes(execution.status) && <button className={button} disabled={busy} onClick={() => act(() => recipeApi.cancel(execution.id))}>{t("recipes.stop")}</button>}
          {["failed", "interrupted"].includes(execution.status) && <button className={button} disabled={busy} onClick={() => setRetry(execution)}>{t("recipes.review_resume")}</button>}
          {execution.run_id && <button className={button} onClick={() => setRunId(execution.run_id!)}>{t("recipes.trace")}</button>}
        </div>
      </article>)}
    </div>
    {retry && <div role="dialog" aria-modal="true" aria-label={t("recipes.review_resume")} className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6">
      <div className="bg-surface border border-border rounded-xl p-6 max-w-lg space-y-4"><h3 className="font-semibold">{t("recipes.review_resume")}</h3>
        <p className="text-sm">{t("recipes.retry_warning")}</p><div className="flex gap-3">
          <button className={button} onClick={() => setRetry(null)}>{t("recipes.cancel")}</button>
          <button className={button} disabled={busy} onClick={() => { const id = retry.id; setRetry(null); act(() => recipeApi.resume(id, [], true)); }}>{t("recipes.confirm_retry")}</button>
        </div></div></div>}
    {runId && <div role="dialog" aria-modal="true" aria-label={t("recipes.trace")} className="fixed inset-4 z-50 overflow-auto bg-background border border-border rounded-xl shadow-2xl">
      <RunReplay runId={runId} onClose={() => setRunId(null)} /></div>}
  </section>;
}
