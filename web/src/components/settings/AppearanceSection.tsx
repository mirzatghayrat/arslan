/**
 * AppearanceSection — the "Appearance & Language" settings section.
 *
 * Self-contained card lifted verbatim out of SettingsScreen's `appearance` slot.
 * Per spec B1 this section groups: display name (localStorage-backed, local-only
 * via profileStore), the UI language Select, and the palette/mode controls
 * (existing <AppearanceSettings/>, rendered as-is).
 *
 * The language change handler is supplied by the host (onLanguageChange) so the
 * exact wired behavior — persist the code AND call i18n.changeLanguage — stays
 * with the host and is unchanged. Display name reads/writes the profileStore
 * directly (its own localStorage mechanism); no persistence change here.
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Palette } from 'lucide-react';
import Select from '../Select';
import { AppearanceSettings } from '../AppearanceSettings';
import { LANGUAGE_OPTIONS, normalizeLanguage } from '../../lib/languages';
import { useProfileStore } from '../../stores/profileStore';

export interface AppearanceSectionProps {
  /** Current UI language code (or legacy label). */
  language: string;
  /**
   * Called with the picked language code. The host wires this to persist the
   * code and call i18n.changeLanguage — kept host-side so the switch behavior is
   * unchanged by the extraction.
   */
  onLanguageChange: (code: string) => void;
}

export default function AppearanceSection({ language, onLanguageChange }: AppearanceSectionProps) {
  const { t } = useTranslation();
  const displayName = useProfileStore((s) => s.displayName);
  const setDisplayName = useProfileStore((s) => s.setDisplayName);

  return (
    <div className="bg-surface/60 border border-border rounded-2xl p-6 space-y-6">
      <div className="flex items-center gap-2 pb-4 border-b border-border/50 select-none">
        <Palette className="w-4.5 h-4.5 text-primary" />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">{t('settings.sectionAppearance')}</h3>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Display name — client-only (localStorage); empty = neutral greeting with no name */}
        <div className="space-y-2">
          <label
            htmlFor="settings-display-name"
            className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
          >
            {t('settings.labelDisplayName')}
          </label>
          <input
            id="settings-display-name"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full bg-surface border border-border-strong focus:border-primary focus:ring-1 focus:ring-ring rounded-xl px-4 py-3 text-xs text-foreground placeholder-subtle-foreground focus:outline-none transition-all font-sans"
            placeholder={t('settings.displayNamePlaceholder')}
          />
          <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
            {t('settings.displayNameHint')}
          </p>
        </div>

        {/* Language */}
        <div className="space-y-2">
          <label
            htmlFor="settings-language"
            className="block text-[10.5px] font-mono font-medium text-muted-foreground uppercase tracking-wide"
          >
            {t('settings.labelLanguage')}
          </label>
          <Select
            id="settings-language"
            value={normalizeLanguage(language)}
            onChange={(code) => onLanguageChange(code)}
            options={LANGUAGE_OPTIONS.map((o) => ({ value: o.code, label: o.label }))}
            ariaLabel={t('settings.labelLanguage')}
          />
          <p className="text-[10px] text-subtle-foreground font-sans leading-relaxed">
            {t('settings.language_i18n_note')}
          </p>
        </div>

        {/* Appearance — palette picker + mode toggle */}
        <div className="md:col-span-2">
          <AppearanceSettings />
        </div>
      </div>
    </div>
  );
}
