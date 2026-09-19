import { act, render, screen } from '@testing-library/react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import SpawnDirectChat from '../components/SpawnDirectChat';
import { initialArslanState, useArslanStore } from '../stores/arslanStore';
import type { Message } from '../types';

const locale = vi.hoisted(() => ({ language: 'zh' }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string) => key, i18n: { resolvedLanguage: locale.language },
}) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
let frameCallback: (frame: any) => void;
vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: (_path: string, callback: (frame: any) => void) => {
  frameCallback = callback;
  return { send: vi.fn(), reconnecting: false, setLastMessageId: vi.fn() };
} }));

const translations = { en: 'English runtime notice', zh: '中文运行提示', ja: '日本語の実行通知', es: 'Aviso de ejecución', de: 'Laufzeithinweis', fr: 'Avis d’exécution' };
const frame = { type: 'error', code: 'LLM_ERROR', message: translations.zh, message_i18n: translations } as const;
const history: Message[] = [{ id: 'm', sender: 'arslan', senderName: 'Arslan', senderAvatar: 'A', text: 'User and model prose stays exact', timestamp: '10:00' }];
const base = { chatHistory: history, setChatHistory: vi.fn(), spawns: [], currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(), activeThread: null };
const spawn = { id: '7', name: 'Fixture', avatarEmoji: 'A', domain: 'test', description: 'test', status: 'idle' as const, tools: [], skills: [], totalTasks: 0 };

beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
beforeEach(() => { locale.language = 'zh'; useArslanStore.setState(initialArslanState(), true); });

describe('already-visible runtime errors follow language changes', () => {
  it('updates the main banner without a new server frame and leaves raw errors exact', () => {
    act(() => useArslanStore.getState().handleFrame(frame));
    const { rerender } = render(<OrchestratorChat {...base} />);
    for (const [language, text] of Object.entries(translations)) {
      locale.language = language;
      rerender(<OrchestratorChat {...base} />);
      expect(screen.getByText(text)).toBeInTheDocument();
      expect(screen.getByText(history[0].text)).toBeInTheDocument();
    }
    act(() => useArslanStore.getState().handleFrame({ type: 'error', code: 'LLM_ERROR', message: 'Raw diagnostic 123' }));
    locale.language = 'ja';
    rerender(<OrchestratorChat {...base} />);
    expect(screen.getByText('Raw diagnostic 123')).toBeInTheDocument();
    expect(screen.queryByText(translations.ja)).not.toBeInTheDocument();
  });

  it.each(['quartz', 'linear', 'brutalist'] as const)('updates direct-chat error bubbles in %s without changing history prose', currentStyle => {
    const { rerender } = render(<SpawnDirectChat spawn={spawn} currentStyle={currentStyle} />);
    act(() => frameCallback({ type: 'history', messages: [{ message_id: 1, role: 'assistant', content: 'Original model prose' }] }));
    act(() => frameCallback(frame));
    for (const [language, text] of Object.entries(translations)) {
      locale.language = language;
      rerender(<SpawnDirectChat spawn={spawn} currentStyle={currentStyle} />);
      expect(screen.getByText('⚠️ ' + text)).toBeInTheDocument();
      expect(screen.getByText('Original model prose')).toBeInTheDocument();
    }
    act(() => frameCallback({ type: 'error', code: 'LLM_ERROR', message: 'Exact raw diagnostic' }));
    locale.language = 'zh';
    rerender(<SpawnDirectChat spawn={spawn} currentStyle={currentStyle} />);
    expect(screen.getByText('⚠️ Exact raw diagnostic')).toBeInTheDocument();
  });
});
