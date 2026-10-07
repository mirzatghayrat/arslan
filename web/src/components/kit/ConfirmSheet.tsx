import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { create } from "zustand";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

export interface ConfirmOptions {
  title: string;
  /** What is lost, in one or two sentences. */
  body?: ReactNode;
  action: string;
  /** Red by default: a confirm sheet is for actions that cannot be undone. */
  destructive?: boolean;
  cancel?: string;
}

/**
 * ConfirmSheet (0.1.55): the sentence, what is lost, Cancel + the red action.
 * Esc cancels, ⌘⏎ confirms. Replaces six delete confirms and both window.confirm
 * calls, and is added to the seven destructive actions that confirmed nothing.
 */
export function ConfirmSheet({ open, options, onAnswer }: {
  open: boolean; options: ConfirmOptions | null; onAnswer: (ok: boolean) => void;
}) {
  const { t } = useTranslation();
  if (!options) return null;
  return (
    <Dialog open={open} onClose={() => onAnswer(false)} onSubmit={() => onAnswer(true)} bare width={420}
      testId="confirm-sheet" title={options.title}>
      <div className="flex flex-col gap-3.5 px-5 pb-4 pt-[18px]">
        <p aria-hidden="true" className="text-[19px] font-bold leading-[1.35]">{options.title}</p>
        {options.body ? <div className="text-[14px] leading-normal text-muted-foreground">{options.body}</div> : null}
        <div className="flex gap-2.5">
          <Button tone="secondary" grow={1} kbd="esc" onClick={() => onAnswer(false)} data-testid="confirm-cancel">
            {options.cancel ?? t("kit.cancel")}
          </Button>
          <Button tone={options.destructive === false ? "primary" : "destructive"} grow={1.4} kbd="⌘⏎"
            onClick={() => onAnswer(true)} data-testid="confirm-action">
            {options.action}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type Pending = { options: ConfirmOptions; resolve: (ok: boolean) => void };
const useConfirmStore = create<{ pending: Pending | null }>(() => ({ pending: null }));

/** `if (await confirmSheet({...})) delete()` — the promise form, for one-line call sites. */
export function confirmSheet(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    useConfirmStore.getState().pending?.resolve(false);
    useConfirmStore.setState({ pending: { options, resolve } });
  });
}

/** Mounted once (App). */
export function ConfirmHost() {
  const pending = useConfirmStore((s) => s.pending);
  const [closing, setClosing] = useState(false);
  const answer = (ok: boolean) => {
    if (closing) return;
    setClosing(true);
    pending?.resolve(ok);
    useConfirmStore.setState({ pending: null });
    setClosing(false);
  };
  return <ConfirmSheet open={!!pending} options={pending?.options ?? null} onAnswer={answer} />;
}
