import { api } from "../api/client";

/** Caller-provided translate function (react-i18next `t`). This module must not
 * import the i18n singleton (it would crash every test that mocks react-i18next),
 * so the rendering components pass their own `t` in. */
export type TranslateFn = (key: string, opts?: Record<string, unknown>) => string;

/** Bucket → locale key of its display/collection name (feed.bucket.*).
 *
 * KNOWN LIMIT (S4.2-d, deliberate): the translated name doubles as the
 * backend COLLECTION name (find-or-create at ingest). zh values equal the
 * pre-i18n originals, so existing zh users keep matching their collections —
 * but a user who switches UI language will find-or-create new locale-named
 * buckets from then on (old ones keep their data, nothing is lost or merged).
 * The full fix is a stable backend collection key with display-only
 * translation; registered as follow-up, out of this round's scope. */
export const BUCKET = {
  text: "feed.bucket.text",
  web: "feed.bucket.web",
  pdf: "feed.bucket.pdf",
  image: "feed.bucket.image",
  word: "feed.bucket.word",
} as const;
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
export async function feedFile(file: File, t: TranslateFn) {
  const b = bucketForFile(file.name);
  if (!b) throw new Error(t("feed.unsupported_format", { name: file.name }));
  return api.ingestCollectionFile(await bucketCollectionId(t(BUCKET[b])), file);
}

/** Feed pasted text or a URL into its bucket (文本 / 网页). */
export async function feedTextOrUrl(input: string, t: TranslateFn) {
  const trimmed = input.trim();
  const web = /^https?:\/\//.test(trimmed);
  const id = await bucketCollectionId(t(web ? BUCKET.web : BUCKET.text));
  return api.ingestCollection(id, web ? { url: trimmed } : { source: t("feed.paste_source"), text: trimmed });
}
