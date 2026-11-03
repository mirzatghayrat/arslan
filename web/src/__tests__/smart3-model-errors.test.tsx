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

import OrchestratorChat from '../components/OrchestratorChat';
import { useArslanStore } from '../stores/arslanStore';
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
  it("names the chat's model and switches this chat to another one, then sends the last message again", async () => {
    conv.get.mockResolvedValue({ choice: null });
    conv.set.mockResolvedValue({ choice: { config_id: 3, model: 'claude-sonnet-5-5' } });
    const onSendMessage = vi.fn();
    render(<OrchestratorChat {...props} chatHistory={history} onSendMessage={onSendMessage} conversationId="c1" providerConfigs={configs} />);
    failed({ role: 'chat', provider: 'deepseek', model: 'deepseek-v4-flash' });
    expect(screen.getByTestId('chat-error-call').textContent).toContain('deepseek · deepseek-v4-flash');
    const button = screen.getByTestId('chat-error-switch');
    expect(button.textContent).toContain('claude-sonnet-5-5');
    await act(async () => { fireEvent.click(button); });
    expect(conv.set).toHaveBeenCalledWith('c1', 3, 'claude-sonnet-5-5');
    expect(onSendMessage).toHaveBeenCalledWith('Plan my week', undefined);
    expect(useArslanStore.getState().error).toBeNull();
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
