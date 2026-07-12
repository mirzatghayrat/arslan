/**
 * Settings section registry — the single source of truth for the System
 * Settings side-nav. The six real sections host relocated cards; `scheduled`
 * and `usage` are placeholders this round (they render a "coming soon" hint and
 * point at Diagnostics, per the Settings-round scope: no endpoint wiring yet).
 */

export type SettingsSectionId =
  | 'providers' | 'search' | 'appearance' | 'access' | 'memory' | 'advanced'
  | 'scheduled' | 'usage';  // last two are placeholders this round

export interface SettingsSectionMeta {
  id: SettingsSectionId;
  labelKey: string;
  icon: string;          // lucide-react icon name
  placeholder?: boolean;
}

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  { id: 'providers',  labelKey: 'settings.navProviders',  icon: 'Sliders' },
  { id: 'search',     labelKey: 'settings.navSearch',     icon: 'Search' },
  { id: 'appearance', labelKey: 'settings.navAppearance', icon: 'Palette' },
  { id: 'access',     labelKey: 'settings.navAccess',     icon: 'KeyRound' },
  { id: 'memory',     labelKey: 'settings.navMemory',     icon: 'Database' },
  { id: 'advanced',   labelKey: 'settings.navAdvanced',   icon: 'Sliders' },
  { id: 'scheduled',  labelKey: 'settings.navScheduled',  icon: 'Clock',    placeholder: true },
  { id: 'usage',      labelKey: 'settings.navUsage',      icon: 'BarChart3', placeholder: true },
];
