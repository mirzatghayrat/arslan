// ThreadRowMenu — the per-conversation "⋯" overflow menu shown on each
// sidebar thread row. Opens a small inline menu (mirrors EquipPopover's
// click-away + absolute dialog pattern) with three actions:
//   · Distill  — harvest this conversation's spawn chats into memory
//   · Archive  — hide it into the collapsible "Archived" section (client-side)
//   · Delete   — opens an inline confirmation first, then removes it
// In the archived variant, "Archive" is swapped for "Unarchive".
//
// Purely presentational: all side effects are delegated to the callbacks the
// sidebar/App wire up. Styling uses semantic tokens only (no raw colors).
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { MoreHorizontal, Wand2, Archive, ArchiveRestore, Trash2, AlertTriangle } from "lucide-react";

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
  const [confirming, setConfirming] = useState(false);

  const close = () => {
    setOpen(false);
    setConfirming(false);
  };

  const itemClass =
    "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[11px] font-sans text-left text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] transition-all";

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={t("sidebar.thread_menu")}
        title={t("sidebar.thread_menu")}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
          setConfirming(false);
        }}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 aria-expanded:opacity-100 w-5 h-5 flex items-center justify-center rounded text-subtle-foreground hover:text-primary hover:bg-primary/10 transition-all shrink-0"
        aria-expanded={open}
        aria-haspopup="menu"
      >
        <MoreHorizontal className="w-3.5 h-3.5" />
      </button>

      {open && (
        <>
          {/* click-away layer */}
          <div
            className="fixed inset-0 z-40"
            onClick={(e) => {
              e.stopPropagation();
              close();
            }}
          />
          <div
            role="menu"
            onClick={(e) => e.stopPropagation()}
            className="absolute right-0 top-6 z-50 w-52 bg-surface-raised border border-border-strong rounded-lg shadow-lg p-1"
          >
            {!confirming ? (
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
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 className="w-3.5 h-3.5 shrink-0" />
                  <span>{t("sidebar.delete")}</span>
                </button>
              </>
            ) : (
              <div className="p-1.5 space-y-2.5">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-danger shrink-0 mt-0.5" />
                  <p className="text-[10.5px] font-sans text-muted-foreground leading-relaxed">
                    {t("sidebar.delete_confirm_body")}
                  </p>
                </div>
                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    className="px-2.5 py-1 rounded-md text-[10.5px] font-sans font-medium text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04] transition-all"
                    onClick={close}
                  >
                    {t("common.cancel")}
                  </button>
                  <button
                    type="button"
                    className="px-2.5 py-1 rounded-md text-[10.5px] font-sans font-bold text-danger bg-danger/10 border border-danger/30 hover:bg-danger/20 transition-all"
                    onClick={() => {
                      onDelete(threadId);
                      close();
                    }}
                  >
                    {t("sidebar.delete_confirm_ok")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </span>
  );
}
