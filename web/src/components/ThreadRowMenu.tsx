// ThreadRowMenu — the per-conversation "⋯" overflow menu shown on each
// sidebar thread row. Portalled and dismissable via the shared primitives, with
// three actions:
//   · Distill  — harvest this conversation's spawn chats into memory
//   · Archive  — hide it into the collapsible "Archived" section (client-side)
//   · Delete   — opens an inline confirmation first, then removes it
// In the archived variant, "Archive" is swapped for "Unarchive".
//
// Purely presentational: all side effects are delegated to the callbacks the
// sidebar/App wire up. Styling uses semantic tokens only (no raw colors).
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useDismissable } from "../hooks/useDismissable";
import AnchoredPortal from "./AnchoredPortal";
import { MoreHorizontal, Wand2, Archive, ArchiveRestore, Trash2 } from "lucide-react";
import { confirmSheet } from "./kit";

interface ThreadRowMenuProps {
  threadId: string;
  /** When true, the menu offers "Unarchive" instead of "Archive". */
  archived?: boolean;
  onDistill: (id: string) => void;
  onArchive: (id: string) => void;
  onUnarchive?: (id: string) => void;
  onDelete: (id: string) => void;
}

export default function ThreadRowMenu({
  threadId,
  archived = false,
  onDistill,
  onArchive,
  onUnarchive,
  onDelete,
}: ThreadRowMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const close = () => {
    setOpen(false);
  };

  // Two fixes, one cause each:
  //  · the menu was `absolute` inside the thread list's `overflow-y-auto`, so
  //    the BOTTOM row's menu was clipped — AnchoredPortal takes it out of that
  //    ancestor and flips it up near the viewport edge;
  //  · dismissal was a `fixed inset-0` backdrop, i.e. implemented as LAYOUT.
  //    Measured before replacing it: clicking the backdrop closed the menu,
  //    clicking anywhere else did not, and Escape did nothing at all.
  const { anchorRef, floatingRef } = useDismissable<HTMLSpanElement, HTMLDivElement>(open, close);

  const itemClass =
    "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[11px] font-sans text-left text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] transition-all";

  return (
    <span ref={anchorRef} className="relative inline-flex">
      <button
        type="button"
        aria-label={t("sidebar.thread_menu")}
        title={t("sidebar.thread_menu")}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 aria-expanded:opacity-100 w-5 h-5 flex items-center justify-center rounded text-subtle-foreground hover:text-primary hover:bg-primary/10 transition-all shrink-0"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <MoreHorizontal className="w-3.5 h-3.5" />
      </button>

      <AnchoredPortal anchorRef={anchorRef} floatingRef={floatingRef} open={open}>
        <div
          role="menu"
          onClick={(e) => e.stopPropagation()}
          className="w-52 bg-surface-raised border border-border-strong rounded-lg shadow-lg p-1"
        >
              <>
                <button
                  type="button"
                  role="menuitem"
                  className={itemClass}
                  onClick={() => {
                    onDistill(threadId);
                    close();
                  }}
                >
                  <Wand2 className="w-3.5 h-3.5 text-primary shrink-0" />
                  <span>{t("sidebar.distill")}</span>
                </button>

                {archived ? (
                  <button
                    type="button"
                    role="menuitem"
                    className={itemClass}
                    onClick={() => {
                      onUnarchive?.(threadId);
                      close();
                    }}
                  >
                    <ArchiveRestore className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
                    <span>{t("sidebar.unarchive")}</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    role="menuitem"
                    className={itemClass}
                    onClick={() => {
                      onArchive(threadId);
                      close();
                    }}
                  >
                    <Archive className="w-3.5 h-3.5 text-subtle-foreground shrink-0" />
                    <span>{t("sidebar.archive")}</span>
                  </button>
                )}

                <button
                  type="button"
                  role="menuitem"
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[11px] font-sans text-left text-danger hover:bg-danger/10 transition-all"
                  onClick={() => {
                    // 0.1.55: the one confirm sheet (it was an inline box inside this menu).
                    close();
                    void confirmSheet({ title: t("confirm.conversationTitle"), body: t("confirm.conversationBody"),
                      action: t("confirm.delete") }).then((ok) => { if (ok) onDelete(threadId); });
                  }}
                >
                  <Trash2 className="w-3.5 h-3.5 shrink-0" />
                  <span>{t("sidebar.delete")}</span>
                </button>
              </>
        </div>
      </AnchoredPortal>
    </span>
  );
}
