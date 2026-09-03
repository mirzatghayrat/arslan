/**
 * The mode setting decides which microphone control the composer shows, and
 * a conversation final goes out through onSendMessage — the same door typing
 * uses — never into the text box.
 */
import { describe, test, expect, beforeEach, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import OrchestratorChat from '../components/OrchestratorChat';
import { useSettingsStore } from '../stores/settingsStore';
import type { Message } from '../types';

// Deterministic i18n — mirrors OrchestratorChat.attach.test.tsx's setup.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));

vi.mock('../api/client', () => ({
  api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() },
}));

let listeners: Array<(e: { payload: string }) => void>;
let invokes: Array<[string, unknown]>;
beforeEach(() => {
  listeners = []; invokes = [];
  (window as any).__TAURI__ = {
    core: { invoke: vi.fn(async (cmd: string, args?: unknown) => { invokes.push([cmd, args]); }) },
    event: { listen: vi.fn(async (_n: string, cb: any) => { listeners.push(cb); return () => {}; }) },
  };
  Element.prototype.scrollIntoView = vi.fn();
});

// A non-empty history so the thread composer (composer-row) renders — the
// same shape OrchestratorChat.attach.test.tsx uses for its default cases.
const history: Message[] = [
  { id: 'm1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'hi', timestamp: '10:00' },
];

const baseProps = {
  chatHistory: history,
  setChatHistory: vi.fn(),
  spawns: [],
  currentStyle: 'quartz' as const,
  setCurrentStyle: vi.fn(),
  activeThread: null,
};

describe('composer microphone control follows voice_mode', () => {
  test('push_to_talk shows the hold button, no toggle', () => {
    useSettingsStore.setState({ settings: { voice_mode: 'push_to_talk' } as any });
    render(<OrchestratorChat {...baseProps} onSendMessage={vi.fn()} />);
    expect(screen.getByTestId('push-to-talk')).toBeTruthy();
    expect(screen.queryByTestId('conversation-toggle')).toBeNull();
  });

  test('off shows neither', () => {
    useSettingsStore.setState({ settings: { voice_mode: 'off' } as any });
    render(<OrchestratorChat {...baseProps} onSendMessage={vi.fn()} />);
    expect(screen.queryByTestId('push-to-talk')).toBeNull();
    expect(screen.queryByTestId('conversation-toggle')).toBeNull();
  });

  test('conversation: toggle on, a final is sent and the text box is left alone', async () => {
    useSettingsStore.setState({ settings: { voice_mode: 'conversation', voice_endpoint_silence_ms: '900' } as any });
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...baseProps} onSendMessage={onSendMessage} />);
    const toggle = screen.getByTestId('conversation-toggle');
    await act(async () => { toggle.click(); await Promise.resolve(); await Promise.resolve(); });
    // Something half-typed and NOT yet sent. An empty box would pass this test
    // whether or not a final writes into it, which is the whole thing at stake:
    // a spoken sentence must go out the door, never land in someone's draft.
    const box = screen.getByPlaceholderText(/orchestrator\.placeholder/) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: 'half a thought' } });
    act(() => listeners.forEach((l) => l({ payload: '{"t":"final","text":"open the desktop"}' })));
    expect(onSendMessage).toHaveBeenCalledWith('open the desktop', undefined);
    expect(box.value).toBe('half a thought');
  });

  test('the silence setting reaches the helper clamped, not raw', async () => {
    // 50 ms is below the floor. The clamp lives in the settings adapter, but
    // this composer reads the backend store directly — so the only proof that
    // the clamp is on the path the endpointer actually gets is the argument
    // voice_conversation_start was invoked with.
    useSettingsStore.setState({ settings: { voice_mode: 'conversation', voice_endpoint_silence_ms: '50' } as any });
    render(<OrchestratorChat {...baseProps} onSendMessage={vi.fn()} />);
    await act(async () => { screen.getByTestId('conversation-toggle').click(); await Promise.resolve(); await Promise.resolve(); });
    const start = invokes.find(([c]) => c === 'voice_conversation_start');
    expect(start).toBeTruthy();
    expect((start![1] as any).silenceMs).toBe(300);
  });

  test('the empty-conversation composer also shows the mode-appropriate control', () => {
    useSettingsStore.setState({ settings: { voice_mode: 'conversation' } as any });
    render(<OrchestratorChat {...baseProps} chatHistory={[]} onSendMessage={vi.fn()} />);
    expect(screen.getByTestId('conversation-toggle')).toBeTruthy();
    expect(screen.queryByTestId('push-to-talk')).toBeNull();
  });
});
