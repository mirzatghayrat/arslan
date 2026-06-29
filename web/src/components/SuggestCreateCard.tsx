import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { SuggestDraft, OverlapInfo } from "../api/client.types";
import RegistryPicker, { type PickKind } from "./RegistryPicker";

/** Equipment shape the backend (B1) consumes; MCPs fold into toolsets. */
export interface EditedDraft extends SuggestDraft {
  capabilities: string[];
  /** The edited task brief (may differ from the original suggestionTaskBrief). */
  brief: string;
  equipment: { toolsets: string[]; skills: string[] };
}

export type GapKind = "discover_mcp" | "distill_skill" | "request_grant";

interface Props {
  draft: SuggestDraft;
  taskBrief: string | null;
  overlaps: OverlapInfo | null;
  /** Receives the fully edited draft incl. final equipment. */
  onCreate: (draft: EditedDraft) => void;
  onDismiss: () => void;
  /** Keep chatting to refine (optional; wired later). */
  onRefine?: () => void;
  /**
   * Gap action handler. Drives an EXISTING gated, human-confirmed acquisition
   * flow (discover→add MCP, or distill→create skill) and resolves with the
   * acquired capability key so the card can fold it into its equipment and drop
   * the gap. Resolves `null` when nothing was acquired (cancelled, or
   * request_grant — which defers to run time). Never auto-acquires.
   */
  onFillGap?: (
    kind: GapKind,
    gap: string,
  ) => Promise<{ row: "tools" | "skills" | "mcps"; key: string } | null>;
}

