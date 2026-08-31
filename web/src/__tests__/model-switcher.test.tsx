/**
 * The composer's model chip.
 *
 * It rendered a bare "·" for as long as the multi-config list has existed,
 * because it read `settings.llm_provider` / `settings.llm_model` — two fields
 * adapters.ts explicitly stopped mapping. These tests pin it to the real rows,
 * and to the thing that makes the chip worth clicking: a model that cannot work
 * says so, and says why, BEFORE you pick it.
 */
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { changeLanguage: vi.fn() } }),
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}));

import ModelSwitcher from '../components/ModelSwitcher';
import type { ProviderConfig, ProviderOption } from '../api/client.types';

const providers: ProviderOption[] = [
  { key: 'deepseek', label: 'DeepSeek', base_url: '', default_model: 'deepseek-chat', native: false, models: [] },
  { key: 'custom', label: 'OpenRouter', base_url: '', default_model: '', native: false, models: [] },
];

const cfg = (over: Partial<ProviderConfig>): ProviderConfig => ({
  id: 1, label: 'A', provider: 'deepseek', model: 'deepseek-chat',
  base_url: '', api_key: '', is_primary: false, ...over,
} as ProviderConfig);

describe('what the chip shows', () => {
  it('names the primary model instead of the dead flat fields', () => {
    render(
      <ModelSwitcher
        configs={[cfg({ id: 1, is_primary: false }), cfg({ id: 2, provider: 'custom', model: 'anthropic/claude-sonnet-5', is_primary: true })]}
        llmProviders={providers}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId('model-switcher')).toHaveTextContent('OpenRouter');
    expect(screen.getByTestId('model-switcher')).toHaveTextContent('anthropic/claude-sonnet-5');
  });

  it('falls back to the first config when nothing is marked primary', () => {
    render(<ModelSwitcher configs={[cfg({ id: 5, model: 'only-one' })]} llmProviders={providers} onSelect={vi.fn()} />);
    expect(screen.getByTestId('model-switcher')).toHaveTextContent('only-one');
  });

  it('offers a way in when no model is configured at all', () => {
    const onManage = vi.fn();
    render(<ModelSwitcher configs={[]} llmProviders={providers} onSelect={vi.fn()} onManage={onManage} />);
    // Not a chip showing nothing — the empty state IS the invitation to fix it.
    expect(screen.getByTestId('model-switcher-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('model-switcher')).toBeNull();
  });

  it.each([
    ['ok', 'ok'],
    ['failed', 'failed'],
    [null, 'untested'],
  ])('carries the stored verdict %s onto the dot as %s', (stored, expected) => {
    render(
      <ModelSwitcher
        configs={[cfg({ is_primary: true, last_health: stored as string | null })]}
        llmProviders={providers}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId('model-switcher-dot')).toHaveAttribute('data-status', expected);
  });

  it('shows a launch test still in flight as testing, not as working', () => {
    render(
      <ModelSwitcher
        configs={[cfg({ id: 3, is_primary: true, last_health: 'ok' })]}
        llmProviders={providers}
        testingIds={new Set([3])}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByTestId('model-switcher-dot')).toHaveAttribute('data-status', 'testing');
  });
});

describe('switching', () => {
  it('opens on click and lists every configured model', async () => {
    const user = userEvent.setup();
    render(
      <ModelSwitcher
        configs={[cfg({ id: 1, is_primary: true }), cfg({ id: 2, provider: 'custom', model: 'm2' })]}
        llmProviders={providers}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('model-switcher-menu')).toBeNull();
    await user.click(screen.getByTestId('model-switcher'));
    expect(screen.getByTestId('model-switcher-option-1')).toBeInTheDocument();
    expect(screen.getByTestId('model-switcher-option-2')).toBeInTheDocument();
  });

  it('picking one reports it and closes', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <ModelSwitcher
        configs={[cfg({ id: 1, is_primary: true }), cfg({ id: 2, model: 'm2' })]}
        llmProviders={providers}
        onSelect={onSelect}
      />,
    );
    await user.click(screen.getByTestId('model-switcher'));
    await user.click(screen.getByTestId('model-switcher-option-2'));
    expect(onSelect).toHaveBeenCalledWith(2);
    expect(screen.queryByTestId('model-switcher-menu')).toBeNull();
  });

  it('a broken model shows WHY in the list, before you pick it', async () => {
    const user = userEvent.setup();
    render(
      <ModelSwitcher
        configs={[
          cfg({ id: 1, is_primary: true }),
          cfg({ id: 2, model: 'm2', last_health: 'failed', last_health_detail: '这把 API key 设了额度上限' }),
        ]}
        llmProviders={providers}
        onSelect={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId('model-switcher'));
    const broken = screen.getByTestId('model-switcher-option-2');
    // The reason replaces the model id — picking a model only to have the next
    // message fail is the loop this closes.
    expect(broken).toHaveTextContent('额度上限');
    expect(broken).not.toHaveTextContent('m2');
  });

  it('a working model shows its id, not a reason', async () => {
    const user = userEvent.setup();
    render(
      <ModelSwitcher
        configs={[cfg({ id: 1, is_primary: true, model: 'good-model', last_health: 'ok' })]}
        llmProviders={providers}
        onSelect={vi.fn()}
      />,
    );
    await user.click(screen.getByTestId('model-switcher'));
    expect(screen.getByTestId('model-switcher-option-1')).toHaveTextContent('good-model');
  });

  it('Escape closes without selecting', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<ModelSwitcher configs={[cfg({ is_primary: true })]} llmProviders={providers} onSelect={onSelect} />);
    await user.click(screen.getByTestId('model-switcher'));
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('model-switcher-menu')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
