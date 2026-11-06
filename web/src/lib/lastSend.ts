/**
 * SMART-3 (PR 696's review): the last message this window sent, attachments included, so "switch this chat and retry"
 * sends exactly that again: an image the first model refused has to reach the next one. One slot only (the newest send,
 * with its conversation), so file text and images don't pile up per conversation. Memory only; after a reload there is
 * nothing, and the retry puts the text back in the composer instead of sending it bare.
 */
import type { ImagePayload } from './imagePayload';
import type { MessageAttachment } from '../types';

export type SentAttachments = { context: string; names: string[]; display?: MessageAttachment[]; images?: ImagePayload[] };

let slot: { conversationId: string; text: string; attached?: SentAttachments } | null = null;

export function rememberSend(conversationId: string, text: string, attached: SentAttachments | undefined): void {
  slot = { conversationId, text, attached };
}

export function lastSend(conversationId: string): { text: string; attached?: SentAttachments } | undefined {
  return slot && slot.conversationId === conversationId ? { text: slot.text, attached: slot.attached } : undefined;
}
