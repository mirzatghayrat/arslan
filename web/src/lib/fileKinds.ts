import { INPUT_FORMATS } from "./inputFormats";

/** How the reader shows a file (0.1.58 §2). */
export type FileKind = "markdown" | "html" | "pdf" | "image" | "video" | "audio" | "table" | "xlsx" | "doc"
  | "text" | "other";

const IMAGE: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif",
  webp: "image/webp", bmp: "image/bmp", svg: "image/svg+xml" };
const VIDEO: Record<string, string> = { mp4: "video/mp4", m4v: "video/mp4", mov: "video/quicktime", webm: "video/webm" };
const AUDIO: Record<string, string> = { mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", ogg: "audio/ogg", aac: "audio/aac" };

export const extOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : "");
export const baseName = (path: string) => path.replace(/\/+$/, "").split("/").pop() || path;
export const dirName = (path: string) => { const i = path.replace(/\/+$/, "").lastIndexOf("/"); return i > 0 ? path.slice(0, i) : ""; };

export function kindOf(name: string): FileKind {
  const ext = extOf(name);
  if (ext === "md" || ext === "markdown") return "markdown";
  if (ext === "html" || ext === "htm") return "html";
  if (ext === "pdf") return "pdf";
  if (IMAGE[ext]) return "image";
  if (VIDEO[ext]) return "video";
  if (AUDIO[ext]) return "audio";
  if (ext === "csv" || ext === "tsv") return "table";
  if (ext === "xlsx") return "xlsx";
  if (["docx", "doc", "rtf", "odt"].includes(ext)) return "doc";
  if ((INPUT_FORMATS.text as string[]).includes(ext) || ["txt", "log", "env.example", "conf", "cfg"].includes(ext)) return "text";
  return "other";
}

export function mimeOf(name: string): string {
  const ext = extOf(name);
  return IMAGE[ext] ?? VIDEO[ext] ?? AUDIO[ext] ?? (ext === "pdf" ? "application/pdf" : "application/octet-stream");
}

/** A small, safe CSV/TSV parser (quotes, doubled quotes, newlines inside quotes). */
export function parseDelimited(text: string, sep: string, maxRows: number): { rows: string[][]; truncated: boolean } {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === sep) { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
      if (rows.length >= maxRows) return { rows, truncated: i < text.length - 1 };
    } else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return { rows, truncated: false };
}
