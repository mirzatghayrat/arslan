import { FileCode, FileImage, FileSpreadsheet, FileText, FileType, FileVideo, FileAudio, Folder, File } from "lucide-react";
import { kindOf } from "../../lib/fileKinds";

const STYLE: Record<string, [typeof File, string]> = {
  markdown: [FileText, "text-info bg-info/10"], text: [FileText, "text-muted-foreground bg-fill"],
  html: [FileCode, "text-info bg-info/10"], pdf: [FileType, "text-danger bg-danger/10"],
  image: [FileImage, "text-primary bg-primary/10"], video: [FileVideo, "text-warning bg-warning/10"],
  audio: [FileAudio, "text-warning bg-warning/10"], table: [FileSpreadsheet, "text-success bg-success/10"],
  xlsx: [FileSpreadsheet, "text-success bg-success/10"], doc: [FileText, "text-info bg-info/10"],
  other: [File, "text-muted-foreground bg-fill"],
};

/** A file's (or folder's) small square icon, coloured by what kind of file it is. */
export default function FileIcon({ name, folder = false, size = 14 }: { name: string; folder?: boolean; size?: number }) {
  const [Icon, cls] = folder ? [Folder, "text-muted-foreground bg-fill"] : STYLE[kindOf(name)] ?? STYLE.other;
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-md ${cls}`} style={{ width: size + 12, height: size + 12 }} aria-hidden>
      <Icon size={size} />
    </span>
  );
}
