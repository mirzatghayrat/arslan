import type { ToolActivity } from "../../types";
import EChart from "../EChart";
import DeckDownloadCard from "../DeckDownloadCard";
import ArtifactDownloads from "../ArtifactDownloads";

/**
 * What the turn made, under the answer (0.1.58 §1): charts and SVG drawn inline, the deck
 * card, and files to download — kept exactly as the old tool card showed them, now without
 * the card around them. (P2 turns files into cards that open in the reader.)
 *
 * 🔒 SECURITY: artifactSvg/artifactChart/artifactPptx are populated ONLY from the backend
 * render_chart/render_deck tool_result frame (arslanStore), NEVER from LLM message text.
 */
export default function ReplyArtifacts({ activity }: { activity?: ToolActivity }) {
  if (!activity) return null;
  const has = activity.artifactChart || activity.artifactSvg || activity.artifactPptx || activity.artifacts?.length;
  if (!has) return null;
  return (
    <div className="flex max-w-xl flex-col gap-2 pl-5" data-testid="reply-artifacts">
      {activity.artifactChart && <EChart option={activity.artifactChart} className="tool-chart" />}
      {activity.artifactSvg && <div className="tool-chart" dangerouslySetInnerHTML={{ __html: activity.artifactSvg }} />}
      {activity.artifactPptx && <DeckDownloadCard {...activity.artifactPptx} />}
      <ArtifactDownloads files={activity.artifacts} />
    </div>
  );
}
