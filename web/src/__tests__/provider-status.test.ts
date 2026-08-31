/**
 * The status a provider dot shows. This is the piece the whole redesign turns
 * on: green used to mean "the model-list endpoint answered", which for a public
 * model list is true with no key at all. Green must now mean "a real message
 * went through and came back".
 */
import { describe, test, expect } from 'vitest';
import { providerStatus, isUsable } from '../lib/providerStatus';

const row = (over: Record<string, unknown> = {}) =>
  ({ last_health: null, last_health_at: null, last_health_detail: null, ...over }) as never;

describe('a stored verdict', () => {
  test('a passing chat test reads ok, with its timestamp', () => {
    const v = providerStatus(row({ last_health: 'ok', last_health_at: '2026-08-31T10:00:00' }));
    expect(v.status).toBe('ok');
    expect(v.at).toBe('2026-08-31T10:00:00');
    expect(v.reason).toBeNull();
  });

  test('a failing chat test carries its reason forward', () => {
    const v = providerStatus(row({
      last_health: 'failed',
      last_health_at: '2026-08-31T10:00:00',
      last_health_detail: '这把 API key 设了额度上限,已经触顶。',
    }));
    expect(v.status).toBe('failed');
    // The reason surviving is the point: "failed" with no cause is only
    // marginally more useful than a green dot that lies.
    expect(v.reason).toContain('额度上限');
  });

  test('never tested is untested — not ok', () => {
    expect(providerStatus(row()).status).toBe('untested');
  });

  test('an empty string is untested', () => {
    expect(providerStatus(row({ last_health: '' })).status).toBe('untested');
  });

  test.each(['reachable_models', 'reachable_no_list', 'unreachable'])(
    'the retired probe word %s reads as untested, never as a verdict',
    (retired) => {
      // A row from a build predating migration 0043, or one it missed. The whole
      // reason these words are retired is that they could not answer this
      // question — so they must not be allowed to answer it now.
      const v = providerStatus(row({ last_health: retired, last_health_at: '2026-08-31T10:00:00' }));
      expect(v.status).toBe('untested');
      expect(v.at).toBeNull();
    },
  );
});

describe('a test running in this session', () => {
  test('testing outranks any stored verdict', () => {
    const v = providerStatus(row({ last_health: 'ok' }), { state: 'testing' });
    expect(v.status).toBe('testing');
  });

  test('a fresh failure outranks a stored pass', () => {
    const v = providerStatus(row({ last_health: 'ok' }), { state: 'failed', error: '余额不足' });
    expect(v.status).toBe('failed');
    expect(v.reason).toBe('余额不足');
  });

  test('a fresh pass outranks a stored failure', () => {
    const v = providerStatus(
      row({ last_health: 'failed', last_health_detail: 'old reason' }),
      { state: 'ok' },
    );
    expect(v.status).toBe('ok');
    expect(v.reason).toBeNull();
  });

  test('idle defers to what was stored', () => {
    const v = providerStatus(row({ last_health: 'ok' }), { state: 'idle' });
    expect(v.status).toBe('ok');
  });
});

describe('isUsable', () => {
  test.each([
    ['ok', true],
    ['untested', true],
    ['testing', true],
    ['failed', false],
  ] as const)('%s → usable=%s', (status, expected) => {
    expect(isUsable({ status, reason: null, at: null })).toBe(expected);
  });

  test('untested is usable — a fresh install has tested nothing', () => {
    // Refusing to route anywhere on a clean install would be worse than trying;
    // only a verdict we actually hold takes a model out of play.
    expect(isUsable(providerStatus(row()))).toBe(true);
  });
});
