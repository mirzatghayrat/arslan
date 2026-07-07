import { api } from "../api/client";

export const BUCKET = { text: "文本", web: "网页", pdf: "PDF", image: "图片", word: "Word" } as const;
export type BucketKey = keyof typeof BUCKET;

/** File name → bucket key, or null if unsupported. */
export function bucketForFile(name: string): BucketKey | null {
  const n = name.toLowerCase();
  if (/\.pdf$/.test(n)) return "pdf";
  if (/\.docx?$/.test(n)) return "word";
  if (/\.html?$/.test(n)) return "web";
  if (/\.(png|jpe?g|gif|webp|bmp)$/.test(n)) return "image";
  if (/\.(txt|md|markdown)$/.test(n)) return "text";
  return null;
}

/** Pasted input → bucket key (url → web, else text). */
export function bucketForText(input: string): BucketKey {
  return /^https?:\/\//.test(input.trim()) ? "web" : "text";
}

/** Find-or-create the collection named `bucketName`, return its id. */
async function bucketCollectionId(bucketName: string): Promise<number> {
  const cols = await api.listCollections();
  const found = cols.find((c) => c.name === bucketName);
  return found ? found.id : (await api.createCollection(bucketName)).id;
}

/** Feed a file into its type bucket. Throws on unsupported type. */
export async function feedFile(file: File) {
  const b = bucketForFile(file.name);
  if (!b) throw new Error(`不支持的格式:${file.name}`);
  return api.ingestCollectionFile(await bucketCollectionId(BUCKET[b]), file);
}

/** Feed pasted text or a URL into its bucket (文本 / 网页). */
export async function feedTextOrUrl(input: string) {
  const t = input.trim();
  const web = /^https?:\/\//.test(t);
  const id = await bucketCollectionId(web ? BUCKET.web : BUCKET.text);
  return api.ingestCollection(id, web ? { url: t } : { source: "粘贴", text: t });
}

/** Feed a file into a SPECIFIC collection (manual target — row drop). */
export async function feedFileInto(collectionId: number, file: File) {
  return api.ingestCollectionFile(collectionId, file);
}
