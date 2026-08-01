import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Cpu, Search, Palette, KeyRound, Database, Bot, Sliders, Circle,
  type LucideIcon,
} from 'lucide-react';
import {
  SETTINGS_SECTIONS,
  sectionsByGroup,
  type SettingsSectionId,
  type SettingsSectionMeta,
} from './sectionRegistry';

/** Explicit icon map (avoids a heavy `import * as Icons` namespace import). */
const ICONS: Record<string, LucideIcon> = {
  Cpu, Search, Palette, KeyRound, Database, Bot, Sliders,
};

interface SettingsShellProps {
  activeSection: SettingsSectionId;
  onSectionChange: (id: SettingsSectionId) => void;
  /** Section id → rendered card(s). */
  children: Partial<Record<SettingsSectionId, React.ReactNode>>;
}

/**
 * Settings shell: a grouped left side-nav beside the active section.
 *
 * Three changes from the flat eight-tab version, all the same idea — the
 * crowding was never the count, it was that everything sat at one level:
 *
 *  - GROUPS. Connection / Personal / System. Seven entries under three
 *    headings is read by heading; eight peers are read one by one.
 *  - SEARCH, over the registry rather than a second hand-kept index. A search
 *    list maintained apart from the nav goes stale the first time a section is
 *    added, and it goes stale silently.
 *  - NO PLACEHOLDERS. `scheduled` and `usage` rendered a "coming soon" card
 *    that pointed at Diagnostics. A nav entry whose only function is to say it
 *    does nothing is worse than not being there; the pointer now sits inside
 *    Automation, next to the settings it relates to.
 *
 * On narrow viewports the nav collapses to a horizontal scrollable chip row —
 * one responsive <nav> (flex-row → md:flex-col) so there is exactly one button
 * per section and no duplicated DOM.
 */
export default function SettingsShell({
  activeSection,
  onSectionChange,
  children,
}: SettingsShellProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');

  const q = query.trim().toLowerCase();
  const matches = useMemo(() => {
    if (!q) return null;
    // Match the translated label, the hint, and the raw id — the id because a
    // user who knows the app by its URLs or docs types "automation", and the
    // translated label because everyone else does not.
    return new Set(
      SETTINGS_SECTIONS.filter((s) =>
        s.id.includes(q) ||
        t(s.labelKey).toLowerCase().includes(q) ||
        (s.hintKey ? t(s.hintKey).toLowerCase().includes(q) : false),
      ).map((s) => s.id),
    );
  }, [q, t]);

  const groups = sectionsByGroup()
    .map((g) => ({ ...g, sections: g.sections.filter((s) => !matches || matches.has(s.id)) }))
    .filter((g) => g.sections.length > 0);

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
        ].join(' ')}
      >
        <Icon className="w-4 h-4 shrink-0" />
        <span className="flex flex-col leading-tight">
          <span className="text-[12px] font-medium font-sans">{t(s.labelKey)}</span>
          {s.hintKey && (
            <span className="text-[9px] font-sans text-subtle-foreground">{t(s.hintKey)}</span>
          )}
        </span>
      </button>
    );
  };

  return (
    <div className="flex flex-col md:flex-row gap-6">
      <div className="md:w-56 md:shrink-0">
        <label className="sr-only" htmlFor="settings-search">{t('settings.searchPlaceholder')}</label>
        <div className="flex items-center gap-1.5 border border-border rounded-xl px-2.5 py-1.5 mb-3">
          <Search className="w-3.5 h-3.5 text-subtle-foreground shrink-0" aria-hidden />
          <input
            id="settings-search"
            data-testid="settings-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('settings.searchPlaceholder')}
            className="w-full bg-transparent text-[11px] font-sans text-foreground placeholder-subtle-foreground focus:outline-none"
          />
        </div>

        <nav
          aria-label={t('settings.navRegion')}
          className="flex flex-row md:flex-col gap-1 overflow-x-auto md:overflow-visible pb-2 md:pb-0"
        >
          {groups.map(({ group, sections }) => (
            <React.Fragment key={group.id}>
              {/* Group headings are hidden while filtering: with two of seven
                  entries left, three headings are more chrome than content. */}
              {!matches && (
                <div className="hidden md:block px-3 pt-3 pb-1 text-[9px] font-mono uppercase tracking-[0.14em] text-subtle-foreground">
                  {t(group.labelKey)}
                </div>
              )}
              {sections.map(navButton)}
            </React.Fragment>
          ))}
          {matches && groups.length === 0 && (
            <p data-testid="settings-search-empty"
               className="px-3 py-2 text-[11px] font-sans text-subtle-foreground">
              {t('settings.searchNoHits')}
            </p>
          )}
        </nav>
      </div>

      <div data-testid="settings-content" className="flex-1 min-w-0 space-y-8">
        {children[activeSection]}
      </div>
    </div>
  );
}
