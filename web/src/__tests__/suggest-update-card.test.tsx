import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import SuggestUpdateCard from '../components/SuggestUpdateCard';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string, o?: Record<string, unknown>) => (o?.name ? `${k}:${o.name}` : k) }) }));

const current = {
  persona_role: 'a witty copywriter', persona_tone: 'playful',
  capabilities: ['copywriting'], toolsets: ['web_search_scraping'], skills: ['humanizer'],
};

describe('SuggestUpdateCard', () => {
  it('renders before→after + equipment delta and confirms', () => {
    const onConfirm = vi.fn();
    const onDismiss = vi.fn();
    render(
      <SuggestUpdateCard
        spawnName="小测"
        current={current}
        changes={{ persona_tone: 'formal', add_toolsets: ['deck'], remove_skills: ['humanizer'] }}
        reason="按你的要求改正式"
        onConfirm={onConfirm}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByText('orchestrator.update_title:小测')).toBeTruthy();
    expect(screen.getByText('playful')).toBeTruthy();     // before (struck through)
    expect(screen.getByText('formal')).toBeTruthy();      // after
    expect(screen.getByText('deck')).toBeTruthy();        // +deck chip
    expect(screen.getByText('humanizer')).toBeTruthy();   // -humanizer chip
    // dismiss works before confirm…
    fireEvent.click(screen.getByText('orchestrator.update_dismiss'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    // …confirm fires once, then the card locks (applying state): re-clicks are dead
    const confirmBtn = screen.getByText('orchestrator.update_confirm').closest('button')!;
    fireEvent.click(confirmBtn);
    fireEvent.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(confirmBtn.disabled).toBe(true);
  });
});
