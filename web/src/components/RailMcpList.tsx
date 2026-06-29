import { useTranslation } from 'react-i18next';
import { Satellite } from 'lucide-react';

// Real /mcp/servers shape (server/services/mcp_service.py::_to_dict): { id, label, status, … }.
// status === 'connected' when the server is live. There is no per-server "exposed" flag.
export type McpServerInfo = { id: number; label: string; status?: string };

export default function RailMcpList({ servers }: { servers: McpServerInfo[] }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1.5">
      <span className="text-[9px] font-mono text-subtle-foreground uppercase tracking-wider font-bold flex items-center gap-1"><Satellite className="w-3 h-3" /> {t('rail.mcp_servers')}</span>
      {servers.length === 0 ? (
        <p className="text-[9px] font-mono text-subtle-foreground italic">{t('rail.mcp_none')}</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {servers.map((s) => (
            <div key={s.id} className="px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 bg-surface text-info">
              <span className={`w-1.5 h-1.5 rounded-full ${s.status === 'connected' ? 'bg-success' : 'bg-subtle-foreground'}`} />
              <span>{s.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
