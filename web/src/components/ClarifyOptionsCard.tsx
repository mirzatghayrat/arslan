import { useTranslation } from "react-i18next";
import { Check } from "lucide-react";
import { AskMark } from "./kit";

interface Props {
  /** The clarifying question Arslan needs answered before it can proceed. */
  question: string;
  /** 2-4 options, validated/clamped server-side. Label is the text sent on pick. */
  options: { label: string; hint?: string }[];
  /** True once the user picked — buttons disable (one-shot; a re-click never re-sends). */
  answered?: boolean;
  /** Called with the picked option's LABEL — sent as a normal user_message. */
  onPick: (label: string) => void;
}

/**
 * PA-3 structured clarification for a backend `clarify_options` frame — 0.1.55 the kit's
 * ChoiceCard: the same surface as an asking card without the asking header. The question,
 * then 2–4 one-click options (label, muted hint). Picking sends the label over the SAME
 * WS send path the composer uses, so one click advances the conversation.
 */
export default function ClarifyOptionsCard({ question, options, answered, onPick }: Props) {
  const { t } = useTranslation();
  return (
    <div data-testid="clarify-options-card" data-answered={answered ? "true" : "false"}
      className={`flex max-w-[460px] flex-col gap-3 rounded-2xl border border-border bg-surface px-4 py-3.5 text-foreground ${answered ? "opacity-70" : ""}`}>
      <div className="flex items-start gap-2.5">
        <AskMark size={26} mouth="idle" />
        <span className="pt-0.5 text-[14px] font-semibold leading-snug">{question}</span>
      </div>
      <div className="flex flex-col gap-1.5">
        {options.map((o) => (
          <button key={o.label} type="button" data-testid="clarify-option" disabled={!!answered} onClick={() => onPick(o.label)}
            className="flex flex-col items-start gap-0.5 rounded-[10px] bg-fill px-3 py-2 text-left hover:bg-fill-strong disabled:cursor-default disabled:hover:bg-fill">
            <span className="text-[13px] font-semibold">{o.label}</span>
            {o.hint && <span className="text-[12px] text-muted-foreground">{o.hint}</span>}
          </button>
        ))}
      </div>
      {answered && (
        <span className="inline-flex items-center gap-1 text-[12px] text-muted-foreground" data-testid="clarify-answered">
          <Check className="h-3.5 w-3.5" aria-hidden /> {t("clarify_card.answered")}
        </span>
      )}
    </div>
  );
}
