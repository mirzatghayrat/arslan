import { create } from 'zustand';
import { invoke } from '@tauri-apps/api/core';
import { shellAvailable } from '../lib/shell';

export const ICON_STYLES = ['frosted', 'monochrome'] as const;
export type IconStyle = typeof ICON_STYLES[number];
const KEY = 'arslan_icon_style';
export function isIconStyle(value: unknown): value is IconStyle {
  return value === 'frosted' || value === 'monochrome';
}
function load(): IconStyle {
  try { const value = localStorage.getItem(KEY); return isIconStyle(value) ? value : 'frosted'; }
  catch { return 'frosted'; }
}
function publish(style: IconStyle) {
  try { localStorage.setItem(KEY, style); } catch { /* Private browsing may deny persistence. */ }
  document.querySelector<HTMLLinkElement>('link[rel="icon"]')?.setAttribute('href', `/brand/${style}.png?v=20260923`);
}

interface IconState {
  style: IconStyle;
  pending: boolean;
  error: boolean;
  initialize: () => Promise<void>;
  select: (style: IconStyle) => Promise<void>;
}
export const useIconStore = create<IconState>((set, get) => ({
  style: load(), pending: false, error: false,
  initialize: async () => {
    if (get().pending) return;
    set({ pending: true });
    try {
      // Native preference survives the sidecar's port/origin changing at launch.
      const native = shellAvailable() ? await invoke<unknown>('get_app_icon') : get().style;
      const style = isIconStyle(native) ? native : 'frosted';
      publish(style); set({ style });
    } catch { publish(get().style); }
    finally { set({ pending: false }); }
  },
  select: async (style) => {
    if (get().pending || !isIconStyle(style)) return;
    set({ pending: true, error: false });
    try {
      if (shellAvailable()) await invoke('set_app_icon', { style });
      publish(style); set({ style });
    } catch { set({ error: true }); }
    finally { set({ pending: false }); }
  },
}));
