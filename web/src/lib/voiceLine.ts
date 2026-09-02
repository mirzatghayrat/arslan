/**
 * The line protocol both voice helpers speak: one JSON object per line over a
 * pipe, forwarded verbatim by the shell as a Tauri event payload.
 *
 * Hold-to-talk (`arslan-listen`) sends ready/partial/final/error. Conversation
 * mode (`arslan-voice`) adds level/state, and the shell adds `ended` when the
 * helper exits. One parser, so a half-written line or a stray log line is
 * ignored the same way on both paths, never thrown.
 */
export type Line =
  | { t: 'ready' }
  | { t: 'partial'; text: string }
  | { t: 'final'; text: string }
  | { t: 'level'; peak: number }
  | { t: 'state'; muted?: boolean }
  | { t: 'ended' }
  | { t: 'error'; code: string; msg: string };

export function parseLine(raw: string): Line | null {
  try {
    const o = JSON.parse(raw);
    if (o && typeof o.t === 'string') return o as Line;
  } catch {
    /* a partial write or a stray log line is not worth a crash */
  }
  return null;
}

/** Turn an error code from a helper into something worth reading. */
export function errorMessage(code: string, fallback: string, t: (k: string) => string): string {
  switch (code) {
    case 'mic-denied':
    case 'speech-denied':
      return t('voice.errDenied');
    case 'mic-auth-timeout':
    case 'speech-auth-timeout':
      return t('voice.errNoAnswer');
    case 'locale-unsupported':
      return t('voice.errLocale');
    case 'no-input':
      return t('voice.errNoInput');
    default:
      return fallback;
  }
}
