import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Messages longer than this render as a collapsible downloadable artifact. Configurable. */
export const LONG_OUTPUT_THRESHOLD = 800;

function previewOf(content: string): string {
  return content.split("\n").slice(0, 3).join("\n").slice(0, 200);
}

export default function MarkdownArtifact({
  title,
  content,
  downloadName,
}: {
  title: string;
  content: string;
  downloadName: string;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const download = () => {
    try {
      const blob = new Blob([content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadName;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExpanded(true);
    }
  };

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-brand">
          <span aria-hidden>📄 </span>{title} · {t("artifact.report")}
        </span>
        <div className="flex gap-2">
          <button onClick={() => setExpanded((e) => !e)} className="text-xs text-white/60 hover:text-white">
            {expanded ? t("artifact.collapse") : t("artifact.expand")}
          </button>
          <button onClick={download} className="text-xs text-brand hover:underline">
            {t("artifact.download")}
          </button>
        </div>
      </div>
      <p className="whitespace-pre-wrap text-sm text-white/80">
        {expanded ? content : `${previewOf(content)}…`}
      </p>
    </div>
  );
}
