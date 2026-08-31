/**
 * Test every configured model once, when the app opens.
 *
 * The old behaviour tested on Settings-open, which meant the answer only existed
 * where almost nobody looked, and only after they went looking. The question
 * "does my LLM work?" is one you have at the moment you try to use it, so it is
 * answered at launch: by the time anyone opens Settings — or glances at the
 * composer — the verdict is already there.
 *
 * Cost is the reason this is once per launch and not a poll: each test is one
 * real (tiny) chat call per configured model, and the user pays for it. Closing
 * and reopening the app tests again, which is the interval the user asked for.
 */

import type { ProviderConfig } from '../api/client.types';

export interface LaunchTestDeps {
  /** POST .../test — a real chat round-trip. Persists its own verdict. */
  test: (id: number) => Promise<{ ok: boolean; error?: string | null }>;
  onStart: (id: number) => void;
  onResult: (id: number, ok: boolean, error?: string | null) => void;
}

/**
 * Fire one test per config, concurrently, and report each as it lands.
 *
 * Never rejects: a provider being down is the normal case this exists to
 * detect, and one broken config must not stop the others from being tested.
 */
export async function runLaunchTests(
  configs: Pick<ProviderConfig, 'id'>[],
  deps: LaunchTestDeps,
): Promise<void> {
  await Promise.all(
    configs.map(async (c) => {
      deps.onStart(c.id);
      try {
        const r = await deps.test(c.id);
        deps.onResult(c.id, !!r.ok, r.error ?? null);
      } catch {
        // The request itself failed (backend down, offline). That is not a
        // verdict about the provider, so report it as a failure of THIS attempt
        // without a reason rather than inventing one about the model.
        deps.onResult(c.id, false, null);
      }
    }),
  );
}
