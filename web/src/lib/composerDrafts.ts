import type { Attachment } from '../components/ComposerAttach';

/** RAM only. Never serialize prepared files or image payloads to browser storage. */
export interface AttachmentDraft { items: Attachment[]; discarded: boolean }
export const composerDrafts = new Map<string, string>();
const attachmentDrafts = new Map<string, AttachmentDraft>();

export function getAttachmentDraft(key: string): AttachmentDraft {
  let draft = attachmentDrafts.get(key);
  if (!draft) {
    draft = { items: [], discarded: false };
    attachmentDrafts.set(key, draft);
  }
  return draft;
}

export function discardComposerDraft(key: string) {
  composerDrafts.delete(key);
  const draft = attachmentDrafts.get(key);
  if (!draft) return;
  draft.discarded = true;
  for (const item of draft.items) if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  draft.items = [];
  attachmentDrafts.delete(key);
}