export default function SuggestCreateCard({
  draft,
  taskBrief,
  overlaps,
  onCreate,
  onDismiss,
  onRefine,
  onFillGap,
}: Props) {
  const { t } = useTranslation();

  // Local editable state seeded from the draft.
  const [name, setName] = useState(draft.name);
  const [domain, setDomain] = useState(draft.domain);
  const [role, setRole] = useState(draft.persona_role ?? "");
  const [tone, setTone] = useState(draft.persona_tone ?? "");
  const [brief, setBrief] = useState(taskBrief ?? "");

  const [tools, setTools] = useState<string[]>(draft.tools ?? []);
  const [skills, setSkills] = useState<string[]>(draft.skills ?? []);
  const [mcps, setMcps] = useState<string[]>(draft.mcps ?? []);

  // Which row's picker is open ("tool" | "mcp" | "skill" | null).
  const [picker, setPicker] = useState<PickKind | null>(null);

  // Gaps the user has filled (removed) locally + which gap is mid-acquisition.
  const [filledGaps, setFilledGaps] = useState<string[]>([]);
  const [busyGap, setBusyGap] = useState<string | null>(null);
  const gaps = (draft.gaps ?? []).filter((g) => !filledGaps.includes(g));
  const seedRefs = draft.seed_refs ?? [];

  async function handleFillGap(kind: GapKind, gap: string) {
    if (busyGap) return;
    setBusyGap(gap);
    try {
      const result = await onFillGap?.(kind, gap);
      if (!result) return; // cancelled / request_grant → leave gap in place
      const { row, key } = result;
      if (row === "tools") setTools((xs) => (xs.includes(key) ? xs : [...xs, key]));
      else if (row === "mcps") setMcps((xs) => (xs.includes(key) ? xs : [...xs, key]));
      else setSkills((xs) => (xs.includes(key) ? xs : [...xs, key]));
      setFilledGaps((xs) => (xs.includes(gap) ? xs : [...xs, gap]));
    } finally {
      setBusyGap(null);
    }
  }

  function handlePick(kind: PickKind, key: string) {
    if (kind === "tool") setTools((xs) => (xs.includes(key) ? xs : [...xs, key]));
    else if (kind === "mcp") setMcps((xs) => (xs.includes(key) ? xs : [...xs, key]));
    else setSkills((xs) => (xs.includes(key) ? xs : [...xs, key]));
    setPicker(null);
  }

  function handleCreate() {
    const edited: EditedDraft = {
      ...draft,
      name,
      domain,
      persona_role: role || null,
      persona_tone: tone || null,
      capabilities: draft.capabilities,
      brief,
      tools,
      skills,
      mcps,
      // MCPs are `mcp_`-prefixed toolset keys → fold into toolsets. Explicit wins.
      equipment: { toolsets: [...tools, ...mcps], skills },
    };
    onCreate(edited);
  }

  return (
    <div className="suggest-create-card" data-testid="suggest-create-card">
      <header className="suggest-create-card__head">
        <span className="suggest-create-card__icon" aria-hidden>✦</span>
        <span className="suggest-create-card__title">{t("create_card.title")}</span>
      </header>

      {/* Editable header fields */}
      <div className="suggest-create-card__fields">
        <Field label={t("create_card.name")}>
          <input
            className="suggest-create-card__input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="edit-name"
            aria-label={t("create_card.name")}
          />
        </Field>
        <Field label={t("create_card.domain")}>
          <input
            className="suggest-create-card__input"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            data-testid="edit-domain"
            aria-label={t("create_card.domain")}
          />
        </Field>
        <Field label={t("create_card.role")}>
          <input
            className="suggest-create-card__input"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            data-testid="edit-role"
            aria-label={t("create_card.role")}
          />
        </Field>
        <Field label={t("create_card.tone")}>
          <input
            className="suggest-create-card__input"
            value={tone}
            onChange={(e) => setTone(e.target.value)}
            data-testid="edit-tone"
            aria-label={t("create_card.tone")}
          />
        </Field>
        <Field label={t("create_card.brief")}>
          <textarea
            className="suggest-create-card__input suggest-create-card__textarea"
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            data-testid="edit-brief"
            aria-label={t("create_card.brief")}
            rows={2}
          />
        </Field>
      </div>

      {/* Equipment: three chip rows */}
      <ChipRow
        kind="tool"
        label={t("create_card.tools")}
        items={tools}
        onRemove={(k) => setTools((xs) => xs.filter((x) => x !== k))}
        onAdd={() => setPicker(picker === "tool" ? null : "tool")}
        addLabel={t("create_card.add")}
      />
      <ChipRow
        kind="skill"
        label={t("create_card.skills")}
        items={skills}
        onRemove={(k) => setSkills((xs) => xs.filter((x) => x !== k))}
        onAdd={() => setPicker(picker === "skill" ? null : "skill")}
        addLabel={t("create_card.add")}
      />
      <ChipRow
        kind="mcp"
        label={t("create_card.mcps")}
        items={mcps}
        onRemove={(k) => setMcps((xs) => xs.filter((x) => x !== k))}
        onAdd={() => setPicker(picker === "mcp" ? null : "mcp")}
        addLabel={t("create_card.add")}
      />

      {picker && (
        <RegistryPicker
          kind={picker}
          selected={picker === "tool" ? tools : picker === "mcp" ? mcps : skills}
          onPick={handlePick}
          onClose={() => setPicker(null)}
        />
      )}

      {/* Capability gaps */}
      {gaps.length > 0 && (
        <div className="suggest-create-card__gaps" data-testid="gaps">
          <div className="suggest-create-card__gaps-title">{t("create_card.gaps")}</div>
          {gaps.map((gap, i) => (
            <div className="suggest-create-card__gap" key={`${gap}-${i}`} data-testid={`gap-${i}`}>
              <span className="suggest-create-card__gap-text">{gap}</span>
              <div className="suggest-create-card__gap-actions">
                <button
                  type="button"
                  className="suggest-create-card__gap-btn"
                  onClick={() => handleFillGap("discover_mcp", gap)}
                  disabled={busyGap !== null}
                  data-testid={`gap-discover-mcp-${i}`}
                >
                  {busyGap === gap ? t("create_card.gap_working") : t("create_card.gap_discover_mcp")}
                </button>
                <button
                  type="button"
                  className="suggest-create-card__gap-btn"
                  onClick={() => handleFillGap("distill_skill", gap)}
                  disabled={busyGap !== null}
                  data-testid={`gap-distill-skill-${i}`}
                >
                  {t("create_card.gap_distill_skill")}
                </button>
                <button
                  type="button"
                  className="suggest-create-card__gap-btn"
                  onClick={() => handleFillGap("request_grant", gap)}
                  disabled={busyGap !== null}
                  title={t("create_card.gap_request_grant_note")}
                  data-testid={`gap-request-grant-${i}`}
                >
                  {t("create_card.gap_request_grant")}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Seed provenance */}
      {seedRefs.length > 0 && (
        <div className="suggest-create-card__provenance" data-testid="seed-provenance">
          {t("create_card.seed_provenance")} {seedRefs.join("、")}
        </div>
      )}

      {overlaps && (
        <div className="suggest-create-card__overlap" role="alert" data-testid="overlap-warning">
          <span className="suggest-create-card__overlap-icon" aria-hidden>⚠</span>
          <span>
            {t("create_card.overlap_warning", { name: overlaps.name })}
            {overlaps.axes.length > 0 && (
              <span className="suggest-create-card__overlap-axes">（{overlaps.axes.join("、")}）</span>
            )}
          </span>
        </div>
      )}

      <div className="suggest-create-card__actions">
        <button
          className="suggest-create-card__btn suggest-create-card__btn--primary"
          onClick={handleCreate}
          data-testid="btn-create"
        >
          {t("create_card.create")}
        </button>
        {onRefine && (
          <button
            className="suggest-create-card__btn suggest-create-card__btn--ghost"
            onClick={onRefine}
            data-testid="btn-refine"
          >
            {t("create_card.refine")}
          </button>
        )}
        <button
          className="suggest-create-card__btn suggest-create-card__btn--ghost"
          onClick={onDismiss}
          data-testid="btn-dismiss"
        >
          {t("create_card.dismiss")}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="suggest-create-card__field">
      <span className="suggest-create-card__field-label">{label}</span>
      {children}
    </label>
  );
}

function ChipRow({
  kind,
  label,
  items,
  onRemove,
  onAdd,
  addLabel,
}: {
  kind: PickKind;
  label: string;
  items: string[];
  onRemove: (key: string) => void;
  onAdd: () => void;
  addLabel: string;
}) {
  return (
    <div className="suggest-create-card__chiprow" data-testid={`chiprow-${kind}`}>
      <span className="suggest-create-card__chiprow-label">{label}</span>
      <div className="suggest-create-card__chips">
        {items.map((key) => (
          <span className="suggest-create-card__chip" key={key} data-testid={`chip-${kind}-${key}`}>
            <span className="suggest-create-card__chip-text">{key}</span>
            <button
              type="button"
              className="suggest-create-card__chip-x"
              onClick={() => onRemove(key)}
              data-testid={`remove-${kind}-${key}`}
              aria-label={`remove ${key}`}
            >
              ✕
            </button>
          </span>
        ))}
        <button
          type="button"
          className="suggest-create-card__chip-add"
          onClick={onAdd}
          data-testid={`add-${kind}`}
        >
          ＋ {addLabel}
        </button>
      </div>
    </div>
  );
}
