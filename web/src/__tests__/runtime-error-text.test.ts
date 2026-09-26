import { describe, expect, it } from 'vitest';
import { runtimeErrorText, runtimeErrorTranslations } from '../lib/runtimeErrorText';
import { initialArslanState, useArslanStore } from '../stores/arslanStore';

const messages = { en: 'English notice', zh: '中文提示', ja: '日本語通知', es: 'Aviso', de: 'Hinweis', fr: 'Avis' };

describe('runtime error translations', () => {
  it('retains legacy text while selecting all six languages at render time', () => {
    for (const [locale, message] of Object.entries(messages)) {
      expect(runtimeErrorText('fallback', runtimeErrorTranslations(messages), locale)).toBe(message);
    }
    expect(runtimeErrorText('fallback', messages, 'fr-FR')).toBe(messages.fr);
    expect(runtimeErrorText('exact raw diagnostic', null, 'zh')).toBe('exact raw diagnostic');
  });
  it.each([null, [], 'text', { en: 'partial' }, { ...messages, fr: 3 }, { ...messages, zh: ' ' }, { ...messages, en: 'x'.repeat(2001) }])(
    'rejects malformed or incomplete translation catalogs', value => {
      expect(runtimeErrorTranslations(value)).toBeNull();
    },
  );
  it('copies only supported locales and does not mutate input', () => {
    expect(runtimeErrorTranslations({ ...messages, unknown: 'extra' })).toEqual(messages);
    expect(runtimeErrorTranslations(messages)).not.toBe(messages);
  });
  it('clears translations on a subsequent raw error, dismiss, and reset', () => {
    useArslanStore.setState(initialArslanState(), true);
    const frame = { type: 'error', code: 'LLM_ERROR', message: messages.zh, message_i18n: messages } as const;
    useArslanStore.getState().handleFrame(frame);
    expect(useArslanStore.getState().errorTranslations).toEqual(messages);
    useArslanStore.getState().handleFrame({ type: 'error', code: 'LLM_ERROR', message: 'exact raw' });
    expect(useArslanStore.getState().errorTranslations).toBeNull();
    expect(useArslanStore.getState().error).toBe('exact raw');
    useArslanStore.getState().handleFrame(frame);
    useArslanStore.getState().clearError();
    expect(useArslanStore.getState().errorTranslations).toBeNull();
    useArslanStore.getState().handleFrame(frame);
    useArslanStore.setState(initialArslanState(), true);
    expect(useArslanStore.getState().errorTranslations).toBeNull();
  });
});
