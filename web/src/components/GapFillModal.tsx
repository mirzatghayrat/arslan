import { useState } from "react";
import { useTranslation } from "react-i18next";
import { evaluateRepo, generateSkill, createSkill, type EvalResult, type SkillDraft } from "../api/discovery";
import { addMcpServer, connectMcpServer, exposeMcpServer } from "../api/mcp";
import { useDismissable } from "../hooks/useDismissable";
import DiscardChangesBar from "./DiscardChangesBar";
import { gapFillDirty } from "../lib/dirty";

export type GapFillKind = "discover_mcp" | "distill_skill";
export type GapFillResult = { row: "tools" | "skills" | "mcps"; key: string };

interface Props {
  kind: GapFillKind;
  /** The capability gap being filled — shown for context. */
  gap: string;
  /** Resolve with the acquired key, or null when cancelled. */
  onDone: (result: GapFillResult | null) => void;
}

/**
 * Focused, human-confirmed gap-fill flow that REUSES the existing gated
 * acquisition clients (no new acquisition logic, never auto-acquires):
 *   discover_mcp  →  evaluateRepo → addMcpServer → connect → expose → key `mcp_<id>`
 *   distill_skill →  generateSkill → (edit) → createSkill → key from CreatedSkill
 * Each step requires an explicit click. On success the acquired capability key
 * is handed back to the card via onDone.
 */
