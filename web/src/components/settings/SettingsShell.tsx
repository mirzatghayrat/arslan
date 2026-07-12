import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Sliders, Search, Palette, KeyRound, Database, Clock, BarChart3, Circle,
  type LucideIcon,
} from 'lucide-react';
import {
  SETTINGS_SECTIONS,
  type SettingsSectionId,
  type SettingsSectionMeta,
} from './sectionRegistry';

/** Explicit icon map (avoids a heavy `import * as Icons` namespace import). */
const ICONS: Record<string, LucideIcon> = {
  Sliders, Search, Palette, KeyRound, Database, Clock, BarChart3,
};

interface SettingsShellProps {
  activeSection: SettingsSectionId;
  onSectionChange: (id: SettingsSectionId) => void;
  /** Section id → rendered card(s). Missing/placeholder ids show a hint card. */
  children: Partial<Record<SettingsSectionId, React.ReactNode>>;
}

/**
 * System Settings shell: a left side-nav (six real sections + two placeholders)
 * beside the active section's content. On narrow viewports (`< md`) the nav
 * collapses to a horizontal, scrollable chip row on top — a single responsive
 * <nav> (flex-row → md:flex-col) so there is exactly one button per section
 * (no duplicated DOM), mirroring the Diagnostics shell's responsive idiom.
 */
export default function SettingsShell({
  activeSection,
  onSectionChange,
  children,
}: SettingsShellProps) {
  const { t } = useTranslation();

  const activeMeta = SETTINGS_SECTIONS.find((s) => s.id === activeSection);
  const activeNode = children[activeSection];
  // Placeholder view when the section is a declared placeholder OR no child was
  // supplied for it (e.g. an endpoint-less section this round).
  const showPlaceholder = Boolean(activeMeta?.placeholder) || activeNode == null;
  const PlaceholderIcon = ICONS[activeMeta?.icon ?? ''] ?? Circle;

  const navButton = (s: SettingsSectionMeta) => {
    const active = s.id === activeSection;
    const Icon = ICONS[s.icon] ?? Circle;
    return (
      <button
        key={s.id}
        type="button"
        data-testid={`settings-nav-${s.id}`}
        aria-current={active ? 'page' : undefined}
        onClick={() => onSectionChange(s.id)}
        className={[
          'flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-left shrink-0',
          'whitespace-nowrap transition-colors select-none',
          active
            ? 'bg-primary/10 text-primary border border-primary/30'
            : 'text-muted-foreground hover:text-foreground hover:bg-surface/60 border border-transparent',
          s.placeholder && !active ? 'opacity-60' : '',
        ].join(' ')}
      >
        <Icon className="w-4 h-4 shrink-0" />
        <span className="flex flex-col leading-tight">
          <span className="text-[12px] font-medium font-sans">{t(s.labelKey)}</span>
          {s.placeholder && (
            <span className="text-[9px] font-mono uppercase tracking-wide text-subtle-foreground">
              {t('settings.navComingSoon')}
            </span>
          )}
        </span>
      </button>
    );
  };

  return (
    <div className="flex flex-col md:flex-row gap-6">
      <nav
        aria-label={t('settings.navRegion')}
        className="flex flex-row md:flex-col gap-1 overflow-x-auto md:overflow-visible md:w-56 md:shrink-0 pb-2 md:pb-0"
      >
        {SETTINGS_SECTIONS.map(navButton)}
      </nav>

      <div data-testid="settings-content" className="flex-1 min-w-0 space-y-8">
        {showPlaceholder ? (
          <div
            data-testid="settings-placeholder"
            className="bg-surface/60 border border-border rounded-2xl p-10 min-h-[240px] flex flex-col items-center justify-center text-center gap-3 select-none"
          >
            <PlaceholderIcon className="w-6 h-6 text-subtle-foreground" />
            <p className="text-xs text-muted-foreground font-sans max-w-sm leading-relaxed">
              {t('settings.placeholderHint')}
            </p>
          </div>
        ) : (
          activeNode
        )}
      </div>
    </div>
  );
}
