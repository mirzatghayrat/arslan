import { useState } from "react";
import { useTranslation } from "react-i18next";
import { MoreHorizontal } from "lucide-react";
import { api } from "../../api/client";
import type { StoredArtifact } from "../../api/client.types";
import { useDismissable } from "../../hooks/useDismissable";
import { baseName, dirName } from "../../lib/fileKinds";
import { useWorkbench } from "../../stores/workbenchStore";
import FileIcon from "../workbench/FileIcon";

/**
 * A file the turn produced, as a card under the answer (0.1.58 §2): what it is, where, how big.
 * A click opens it in the reader; ⋯ downloads it or copies its path. (Its snapshot is what is
 * shown — the file as delivered, checked by size and checksum by the download route.)
 */
export default function FileCard({ file }: { file: StoredArtifact }) {
  const { t } = useTranslation();
  const openReader = useWorkbench((s) => s.openReader);
  const [menu, setMenu] = useState(false);
  const { anchorRef, floatingRef } = useDismissable<HTMLButtonElement, HTMLDivElement>(menu, () => setMenu(false));
  const name = baseName(file.title);
  const folder = dirName(file.title);
  async function download() {
    const blob = await api.downloadRunArtifact(file.run_id, file.filename);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const item = "block w-full rounded px-2 py-1.5 text-left text-[12px] hover:bg-foreground/5";
  return (
    <div className="flex w-[272px] max-w-full items-center gap-2.5 rounded-xl border border-border bg-background px-2.5 py-2" data-testid="file-card">
      <button type="button" onClick={() => openReader({ kind: "artifact", file })} className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
        data-testid={`file-card-open-${name}`}>
        <FileIcon name={name} size={15} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold">{name}</span>
          <span className="block truncate text-[11px] text-subtle-foreground">{folder ? `${folder} · ` : ""}{Math.max(1, Math.ceil(file.bytes / 1024))} KB</span>
        </span>
        <span className="shrink-0 rounded-md bg-fill px-2 py-0.5 text-[11.5px] text-muted-foreground">{t("workbench.preview")}</span>
      </button>
      <span className="relative">
        <button ref={anchorRef} type="button" aria-label={t("workbench.more")} aria-haspopup="menu" aria-expanded={menu}
          onClick={() => setMenu((v) => !v)} className="rounded p-1 text-subtle-foreground hover:bg-foreground/5"><MoreHorizontal size={15} /></button>
        {menu && <div ref={floatingRef} role="menu" className="absolute right-0 top-full z-30 mt-1 min-w-40 rounded-md border border-border bg-background p-1 shadow-md">
          <button type="button" role="menuitem" className={item} onClick={() => { setMenu(false); void download(); }}>{t("workbench.download")}</button>
          <button type="button" role="menuitem" className={item} onClick={() => { setMenu(false); void navigator.clipboard?.writeText(file.title); }}>
            {t("workbench.copyPath")}</button>
        </div>}
      </span>
    </div>
  );
}
