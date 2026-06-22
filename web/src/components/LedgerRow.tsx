import { useTranslation } from "react-i18next";

interface LedgerRowProps {
  spawn: { id: number; name: string };
  isMember: boolean;
  onInvite: (id: number) => void;
  onKick: (id: number) => void;
}

export function LedgerRow({ spawn, isMember, onInvite, onKick }: LedgerRowProps) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-white text-xs font-mono">{spawn.name}</span>
      {isMember ? (
        <button
          aria-label={t("ledger.exit")}
          onClick={() => onKick(spawn.id)}
          className="px-3 py-1.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border border-rose-500/40 bg-rose-950/20 text-rose-400 hover:bg-rose-950/40 hover:border-rose-500/60 transition-all shrink-0 flex items-center gap-1"
        >
          {t("ledger.connectedExit")}
        </button>
      ) : (
        <button
          aria-label={t("ledger.pullIn")}
          onClick={() => onInvite(spawn.id)}
          className="px-3 py-1.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border border-[#FF8E24]/40 bg-[#FF8E24]/5 text-[#FF8E24] hover:bg-[#FF8E24]/15 hover:border-[#FF8E24]/60 transition-all shrink-0 flex items-center gap-1"
        >
          {t("ledger.pullIntoChat")}
        </button>
      )}
    </div>
  );
}
