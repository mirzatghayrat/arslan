/**
 * SMART-3 (v0.1.64, model-switch part B): a failed model call says which call failed (the error frame's `call`), and
 * the window offers the way out: for the chat's own model, switch this chat to another configured model and send the
 * last message again; for a helper (vision and the like), open the model settings. User report: a chat kept failing
 * on DeepSeek's balance after the user picked Claude.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o ? `${k}:${JSON.stringify(o)}` : k), i18n: { resolvedLanguage: 'en' } }),
}));
const { conv } = vi.hoisted(() => ({ conv: { get: vi.fn(), set: vi.fn(), clear: vi.fn() } }));
vi.mock('../api/conversationModel', () => ({ conversationModelApi: conv }));
vi.mock('../api/client', async (orig) => ({ ...(await orig<object>()), fetchProviderModels: vi.fn(async () => ({ models: [] })) }));
// The voice conversation's final transcript is a send of its own; holding onFinal lets a test speak one.
const { voice } = vi.hoisted(() => ({ voice: { onFinal: undefined as undefined | ((text: string) => void) } }));
vi.mock('../hooks/useConversationMode', () => ({
  useConversationMode: (o: { onFinal: (text: string) => void }) => { voice.onFinal = o.onFinal; return { phase: 'idle', partial: '' }; },
}));

import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore } from '../stores/arslanStore';
import { lastSend, rememberSend } from '../lib/lastSend';
import { isModelSaving } from '../components/models/useConversationModel';
import { SAVE_TIMEOUT_MS } from '../components/models/ConversationModelChip';
import type { ProviderConfig } from '../api/client.types';
import type { Message } from '../types';

beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); vi.clearAllMocks(); useArslanStore.getState().clearError(); });

const configs = [
  { id: 1, label: 'DeepSeek', provider: 'deepseek', model: 'deepseek-v4-flash', is_primary: true },
  { id: 3, label: 'Anthropic', provider: 'anthropic', model: 'claude-sonnet-5-5', is_primary: false },
] as ProviderConfig[];
const history: Message[] = [{ id: 'u1', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'Plan my week', timestamp: '10:00' }];
const props = { setChatHistory: vi.fn(), spawns: [], currentStyle: 'quartz' as const, setCurrentStyle: vi.fn(), activeThread: null };

function failed(call: { role: string; provider: string; model: string }) {
  act(() => useArslanStore.getState().handleFrame({ type: 'error', code: 'LLM_ERROR', message: 'Insufficient Balance', call } as never));
}

describe('the error frame says which call failed', () => {
  it('keeps the call, and forgets it with the error', () => {
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    expect(useArslanStore.getState().errorCall).toEqual({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    act(() => useArslanStore.getState().clearError());
    expect(useArslanStore.getState().errorCall).toBeNull();
  });
});

describe('the error banner', () => {
  it("names the chat's model and switches this chat to another one, then sends the last message again, attachments too", async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    const attached = { context: '', names: ['photo.png'], images: [{ mime_type: 'image/png', data: 'AAAA' }] };
    rememberSend('c1', 'What is in this photo?', attached as never);
    const photo: Message[] = [{ ...history[0], text: 'What is in this photo?' }];
    render(<OrchestratorChat {...props} chatHistory={photo} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    expect(screen.getByTestId('chat-error-call').textContent).toContain('deepseek · deepseek-v4-flash');
    const button = screen.getByTestId('chat-error-switch');
    expect(button.textContent).toContain('claude-sonnet-5-5');
    await act(async () => { fireEvent.click(button); });
    expect(conv.set).toHaveBeenCalledWith('c1', 3, 'claude-sonnet-5-5');
    expect(onSendMessage).toHaveBeenCalledWith('What is in this photo?', attached);
    expect(useArslanStore.getState().error).toBeNull();
  });

  it('with no remembered send (after a reload), switches and puts the text back instead of sending it bare', async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    const { container } = render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c-reloaded"
      providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(conv.set).toHaveBeenCalledWith('c-reloaded', 3, 'claude-sonnet-5-5');
    expect(onSendMessage).not.toHaveBeenCalled();
    expect((container.querySelector('#chat-message-input') as HTMLTextAreaElement).value).toBe('Plan my week');
  });

  it('a clarify answer is recorded like a typed send, so the retry sends that answer', async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    const withCard: Message[] = [
      { id: '7', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: '', timestamp: '10:00',
        clarifyOptions: { question: 'Which week?', options: [{ label: 'Next week' }, { label: 'This week' }], answered: false } } as never,
      { id: 'u2', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'Next week', timestamp: '10:01' }];
    render(<OrchestratorChat {...props} chatHistory={withCard} onSendMessage={onSendMessage} conversationId="c-clarify" providerConfigs={configs} />);
    fireEvent.click(screen.getByRole('button', { name: /Next week/ }));
    onSendMessage.mockClear();
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(onSendMessage).toHaveBeenCalledWith('Next week', undefined);
  });

  it('never resends an older message: a newer one (a voice send, say) goes back to the composer instead', async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    rememberSend('c-voice', 'Older typed message', { context: '', names: ['a.png'], images: [{ mime_type: 'image/png', data: 'AA' }] } as never);
    const newer: Message[] = [{ id: 'u9', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'Newer spoken message', timestamp: '10:02' }];
    const { container } = render(<OrchestratorChat {...props} chatHistory={newer} onSendMessage={onSendMessage} conversationId="c-voice"
      providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(onSendMessage).not.toHaveBeenCalled();
    expect((container.querySelector('#chat-message-input') as HTMLTextAreaElement).value).toBe('Newer spoken message');
  });

  it('a voice send is remembered, so the retry sends the spoken message itself', async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    rememberSend('c-spoken', 'Older typed message', undefined);
    const { rerender } = render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage}
      conversationId="c-spoken" providerConfigs={configs} />);
    act(() => voice.onFinal?.('Newer spoken message'));
    expect(onSendMessage).toHaveBeenCalledWith('Newer spoken message', undefined);
    onSendMessage.mockClear();
    const spoken: Message[] = [{ id: 'u9', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'Newer spoken message', timestamp: '10:02' }];
    rerender(<OrchestratorChat {...props} chatHistory={spoken} onSendMessage={onSendMessage} conversationId="c-spoken" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(onSendMessage).toHaveBeenCalledWith('Newer spoken message', undefined);
  });

  it("compares with the newest USER message, so an Arslan message after it does not block the retry", async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    const attached = { context: '', names: ['a.png'], images: [{ mime_type: 'image/png', data: 'AA' }] };
    rememberSend('c-after', 'Plan my week', attached as never);
    const answered: Message[] = [...history,
      { id: 'a1', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'Looking at your calendar…', timestamp: '10:00' }];
    render(<OrchestratorChat {...props} chatHistory={answered} onSendMessage={onSendMessage} conversationId="c-after" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(onSendMessage).toHaveBeenCalledWith('Plan my week', attached);
  });

  it('remembers one send only, for the conversation it was in', () => {
    rememberSend('c-a', 'first', undefined);
    rememberSend('c-b', 'second', undefined);
    expect(lastSend('c-a')).toBeUndefined();
    expect(lastSend('c-b')?.text).toBe('second');
  });

  it('a double click switches and sends once', async () => {
    conv.get.mockResolvedValue({ choice: null });
    let land!: (v: unknown) => void;
    conv.set.mockImplementation(() => new Promise((resolve) => { land = resolve; }));
    const onSendMessage = vi.fn();
    rememberSend('c1', 'Plan my week', undefined);
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    const button = screen.getByTestId('chat-error-switch');
    await act(async () => { fireEvent.click(button); fireEvent.click(button); });
    await act(async () => { land({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } }); });
    expect(conv.set).toHaveBeenCalledTimes(1);
    expect(onSendMessage).toHaveBeenCalledTimes(1);
  });

  it('sends nothing if the conversation changed while the switch was saving', async () => {
    conv.get.mockResolvedValue({ choice: null });
    let land!: (v: unknown) => void;
    conv.set.mockImplementation(() => new Promise((resolve) => { land = resolve; }));
    const onSendMessage = vi.fn();
    rememberSend('c1', 'Plan my week', undefined);
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    act(() => useArslanStore.getState().resetForNewConversation());
    await act(async () => { land({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } }); });
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('a switch with no answer gives up after a while, keeps the error and sends nothing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      conv.get.mockResolvedValue({ choice: null });
      conv.set.mockImplementation(() => new Promise(() => {}));
      const onSendMessage = vi.fn();
      rememberSend('c1', 'Plan my week', undefined);
      render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
      failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
      await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
      expect(isModelSaving('c1')).toBe(true);
      await act(async () => { vi.advanceTimersByTime(SAVE_TIMEOUT_MS + 10); });
      expect(isModelSaving('c1')).toBe(false);
      expect(onSendMessage).not.toHaveBeenCalled();
      expect(useArslanStore.getState().error).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("with only one provider configured, offers that provider's other model", () => {
    conv.get.mockResolvedValue({ choice: null });
    const one = [configs[0], { id: 2, label: 'DeepSeek', provider: 'deepseek', model: 'deepseek-v4-pro', is_primary: false }] as ProviderConfig[];
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={vi.fn()} conversationId="c1" providerConfigs={one} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    expect(screen.getByTestId('chat-error-switch').textContent).toContain('deepseek-v4-pro');
  });

  it('keeps the error and sends nothing when the switch fails', async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockRejectedValue(new Error('provider_config_not_found'));
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    await act(async () => { fireEvent.click(screen.getByTestId('chat-error-switch')); });
    expect(onSendMessage).not.toHaveBeenCalled();
    expect(useArslanStore.getState().error).not.toBeNull();
  });

  it("for a helper's failure, opens the model settings instead of switching the chat", () => {
    conv.get.mockResolvedValue({ choice: null });
    const onOpenSettings = vi.fn();
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={vi.fn()} conversationId="c1" providerConfigs={configs}
      onOpenSettings={onOpenSettings} />);
    failed({ role: 'vision', provider: 'deepseek', model: 'deepseek-v4-flash' });
    expect(screen.queryByTestId('chat-error-switch')).toBeNull();
    expect(screen.getByTestId('chat-error-call').textContent).toContain('ui.errorRole_vision');
    fireEvent.click(screen.getByTestId('chat-error-settings'));
    expect(onOpenSettings).toHaveBeenCalled();
  });
});
