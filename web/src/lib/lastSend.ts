/**
 * SMART-3 (PR 696's review): the last message this window sent in each conversation, attachments included, so "switch this
 * chat and retry" sends exactly that again: an image the first model refused has to reach the next one. Memory only;
 * after a reload there is nothing, and the retry puts the text back in the composer instead of sending it bare.
 */
import type { ImagePayload } from './imagePayload';
import type { MessageAttachment } from '../types';

export type SentAttachments = { context: string; names: string[]; display?: MessageAttachment[]; images?: ImagePayload[] };

const sends = new Map<string, { text: string; attached?: SentAttachments }>();

export function rememberSend(conversationId: string, text: string, attached: SentAttachments | undefined): void {
  sends.set(conversationId, { text, attached });
}

export function lastSend(conversationId: string): { text: string; attached?: SentAttachments } | undefined {
  return sends.get(conversationId);
}
