/** Phone v2, Mac side: a message sent from the iPhone carries a Remote mark in every chat style,
 *  and a message typed at the Mac carries none. */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll } from 'vitest';
import OrchestratorChat from '../components/OrchestratorChat';
import type { Message } from '../types';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }));
vi.mock('../api/client', () => ({ api: { extractAttachmentUrl: vi.fn(), extractAttachmentFile: vi.fn() } }));
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });

const history: Message[] = [
  { id: 'p', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'sent from the phone', timestamp: '10:00', fromPhone: true },
  { id: 'm', sender: 'user', senderName: 'You', senderAvatar: '🙂', text: 'typed at the Mac', timestamp: '10:01' },
  { id: 'a', sender: 'arslan', senderName: 'Arslan', senderAvatar: '🦁', text: 'on it', timestamp: '10:02' },
];

describe('Remote mark on phone messages', () => {
  it.each(['quartz', 'brutalist', 'linear'] as const)('%s style marks only the phone message', (style) => {
    render(<OrchestratorChat chatHistory={history} setChatHistory={vi.fn()} onSendMessage={vi.fn()} spawns={[]}
      currentStyle={style} setCurrentStyle={vi.fn()} activeThread={null} />);
    const chips = screen.getAllByTestId('from-phone');
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toBe('sidebar.remote · chat.fromPhone');
  });
});
