import { getVersion } from '@tauri-apps/api/app';
import { updaterAvailable } from './updater';

export type AppIdentity = {
  client: 'desktop' | 'browser';
  version: string | null;
  channel: 'stable' | 'preview' | 'unknown';
};

/** Read the running shell, never the backend's independent package version. */
export async function readAppIdentity(): Promise<AppIdentity> {
  if (!updaterAvailable()) return { client: 'browser', version: null, channel: 'unknown' };
  try {
    const version = await getVersion();
    // An unavailable or malformed version must not be presented as stable.
    const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.exec(version);
    if (!match || version.length > 100) throw new Error('invalid version');
    return { client: 'desktop', version, channel: match[4] ? 'preview' : 'stable' };
  } catch {
    return { client: 'desktop', version: null, channel: 'unknown' };
  }
}

/** Deliberate allowlist: no prompts, paths, model settings, logs or credentials. */
export function identitySummary(identity: AppIdentity): string {
  return [
    'Arslan — app identity',
    `client: ${identity.client}`,
    `version: ${identity.version ?? 'unknown'}`,
    `channel: ${identity.channel}`,
  ].join('\n');
}
