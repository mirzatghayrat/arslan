import { useTranslation } from 'react-i18next';
import { Monitor } from 'lucide-react';

/**
 * Desktop — how Arslan behaves while its window is closed (0.1.41).
 *
 * Closing the window no longer quits: Arslan stays in the menu bar, scheduled
 * tasks keep running, and ⌘Q or "Quit Arslan" in the menu bar quits. These two
 * switches are ON by default and neither spends anything, which is why they do
 * not live under Automation (whose copy says everything there spends and is off).
 */
export default function DesktopSection({
  keepAwakeEnabled,
  onKeepAwakeChange,
  notificationsEnabled,
  onNotificationsChange,
  islandEnabled = true,
  onIslandChange,
}: {
  keepAwakeEnabled: boolean;
  onKeepAwakeChange?: (v: boolean) => void;
  notificationsEnabled: boolean;
  onNotificationsChange?: (v: boolean) => void;
  islandEnabled?: boolean;
  onIslandChange?: (v: boolean) => void;
}) {
  const { t } = useTranslation();
  const row = (id: string, label: string, desc: string, checked: boolean, onChange?: (v: boolean) => void) => (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h4 className="text-xs font-bold text-foreground font-sans">{t(label)}</h4>
        <p className="text-[11px] text-muted-foreground font-sans mt-0.5 max-w-xl">{t(desc)}</p>
      </div>
      <input id={id} data-testid={id} type="checkbox" checked={checked}
        onChange={(e) => onChange?.(e.target.checked)}
        className="w-4 h-4 mt-1 shrink-0 text-primary bg-background border-border rounded focus:ring-0 select-none cursor-pointer" />
    </div>
  );
  return (
    <div className="bg-surface border border-border rounded-2xl p-6" data-testid="settings-desktop">
      <div className="flex items-center gap-2 mb-1">
        <Monitor className="w-3.5 h-3.5 text-subtle-foreground" aria-hidden />
        <h3 className="text-xs font-semibold font-mono uppercase tracking-widest text-foreground leading-none">
          {t('settings.navDesktop')}
        </h3>
      </div>
      <p className="text-[11px] text-muted-foreground font-sans max-w-2xl mb-5">{t('settings.desktopLede')}</p>
      <div className="space-y-5">
        {row('settings-keep-awake-toggle', 'settings.labelKeepAwake', 'settings.keepAwakeDesc',
          keepAwakeEnabled, onKeepAwakeChange)}
        <div className="h-[1px] bg-border/40" />
        {row('settings-desktop-notifications-toggle', 'settings.labelDesktopNotifications',
          'settings.desktopNotificationsDesc', notificationsEnabled, onNotificationsChange)}
        <div className="h-[1px] bg-border/40" />
        {row('settings-island-toggle', 'settings.labelIsland', 'settings.islandDesc',
          islandEnabled, onIslandChange)}
      </div>
    </div>
  );
}