export default function GapFillModal({ kind, gap, onDone }: Props) {
  const { t } = useTranslation();
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // discover_mcp draft (review/edit before add — the consent step).
  const [evalRes, setEvalRes] = useState<EvalResult | null>(null);
  const [mcpDraft, setMcpDraft] = useState({ transport: "stdio", command: "", args: "", url: "" });

  // distill_skill draft (review/edit before create — the consent step).
  const [skillDraft, setSkillDraft] = useState<({ full_name: string } & SkillDraft) | null>(null);

  // ── Editor rules (①A). Dirty = anything typed OR a draft awaiting consent.
  // The drafts count because they are the review step: losing one means the
  // evaluate call has to be paid for again. `busy` counts too — closing during
  // an in-flight step would orphan it.
  const [confirmingClose, setConfirmingClose] = useState(false);
  const dirty = gapFillDirty({
    ref, busy, hasEvalResult: Boolean(evalRes), hasSkillDraft: Boolean(skillDraft), mcpDraft,
  });
  useDismissable<HTMLDivElement, HTMLDivElement>(
    true,
    () => (dirty ? setConfirmingClose(true) : onDone(null)),
    { outsideClick: false },   // holds form input
  );

  async function handleEvaluate() {
    const trimmed = ref.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const res = await evaluateRepo(trimmed);
      setEvalRes(res);
      const s = res.suggestion;
      setMcpDraft({
        transport: s.transport ?? "stdio",
        command: s.command ?? "",
        args: (s.args || []).join(" "),
        url: s.url ?? "",
      });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function handleAddMcp() {
    if (!evalRes) return;
    setBusy(true);
    setError(null);
    try {
      const server = await addMcpServer({
        label: evalRes.repo.full_name.split("/").pop()!,
        transport: mcpDraft.transport,
        command: mcpDraft.command,
        // Naive whitespace split — does NOT handle quoted args. Acceptable here:
        // the user reviews/edits the launch command before clicking Add.
        args: mcpDraft.args.split(/\s+/).filter(Boolean),
        url: mcpDraft.url || undefined,
        env: {},
      });
      // Connect + expose so the toolset is assignable; best-effort.
      try {
        await connectMcpServer(server.id);
        await exposeMcpServer(server.id, true);
      } catch {
        /* server is added; connect/expose can be retried in Settings → MCP */
      }
      onDone({ row: "mcps", key: `mcp_${server.id}` });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  }

  async function handleGenerateSkill() {
    const trimmed = ref.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const res = await generateSkill(trimmed);
      if (!res.skill) {
        setError(t("gap_fill.no_skill", { repo: res.repo.full_name }));
        return;
      }
      setSkillDraft({ full_name: res.repo.full_name, ...res.skill });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateSkill() {
    if (!skillDraft) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createSkill({
        full_name: skillDraft.full_name,
        name: skillDraft.name,
        category: skillDraft.category,
        description: skillDraft.description,
        body: skillDraft.body,
      });
      onDone({ row: "skills", key: created.key });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setBusy(false);
    }
  }

  const isMcp = kind === "discover_mcp";

  return (
    <div className="gap-fill-overlay" data-testid="gap-fill-modal" role="dialog" aria-modal="true">
      <div className="gap-fill-modal">
        <header className="gap-fill-modal__head">
          <span className="gap-fill-modal__title">
            {isMcp ? t("gap_fill.discover_title") : t("gap_fill.distill_title")}
          </span>
          <button
            type="button"
            className="gap-fill-modal__close"
            onClick={() => onDone(null)}
            data-testid="gap-fill-cancel"
            aria-label={t("gap_fill.cancel")}
          >
            ✕
          </button>
        </header>

        <p className="gap-fill-modal__gap">{t("gap_fill.for_gap", { gap })}</p>

        {/* Step 1: repo ref input + evaluate/generate (read-only) */}
        <div className="gap-fill-modal__row">
          <input
            className="gap-fill-modal__input"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            placeholder={t("gap_fill.ref_placeholder")}
            data-testid="gap-fill-ref"
            aria-label={t("gap_fill.ref_placeholder")}
          />
          <button
            type="button"
            className="gap-fill-modal__btn gap-fill-modal__btn--primary"
            onClick={isMcp ? handleEvaluate : handleGenerateSkill}
            disabled={busy || !ref.trim()}
            data-testid="gap-fill-evaluate"
          >
            {busy ? t("gap_fill.working") : isMcp ? t("gap_fill.evaluate") : t("gap_fill.generate")}
          </button>
        </div>

        {error && (
          <div className="gap-fill-modal__error" role="alert" data-testid="gap-fill-error">
            {error}
          </div>
        )}

        {/* Step 2 (MCP): review suggested command + Add (the gated, confirmed step) */}
        {isMcp && evalRes && (
          <div className="gap-fill-modal__draft" data-testid="gap-fill-mcp-draft">
            <div className="gap-fill-modal__classify">
              {evalRes.suggestion.is_mcp ? t("gap_fill.is_mcp") : t("gap_fill.not_mcp")}
              {evalRes.suggestion.reason ? ` — ${evalRes.suggestion.reason}` : ""}
            </div>
            <select
              className="gap-fill-modal__input"
              value={mcpDraft.transport}
              onChange={(e) => setMcpDraft((p) => ({ ...p, transport: e.target.value }))}
              aria-label="transport"
            >
              <option value="stdio">stdio</option>
              <option value="http">http</option>
            </select>
            {mcpDraft.transport === "http" ? (
              <input
                className="gap-fill-modal__input"
                value={mcpDraft.url}
                onChange={(e) => setMcpDraft((p) => ({ ...p, url: e.target.value }))}
                placeholder="https://…/mcp"
                aria-label="url"
              />
            ) : (
              <>
                <input
                  className="gap-fill-modal__input"
                  value={mcpDraft.command}
                  onChange={(e) => setMcpDraft((p) => ({ ...p, command: e.target.value }))}
                  placeholder="npx"
                  aria-label="command"
                />
                <input
                  className="gap-fill-modal__input"
                  value={mcpDraft.args}
                  onChange={(e) => setMcpDraft((p) => ({ ...p, args: e.target.value }))}
                  placeholder="-y @scope/server"
                  aria-label="args"
                />
              </>
            )}
            <button
              type="button"
              className="gap-fill-modal__btn gap-fill-modal__btn--primary"
              onClick={handleAddMcp}
              disabled={
                busy ||
                !evalRes.suggestion.is_mcp ||
                (mcpDraft.transport === "http" ? !mcpDraft.url.trim() : !mcpDraft.command.trim())
              }
              data-testid="gap-fill-add-mcp"
            >
              {busy ? t("gap_fill.working") : t("gap_fill.add_mcp")}
            </button>
          </div>
        )}

        {/* Step 2 (Skill): review/edit distilled body + Create (the gated, confirmed step) */}
        {!isMcp && skillDraft && (
          <div className="gap-fill-modal__draft" data-testid="gap-fill-skill-draft">
            <input
              className="gap-fill-modal__input"
              value={skillDraft.name}
              onChange={(e) => setSkillDraft((p) => p && { ...p, name: e.target.value })}
              placeholder={t("gap_fill.skill_name")}
              aria-label={t("gap_fill.skill_name")}
            />
            <input
              className="gap-fill-modal__input"
              value={skillDraft.description}
              onChange={(e) => setSkillDraft((p) => p && { ...p, description: e.target.value })}
              placeholder={t("gap_fill.skill_desc")}
              aria-label={t("gap_fill.skill_desc")}
            />
            {/* 🔒 body shown ONLY as plain text in a textarea, never rendered as HTML */}
            <textarea
              className="gap-fill-modal__input gap-fill-modal__textarea"
              value={skillDraft.body}
              onChange={(e) => setSkillDraft((p) => p && { ...p, body: e.target.value })}
              rows={8}
              spellCheck={false}
              aria-label={t("gap_fill.skill_body")}
            />
            <button
              type="button"
              className="gap-fill-modal__btn gap-fill-modal__btn--primary"
              onClick={handleCreateSkill}
              disabled={busy || !skillDraft.name.trim() || !skillDraft.body.trim()}
              data-testid="gap-fill-create-skill"
            >
              {busy ? t("gap_fill.working") : t("gap_fill.create_skill")}
            </button>
          </div>
        )}
      {confirmingClose && (
          <DiscardChangesBar
            onDiscard={() => onDone(null)}
            onCancel={() => setConfirmingClose(false)}
          />
        )}
      </div>
    </div>
  );
}
