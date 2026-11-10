// ConversationHeader — the conversation's line in the top bar: the green status dot and its title first,
// then the chips (project, task status, run state) that ConversationControls and TaskPanel render as children.
//
// The title never wraps (one line, ellipsis, at least ~4em) and no chip wraps. What gives way is
// decided by the HEADER's own width, a container query, not the window's: opening the right panel
// narrows the header without the window changing size, which is when the chips used to wrap.
//   ≤ 560px  chips show only their icon; the text stays as a tooltip and in the accessible name
//   ≤ 400px  the secondary chips (project, task status) move into the ⋯ menu; the run state stays an icon
//   ≤ 300px  only ⋯ remains
// The chips mark themselves with data-hdr-chip ("secondary" or "run") and these classes.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { MoreHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useDismissable } from "../../hooks/useDismissable";
import { useMenuKeyboard } from "../../hooks/useMenuKeyboard";
import RenameInput from "../RenameInput";

/** One header chip: never wraps. */
export const HDR_CHIP = "inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-border px-2 text-[12px] @max-[560px]/hdr:px-1.5";
/** A chip's text: hidden at ≤ 560px, the icon stays. */
export const HDR_LABEL = "@max-[560px]/hdr:hidden";
/** Project and task status: into ⋯ at ≤ 400px. */
export const HDR_SECONDARY = "@max-[400px]/hdr:hidden";
/** The run state: into ⋯ at ≤ 300px. */
export const HDR_RUN = "@max-[300px]/hdr:hidden";

interface HiddenChip { kind: string; label: string; el: HTMLElement }

function readChips(root: HTMLElement | null): HiddenChip[] {
  const chips = Array.from(root?.querySelectorAll<HTMLElement>("[data-hdr-chip]") ?? []);
  return chips.map((el) => ({ kind: el.dataset.hdrChip ?? "secondary", label: el.getAttribute("title") ?? el.textContent ?? "", el }));
}

export default function ConversationHeader({ title, onRename, children }: {
  title: string;
  /** Absent for a conversation that cannot be renamed (a temporary one). */
  onRename?: (title: string) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [menu, setMenu] = useState<HiddenChip[] | null>(null);
  const chipsRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLButtonElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const open = menu !== null;
  const { anchorRef, floatingRef } = useDismissable<HTMLDivElement, HTMLDivElement>(open, () => setMenu(null));
  const onMenuKeyDown = useMenuKeyboard(open, moreRef, floatingRef);
  // The chips belong to their own components (they own the dialogs they open), so ⋯ reads them from the
  // header and an item is a click on the chip it stands for. CSS decides which items show.
  function openMenu() { setMenu(readChips(chipsRef.current)); }
  // While it is open the list follows the chips: a chip re-renders inside its own component (the run state
  // changes, a task finishes) without re-rendering this header, so watch the chips' DOM and read them again.
  useEffect(() => {
    const root = chipsRef.current;
    if (!open || !root) return;
    const observer = new MutationObserver(() => setMenu((current) => (current ? readChips(root) : current)));
    observer.observe(root, { subtree: true, childList: true, attributes: true, characterData: true });
    return () => observer.disconnect();
  }, [open]);
  const more = t("sidebar.headerMore");
  return <div data-testid="conversation-header" className="@container/hdr min-w-0 flex-1">
    <div className="flex h-9 min-w-0 items-center gap-1.5">
      {/* The dot IS the "active session workspace" label — it was
          three words of chrome saying what a green dot already says. */}
      <span data-testid="conversation-status-dot" className="w-2 h-2 rounded-full bg-success shrink-0"></span>
      {editing && onRename
        ? <RenameInput value={title} testId="header-rename-input" onRename={onRename}
            className="max-w-[420px] text-[13px] font-semibold"
            onClose={(byKey) => { setEditing(false); if (byKey) setTimeout(() => titleRef.current?.focus()); }} />
        : onRename
          ? <button ref={titleRef} type="button" data-testid="header-title" title={t("sidebar.renameHint", { title })}
              onClick={() => setEditing(true)}
              className="min-w-[4em] shrink truncate rounded-md px-1.5 py-0.5 text-left text-[13px] font-semibold text-foreground hover:bg-foreground/5">
              {title}</button>
          : <span data-testid="header-title" title={title} className="min-w-[4em] shrink truncate px-1.5 text-[13px] font-semibold text-foreground">{title}</span>}
      <div ref={chipsRef} data-testid="conversation-context-bar" className="ml-auto flex shrink-0 items-center gap-1">{children}</div>
      <div ref={anchorRef} data-testid="header-more-wrap" className="relative hidden shrink-0 @max-[400px]/hdr:block">
        <button ref={moreRef} type="button" data-testid="header-more" aria-label={more} title={more} aria-haspopup="menu"
          aria-expanded={open} onClick={() => (menu ? setMenu(null) : openMenu())}
          className="grid h-6 w-[26px] place-items-center rounded-md border border-border text-muted-foreground hover:text-foreground">
          <MoreHorizontal size={14} /></button>
        {menu && <div ref={floatingRef} role="menu" data-testid="header-more-menu" onKeyDown={onMenuKeyDown}
          className="absolute right-0 top-full z-50 mt-1 w-56 rounded-lg border border-border-strong bg-surface-raised p-1 shadow-lg">
          {menu.map((item, index) => <button key={index} type="button" role="menuitem" data-kind={item.kind}
            onClick={() => { setMenu(null); item.el.click(); }}
            // The run state is still in the header down to 300px, so it is listed only below that.
            className={`${item.kind === "run" ? "hidden @max-[300px]/hdr:flex" : "flex"} w-full items-center rounded-md px-2.5 py-1.5 text-left text-[11px] text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground`}>
            <span className="truncate">{item.label}</span></button>)}
        </div>}
      </div>
    </div>
  </div>;
}
