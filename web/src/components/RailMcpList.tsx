import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Satellite, Stethoscope } from 'lucide-react';
import { api } from '../api/client';

// Real /mcp/servers shape (server/services/mcp_service.py::_to_dict): { id, label, status,
// health_status, last_error, … }. status === 'connected' when the server is live;
// health_status is the PB-4 probe verdict: 'ok' | 'failing' | null = never checked.
export type McpServerInfo = {
  id: number;
  label: string;
  status?: string;
  health_status?: string | null;
  last_error?: string | null;
};

type HealthOverride = { health_status: string; last_error: string | null };

export default function RailMcpList({ servers }: { servers: McpServerInfo[] }) {
  const { t } = useTranslation();
  // Local overrides so a 体检 click refreshes the row without re-fetching the whole list.
  const [overrides, setOverrides] = useState<Record<number, HealthOverride>>({});
  const [checkingId, setCheckingId] = useState<number | null>(null);

  const runCheck = async (id: number) => {
    setCheckingId(id);
    try {
      const r = await api.checkMcpHealth(id);
      setOverrides((o) => ({ ...o, [id]: { health_status: r.health_status, last_error: r.last_error } }));
    } catch {
      // fail-open: probe endpoint unreachable → keep whatever we knew before
    }
    setCheckingId(null);
  };

  return (
    <div className="space-y-1.5">
      <span className="text-[9px] font-mono text-subtle-foreground uppercase tracking-wider font-bold flex items-center gap-1"><Satellite className="w-3 h-3" /> {t('rail.mcp_servers')}</span>
      {servers.length === 0 ? (
        <p className="text-[9px] font-mono text-subtle-foreground italic">{t('rail.mcp_none')}</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {servers.map((s) => {
            const hs = overrides[s.id]?.health_status ?? s.health_status ?? null;
            const err = overrides[s.id]?.last_error ?? s.last_error ?? null;
            const healthDot = hs === 'ok' ? 'bg-success' : hs === 'failing' ? 'bg-danger' : 'bg-subtle-foreground';
            const healthTitle =
              hs === 'ok' ? t('rail.mcp_health_ok')
              : hs === 'failing' ? (err || t('rail.mcp_health_failing'))
              : t('rail.mcp_health_unknown');
            return (
              <div key={s.id} className="px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 bg-surface text-info">
                <span className={`w-1.5 h-1.5 rounded-full ${s.status === 'connected' ? 'bg-success' : 'bg-subtle-foreground'}`} />
                <span>{s.label}</span>
                <span
                  data-testid={`mcp-health-${s.id}`}
                  title={healthTitle}
                  className={`w-1.5 h-1.5 rounded-full ${healthDot}`}
                />
                <button
                  type="button"
                  onClick={() => runCheck(s.id)}
                  disabled={checkingId === s.id}
                  title={t('rail.mcp_health_check')}
                  className="flex items-center gap-0.5 text-[9px] text-subtle-foreground hover:text-info disabled:opacity-50"
                >
                  <Stethoscope className="w-2.5 h-2.5" />
                  {t('rail.mcp_health_check')}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
