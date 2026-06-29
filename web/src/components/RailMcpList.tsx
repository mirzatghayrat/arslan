import { useTranslation } from 'react-i18next';
import { Satellite } from 'lucide-react';

export type McpServerInfo = { id: number; name: string; connected?: boolean; exposed?: boolean };

export default function RailMcpList({ servers }: { servers: McpServerInfo[] }) {
  const { t } = useTranslation();
  const live = servers.filter((s) => s.exposed || s.connected);
  return (
    <div className="space-y-1.5">
      <span className="text-[9px] font-mono text-subtle-foreground uppercase tracking-wider font-bold flex items-center gap-1"><Satellite className="w-3 h-3" /> {t('rail.mcp_servers')}</span>
      {live.length === 0 ? (
        <p className="text-[9px] font-mono text-subtle-foreground italic">{t('rail.mcp_none')}</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {live.map((s) => (
            <div key={s.id} className="px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 bg-surface text-info">
              <span className={`w-1.5 h-1.5 rounded-full ${s.connected ? 'bg-success' : 'bg-subtle-foreground'}`} />
              <span>{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
