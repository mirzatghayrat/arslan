/**
 * Settings section registry — the single source of truth for the Settings
 * side-nav, and (via `FIELD_HOMES`) the contract that no existing control is
 * lost when sections move.
 *
 * 0.1.55 §11: eleven sections in three groups became seven flat ones, named for
 * what a person is looking for (General, Models, What Arslan can do, Background,
 * Memory & privacy, Connections, About) rather than for how the code is split.
 * Old ids still resolve through `LEGACY_SECTION`, so deep links keep working.
 *
 * The two placeholder sections (`scheduled`, `usage`) stay gone. They rendered a
 * "coming soon" card pointing at Diagnostics; the pointer survives as a link in
 * `background` and on the About page.
 */

export type SettingsSectionId =
  | 'general' | 'models' | 'abilities' | 'background' | 'memory' | 'connections' | 'about';

/** 0.1.55 §11: one flat list of seven. Kept as a type for callers that still pass a group. */
export type SettingsGroupId = 'all';

export interface SettingsGroupMeta {
  id: SettingsGroupId;
  labelKey: string;
}

export interface SettingsSectionMeta {
  id: SettingsSectionId;
  group: SettingsGroupId;
  labelKey: string;
  icon: string;          // lucide-react icon name
  /** One sentence: what lives here (shown at the top of the section, and searched). */
  hintKey?: string;
}

/** 0.1.55 §11: no group headings — seven entries are read at a glance. */
export const SETTINGS_GROUPS: SettingsGroupMeta[] = [];

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  { id: 'general',     group: 'all', labelKey: 'settings.navGeneral',     icon: 'SlidersHorizontal', hintKey: 'settings.hintGeneral' },
  { id: 'models',      group: 'all', labelKey: 'settings.navModels',      icon: 'Cpu',               hintKey: 'settings.hintModels' },
  { id: 'abilities',   group: 'all', labelKey: 'settings.navAbilities',   icon: 'Hand',              hintKey: 'settings.hintAbilities' },
  { id: 'background',  group: 'all', labelKey: 'settings.navBackground',  icon: 'BellRing',          hintKey: 'settings.hintBackground' },
  { id: 'memory',      group: 'all', labelKey: 'settings.navMemoryPrivacy', icon: 'Database',        hintKey: 'settings.hintMemory' },
  { id: 'connections', group: 'all', labelKey: 'settings.navConnections', icon: 'Globe',             hintKey: 'settings.hintConnections' },
  { id: 'about',       group: 'all', labelKey: 'settings.navAbout',       icon: 'Info',              hintKey: 'settings.hintAbout' },
];

/** Section ids from before 0.1.55, so an old deep link still lands on the right page. */
export const LEGACY_SECTION: Record<string, SettingsSectionId> = {
  modelroles: 'models', search: 'connections', appearance: 'general', automation: 'background',
  proactive: 'background', desktop: 'general', phone: 'connections', access: 'connections', advanced: 'abilities',
};

export function resolveSection(id: string | undefined): SettingsSectionId | undefined {
  if (!id) return undefined;
  if (SETTINGS_SECTIONS.some((s) => s.id === id)) return id as SettingsSectionId;
  return LEGACY_SECTION[id];
}

/**
 * Every control that exists, and the section it lives in — the "not one field is
 * lost" table as data, so a test checks it instead of a person re-reading screens.
 * 0.1.55 §11 rehomed every key that existed before; none was dropped.
 */
export const FIELD_HOMES: Record<string, SettingsSectionId> = {
  'provider.list': 'models',
  'provider.api_key': 'models',
  'provider.base_url': 'models',
  'provider.model': 'models',
  'provider.primary': 'models',
  'provider.add': 'models',
  'provider.delete': 'models',
  'provider.connection_test': 'models',
  'provider.capabilities': 'models',
  'llm.strategy': 'models',
  'slot.compaction': 'models',
  'slot.title': 'models',
  'slot.synthesis': 'models',
  'slot.vision': 'models',
  'slot.router': 'models',
  'search.tools': 'connections',
  'appearance.display_name': 'general',
  'appearance.language': 'general',
  'appearance.theme': 'general',
  'appearance.ocr_languages': 'general',
  'memory.in_conversations': 'memory',
  'memory.learned_practices': 'memory',
  'memory.distill_on_session_end': 'memory',
  'memory.retention_days': 'memory',
  'memory.run_debug_retention_days': 'memory',
  'memory.embedding_model': 'models',
  'curation.enabled': 'background',
  'research_review.enabled': 'background',
  'proactive.enabled': 'background',
  'proactive.sources': 'background',
  'proactive.notify': 'general',
  'proactive.quiet_hours': 'general',
  'proactive.brief': 'background',
  'proactive.watches': 'background',
  'proactive.muted': 'background',
  'proactive.diagnosis_cap': 'background',
  'desktop.keep_awake': 'general',
  'desktop.notifications': 'general',
  'desktop.island': 'general',
  'automation.activity_link': 'background',
  'phone.enabled': 'connections',
  'phone.pairing': 'connections',
  'phone.requests': 'connections',
  'phone.devices': 'connections',
  'access.api_token': 'connections',
  'access.mcp_server_enabled': 'connections',
  'advanced.telemetry': 'memory',
  'advanced.orchestrator_shell': 'abilities',
  'advanced.shell_confirm_policy': 'abilities',
  'advanced.background_job_budget': 'background',
  'advanced.terminal_rules': 'abilities',
  'general.voice_mode': 'general',
  'general.voice_input_locale': 'general',
  'general.voice_silence': 'general',
  'abilities.default_read': 'abilities',
  'abilities.workspace_dir': 'abilities',
  'abilities.sandbox': 'abilities',
  'abilities.lan_discovery': 'abilities',
  'abilities.ssh': 'abilities',
  'abilities.hands': 'abilities',
  'abilities.browser_setup': 'abilities',
  'memory.index_health': 'memory',
  'memory.backup': 'memory',
  'memory.deletion_export': 'memory',
  'connections.github_token': 'connections',
  'about.version': 'about',
  'about.whats_new': 'about',
  'about.activity_link': 'about',
};

/** Sections in nav order (one flat group since 0.1.55). */
export function sectionsByGroup(): { group: SettingsGroupMeta; sections: SettingsSectionMeta[] }[] {
  return [{ group: { id: 'all', labelKey: 'settings.navRegion' }, sections: SETTINGS_SECTIONS }];
}
