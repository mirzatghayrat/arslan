import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { request } from '../../api/client';

type Grant = { id: number; conversation_id: string; title: string };

/**
 * S4a: the conversations whose commands may run outside the sandbox, background tasks' too — the
 * card's "In this conversation", which is stored and outlives a restart. A standing permission
 * nobody can see is one nobody can take back, so each is listed here with a way to take it back.
 */
export default function SandboxGrantsPanel() {
  const { t } = useTranslation();
  const [grants, setGrants] = useState<Grant[] | null>(null);

  useEffect(() => {
    let alive = true;
    request<Grant[]>('/permissions/grants?kind=outside')
      .then((g) => { if (alive) setGrants(Array.isArray(g) ? g : []); })
      .catch(() => { if (alive) setGrants([]); });
    return () => { alive = false; };
  }, []);

  const takeBack = async (id: number) => {
    await request(`/permissions/grants/${id}`, { method: 'DELETE' });
    setGrants((g) => (g ?? []).filter((x) => x.id !== id));
  };

  if (grants == null) return null;
  return (
    <div className="pl-4 border-l-2 border-primary/20 space-y-1.5" data-testid="sandbox-grants">
      <h4 className="text-[13px] font-medium text-foreground">{t('settings.sandboxGrantsTitle')}</h4>
      {grants.length === 0 ? (
        <p className="text-[11px] text-muted-foreground font-sans">{t('settings.sandboxGrantsEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {grants.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-3 text-[12px]">
              <span className="text-foreground truncate">{g.title || t('settings.sandboxGrantsUntitled')}</span>
              <button type="button" data-testid={`sandbox-grant-take-back-${g.id}`} onClick={() => void takeBack(g.id)}
                className="shrink-0 rounded-md border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
                {t('settings.sandboxGrantsTakeBack')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
