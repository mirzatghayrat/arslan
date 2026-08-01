/**
 * Settings section registry — the single source of truth for the Settings
 * side-nav, and (via `FIELD_HOMES`) the contract that no existing control is
 * lost in the redesign.
 *
 * The flat list of eight tabs became three groups. The problem was never the
 * number of settings — it was that all of them sat at one level of disclosure,
 * so finding one meant scanning all eight. The research behind the mock reached
 * the same sentence about the provider pane: crowding is fixed by DISCLOSURE
 * LEVELS, not by deleting things and not by adding whitespace.
 *
 * The two placeholder sections (`scheduled`, `usage`) are gone. They rendered a
 * "coming soon" card pointing at Diagnostics — a nav entry whose only function
 * was to tell you it does nothing. The pointer survives as a link inside
 * `automation`, beside the settings it actually relates to.
 */

export type SettingsSectionId =
  | 'models' | 'search'                       // Connection
  | 'appearance' | 'memory'                   // Personal
  | 'automation' | 'access' | 'advanced';     // System

export type SettingsGroupId = 'connection' | 'personal' | 'system';

export interface SettingsGroupMeta {
  id: SettingsGroupId;
  labelKey: string;
}

export interface SettingsSectionMeta {
  id: SettingsSectionId;
  group: SettingsGroupId;
  labelKey: string;
  icon: string;          // lucide-react icon name
  /** Optional one-line "what lives here", shown under the nav label. */
  hintKey?: string;
}

export const SETTINGS_GROUPS: SettingsGroupMeta[] = [
  { id: 'connection', labelKey: 'settings.groupConnection' },
  { id: 'personal',   labelKey: 'settings.groupPersonal' },
  { id: 'system',     labelKey: 'settings.groupSystem' },
];

export const SETTINGS_SECTIONS: SettingsSectionMeta[] = [
  { id: 'models',     group: 'connection', labelKey: 'settings.navModels',     icon: 'Cpu' },
  { id: 'search',     group: 'connection', labelKey: 'settings.navSearch',     icon: 'Search' },
  { id: 'appearance', group: 'personal',   labelKey: 'settings.navAppearance', icon: 'Palette' },
  { id: 'memory',     group: 'personal',   labelKey: 'settings.navMemory',     icon: 'Database' },
  // Everything that can spend money lives together, with the honest copy about
  // what the caps do and do not bound. Split across sections is how someone
  // turns on the second one without ever seeing the first one's warning.
  { id: 'automation', group: 'system',     labelKey: 'settings.navAutomation', icon: 'Bot',
    hintKey: 'settings.navAutomationHint' },
  { id: 'access',     group: 'system',     labelKey: 'settings.navAccess',     icon: 'KeyRound' },
  { id: 'advanced',   group: 'system',     labelKey: 'settings.navAdvanced',   icon: 'Sliders' },
];

/**
 * Every control that exists, and the section it lives in. This is the mock's
 * §03 "not one field is lost" table written as data, so a test checks it
 * instead of a person re-reading two screens.
 *
 * Built from a four-angle sweep — by component, by i18n key, by server schema,
 * and by "can this spend money" — because reading components alone misses two
 * whole classes: settings the API exposes with NO UI, and controls rendered
 * from a list rather than as literal JSX.
 *
 * 🔴 `curation.enabled` is the first class, and it is why the sweep was worth
 * doing. It has shipped in `SettingsIn`/`SettingsOut` since the curation round,
 * `server/schemas.py:20` documents it as opt-in because "it spends" — and the
 * app never rendered a control for it. The mock's §03 listed it as a MOVE from
 * Advanced; there was nothing in Advanced to move. It is built here.
 */
export const FIELD_HOMES: Record<string, SettingsSectionId> = {
  // ── models (was `providers`) ──────────────────────────────────────────────
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

  // ── search ────────────────────────────────────────────────────────────────
  'search.tools': 'search',

  // ── appearance ────────────────────────────────────────────────────────────
  'appearance.display_name': 'appearance',
  'appearance.language': 'appearance',
  'appearance.theme': 'appearance',
  'appearance.ocr_languages': 'appearance',

  // ── memory ────────────────────────────────────────────────────────────────
  'memory.distill_on_session_end': 'memory',
  'memory.retention_days': 'memory',
  'memory.run_debug_retention_days': 'memory',
  'memory.embedding_model': 'memory',

  // ── automation (new section; everything that spends lives here) ───────────
  'evolution.auto': 'automation',
  'evolution.max_dispatches': 'automation',
  'curation.enabled': 'automation',
  //: Replaces the two placeholder nav entries.
  'automation.diagnostics_link': 'automation',

  // ── access & security ─────────────────────────────────────────────────────
  'access.api_token': 'access',
  'access.mcp_server_enabled': 'access',

  // ── advanced ──────────────────────────────────────────────────────────────
  'advanced.telemetry': 'advanced',
  'advanced.orchestrator_shell': 'advanced',
  'advanced.shell_confirm_policy': 'advanced',
  'advanced.spawn_mode': 'advanced',
};

/** Sections in nav order, grouped. */
export function sectionsByGroup(): { group: SettingsGroupMeta; sections: SettingsSectionMeta[] }[] {
  return SETTINGS_GROUPS.map((group) => ({
    group,
    sections: SETTINGS_SECTIONS.filter((s) => s.group === group.id),
  }));
}
