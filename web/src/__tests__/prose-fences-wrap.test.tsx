// SMART (the user, 2026-11-02): a fence of prose (```text, ```markdown, ```md, or no language at all) wraps, so a
// "message to send" block reads without scrolling sideways. A fence of code keeps its horizontal scroll, as Claude
// and ChatGPT do.
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
  Trans: ({ children }: { children?: unknown }) => children,
}));

import Markdown from '../components/Markdown';

afterEach(cleanup);

const LONG = 'Hi Lina, here is the week in one long line that should wrap rather than run off the side of the card '
  + 'and make you scroll sideways to read the end of it.';

function block(fence: string) {
  const { container } = render(<Markdown>{`Before\n\n${fence}\n${LONG}\n\`\`\`\n`}</Markdown>);
  const pre = container.querySelector('pre') as HTMLPreElement;
  expect(pre).not.toBeNull();
  return pre;
}

describe('prose fences wrap', () => {
  it.each(['```text', '```markdown', '```md', '```', '```TEXT', '```txt', '```plaintext'])('%s wraps', (fence) => {
    const pre = block(fence);
    expect(pre.style.whiteSpace).toBe('pre-wrap');
    expect(pre.style.overflowWrap).toBe('anywhere');
    expect(pre.textContent).toContain(LONG);                    // nothing is cut
  });

  it.each(['```python', '```bash', '```json', '```ts', '```diff', '```text-like'])(
    '%s keeps its horizontal scroll', (fence) => {
      const pre = block(fence);
      expect(pre.style.whiteSpace).toBe('pre');
      expect(pre.style.overflowX).toBe('auto');
    });

  it('a prose fence keeps its line breaks and indentation', () => {
    const { container } = render(<Markdown>{'```text\nline one\n    indented\n\nafter a blank\n```\n'}</Markdown>);
    expect((container.querySelector('pre') as HTMLPreElement).textContent).toBe('line one\n    indented\n\nafter a blank\n');
  });
});
