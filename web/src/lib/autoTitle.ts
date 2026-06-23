/**
 * autoTitle.ts — helpers for auto-generating concise thread titles after the
 * first user→assistant exchange completes (Claude/ChatGPT-style).
 *
 * Kept pure / side-effect-free so it is easy to unit-test without React.
 */

import type { Message } from "../types";

/** Placeholder title patterns set when a thread is first created. */
const PLACEHOLDER_PATTERNS = [
  "New Session",
  /^Orchestration thread #\d+$/,
] as const;

function isPlaceholderTitle(title: string): boolean {
  return PLACEHOLDER_PATTERNS.some((p) =>
    typeof p === "string" ? title === p : p.test(title),
  );
}

/**
 * A thread should receive an auto-generated title when:
 *   1. Its title is still a placeholder (either the raw default or the raw
 *      first-message truncation — we treat any title that looks like a
 *      placeholder OR was never explicitly set as eligible).
 *   2. It has exactly one user message AND at least one assistant (arslan/spawn)
 *      reply (i.e. the first exchange has completed).
 *   3. The title hasn't already been generated (caller tracks this externally
 *      via a Set of titled threadIds).
 *
 * NOTE: We do NOT gate on `isPlaceholderTitle` alone, because the dumb rename
 * in App.tsx already replaces "New Session" with the truncated user text, which
 * is NOT a placeholder string. We therefore treat any thread with exactly one
 * user message as a candidate — if it has a truly custom title the caller should
 * mark it as already-titled in its tracking set.
 */
export function shouldAutoTitle(thread: {
  title: string;
  history: Message[];
}): boolean {
  const userMessages = thread.history.filter((m) => m.sender === "user");
  const assistantMessages = thread.history.filter(
    (m) => m.sender === "arslan" || m.sender === "spawn",
  );
  // Must have exactly one user message (first exchange) and at least one reply.
  if (userMessages.length !== 1 || assistantMessages.length === 0) return false;
  return true;
}

/**
 * Fire-and-forget: calls `generate` with the first user + first assistant texts,
 * then calls `onTitle(threadId, generatedTitle)` with the result.
 *
 * On error, does NOT call `onTitle` — the existing placeholder title is kept.
 */
export async function maybeAutoTitle(
  threadId: string,
  thread: { history: Message[] },
  generate: (firstMessage: string, firstReply?: string) => Promise<{ title: string }>,
  onTitle: (threadId: string, title: string) => void,
): Promise<void> {
  const firstUser = thread.history.find((m) => m.sender === "user");
  const firstAssistant = thread.history.find(
    (m) => m.sender === "arslan" || m.sender === "spawn",
  );
  if (!firstUser) return;

  try {
    const result = await generate(firstUser.text, firstAssistant?.text);
    if (result.title) {
      onTitle(threadId, result.title);
    }
  } catch {
    // graceful fallback: keep placeholder title, do not call onTitle
  }
}
