import type { SuggestDraft, OverlapInfo } from "../api/client.types";

interface Props {
  draft: SuggestDraft;
  taskBrief: string | null;
  overlaps: OverlapInfo | null;
  onCreate: () => void;
  onDismiss: () => void;
}

export default function SuggestCreateCard({ draft, taskBrief, overlaps, onCreate, onDismiss }: Props) {
  return (
    <div className="suggest-create-card" data-testid="suggest-create-card">
      <header className="suggest-create-card__head">
        <span className="suggest-create-card__icon" aria-hidden>✦</span>
        <span className="suggest-create-card__title">建议新建分身</span>
        <span className="suggest-create-card__name">{draft.name}</span>
      </header>

      {taskBrief && (
        <p className="suggest-create-card__brief">{taskBrief}</p>
      )}

      <dl className="suggest-create-card__meta">
        <div className="suggest-create-card__meta-row">
          <dt>领域</dt>
          <dd>{draft.domain}</dd>
        </div>
        {draft.capabilities.length > 0 && (
          <div className="suggest-create-card__meta-row">
            <dt>能力</dt>
            <dd>{draft.capabilities.join("、")}</dd>
          </div>
        )}
        {draft.persona_role && (
          <div className="suggest-create-card__meta-row">
            <dt>角色</dt>
            <dd>{draft.persona_role}</dd>
          </div>
        )}
        {draft.persona_tone && (
          <div className="suggest-create-card__meta-row">
            <dt>风格</dt>
            <dd>{draft.persona_tone}</dd>
          </div>
        )}
        {draft.reason && (
          <div className="suggest-create-card__meta-row">
            <dt>原因</dt>
            <dd>{draft.reason}</dd>
          </div>
        )}
      </dl>

      {overlaps && (
        <div className="suggest-create-card__overlap" role="alert" data-testid="overlap-warning">
          <span className="suggest-create-card__overlap-icon" aria-hidden>⚠</span>
          <span>
            与已有分身「{overlaps.name}」可能重叠
            {overlaps.axes.length > 0 && (
              <span className="suggest-create-card__overlap-axes">（{overlaps.axes.join("、")}）</span>
            )}
          </span>
        </div>
      )}

      <div className="suggest-create-card__actions">
        <button
          className="suggest-create-card__btn suggest-create-card__btn--primary"
          onClick={onCreate}
          data-testid="btn-create"
        >
          创建
        </button>
        <button
          className="suggest-create-card__btn suggest-create-card__btn--ghost"
          onClick={onDismiss}
          data-testid="btn-dismiss"
        >
          忽略
        </button>
      </div>
    </div>
  );
}
