import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getFirstRunSeen, restoreFirstRunSeen, setFirstRunSeen } from '../lib/firstRun';

describe('durable onboarding state', () => {
  beforeEach(() => localStorage.clear());

  it('restores the backend flag with an empty origin-local store', async () => {
    const save = vi.fn();
    expect(await restoreFirstRunSeen(true, save)).toBe(true);
    expect(getFirstRunSeen()).toBe(true);
    expect(save).not.toHaveBeenCalled();
  });

  it('keeps a fresh installation unseen without writing', async () => {
    const save = vi.fn();
    expect(await restoreFirstRunSeen(false, save)).toBe(false);
    expect(save).not.toHaveBeenCalled();
  });

  it('migrates the legacy local flag', async () => {
    setFirstRunSeen();
    const save = vi.fn().mockResolvedValue({ first_run_seen: true });
    expect(await restoreFirstRunSeen(false, save)).toBe(true);
    expect(save).toHaveBeenCalledOnce();
  });

  it('keeps the legacy hint when migration fails and retries next load', async () => {
    setFirstRunSeen();
    const save = vi.fn().mockRejectedValue(new Error('offline'));
    expect(await restoreFirstRunSeen(false, save)).toBe(true);
    expect(await restoreFirstRunSeen(false, save)).toBe(true);
    expect(save).toHaveBeenCalledTimes(2);
  });

  it('restores after a simulated loopback-origin change', async () => {
    await restoreFirstRunSeen(true, vi.fn());
    localStorage.clear();
    expect(await restoreFirstRunSeen(true, vi.fn())).toBe(true);
  });
});
