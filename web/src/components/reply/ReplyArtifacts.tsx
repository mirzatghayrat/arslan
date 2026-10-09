import type { ToolActivity } from "../../types";
import EChart from "../EChart";
import DeckDownloadCard from "../DeckDownloadCard";
import type { StoredArtifact } from "../../api/client.types";
import { useWorkbench } from "../../stores/workbenchStore";
import FileCard from "./FileCard";
import { useTranslation } from "react-i18next";

/** Cards shown inline; the rest are one click away in the workbench's 任务 tab. */
export const INLINE_FILES = 3;

/** One card per path: a file written twice in a turn shows its last version. */
export function lastVersions(files: StoredArtifact[] = []): StoredArtifact[] {
  const byPath = new Map<string, StoredArtifact>();
  for (const f of files) byPath.set(f.title, f);
  return [...byPath.values()];
}

/**
 * What the turn made, under the answer (0.1.58 §1): charts and SVG drawn inline, the deck
 * card, and files to download — kept exactly as the old tool card showed them, now without
 * the card around them. Files are cards that open in the reader (P2).
 *
 * 🔒 SECURITY: artifactSvg/artifactChart/artifactPptx are populated ONLY from the backend
 * render_chart/render_deck tool_result frame (arslanStore), NEVER from LLM message text.
 */
export default function ReplyArtifacts({ activity, files = [] }: { activity?: ToolActivity; files?: StoredArtifact[] }) {
  const { t } = useTranslation();
  const show = useWorkbench((s) => s.show);
  const has = activity?.artifactChart || activity?.artifactSvg || activity?.artifactPptx || files.length;
  if (!has) return null;
  return (
    <div className="flex max-w-xl flex-col gap-2 pl-5" data-testid="reply-artifacts">
      {activity?.artifactChart && <EChart option={activity.artifactChart} className="tool-chart" />}
      {activity?.artifactSvg && <div className="tool-chart" dangerouslySetInnerHTML={{ __html: activity.artifactSvg }} />}
      {activity?.artifactPptx && <DeckDownloadCard {...activity.artifactPptx} />}
      {files.length > 0 && <div className="flex flex-wrap gap-2" data-testid="reply-files">
        {files.slice(0, INLINE_FILES).map((f) => <FileCard key={`${f.run_id}-${f.filename}`} file={f} />)}
        {files.length > INLINE_FILES && <button type="button" onClick={() => show("task")} data-testid="reply-more-files"
          className="self-center text-[12px] text-subtle-foreground hover:text-foreground">{t("workbench.moreFiles", { count: files.length - INLINE_FILES })} ›</button>}
      </div>}
    </div>
  );
}
