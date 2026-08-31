/**
 * The launch-time sweep. What matters here is that it is resilient — one dead
 * provider must not stop the others being tested — and that a transport failure
 * is not dressed up as a verdict about the model.
 */
import { describe, test, expect, vi } from 'vitest';
import { runLaunchTests } from '../lib/launchTest';

const cfgs = [{ id: 1 }, { id: 2 }, { id: 3 }];

describe('runLaunchTests', () => {
  test('tests every configured model exactly once', async () => {
    const test = vi.fn().mockResolvedValue({ ok: true });
    await runLaunchTests(cfgs, { test, onStart: vi.fn(), onResult: vi.fn() });
    expect(test).toHaveBeenCalledTimes(3);
    expect(test.mock.calls.map((c) => c[0]).sort()).toEqual([1, 2, 3]);
  });

  test('marks each as testing before its result lands', async () => {
    const onStart = vi.fn();
    await runLaunchTests(cfgs, { test: vi.fn().mockResolvedValue({ ok: true }), onStart, onResult: vi.fn() });
    expect(onStart.mock.calls.map((c) => c[0]).sort()).toEqual([1, 2, 3]);
  });

  test('one failing provider does not stop the others', async () => {
    const test = vi.fn(async (id: number) => {
      if (id === 2) throw new Error('network down');
      return { ok: true };
    });
    const onResult = vi.fn();
    await runLaunchTests(cfgs, { test, onStart: vi.fn(), onResult });
    expect(onResult).toHaveBeenCalledTimes(3);
    expect(onResult).toHaveBeenCalledWith(1, true, null);
    expect(onResult).toHaveBeenCalledWith(3, true, null);
  });

  test('a thrown request reports failure with no invented reason', async () => {
    const onResult = vi.fn();
    await runLaunchTests([{ id: 7 }], {
      test: vi.fn().mockRejectedValue(new Error('backend unreachable')),
      onStart: vi.fn(),
      onResult,
    });
    // The backend being unreachable says nothing about the provider — surfacing
    // "backend unreachable" as the model's reason would be a fresh lie.
    expect(onResult).toHaveBeenCalledWith(7, false, null);
  });

  test("carries the provider's own reason through", async () => {
    const onResult = vi.fn();
    await runLaunchTests([{ id: 9 }], {
      test: vi.fn().mockResolvedValue({ ok: false, error: '额度上限已触顶' }),
      onStart: vi.fn(),
      onResult,
    });
    expect(onResult).toHaveBeenCalledWith(9, false, '额度上限已触顶');
  });

  test('no configs is a no-op, not a crash', async () => {
    const test = vi.fn();
    await expect(runLaunchTests([], { test, onStart: vi.fn(), onResult: vi.fn() })).resolves.toBeUndefined();
    expect(test).not.toHaveBeenCalled();
  });

  test('never rejects even when every provider throws', async () => {
    await expect(runLaunchTests(cfgs, {
      test: vi.fn().mockRejectedValue(new Error('all down')),
      onStart: vi.fn(),
      onResult: vi.fn(),
    })).resolves.toBeUndefined();
  });
});
