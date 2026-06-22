import { useTranslation } from "react-i18next";

interface LedgerRowProps {
  spawn: { id: number; name: string };
  isMember: boolean;
  onInvite: (id: number) => void;
  onKick: (id: number) => void;
}

// Invite/kick action for a spawn in the Ledger. Button-only — the row's name,
// avatar and details are rendered by the caller alongside this control.
export function LedgerRow({ spawn, isMember, onInvite, onKick }: LedgerRowProps) {
  const { t } = useTranslation();
  return isMember ? (
    <button
      aria-label={t("ledger.exit")}
      onClick={() => onKick(spawn.id)}
      className="px-3 py-1.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20 hover:border-danger/60 transition-all shrink-0 flex items-center gap-1"
    >
      {t("ledger.connectedExit")}
    </button>
  ) : (
    <button
      aria-label={t("ledger.pullIn")}
      onClick={() => onInvite(spawn.id)}
      className="px-3 py-1.5 rounded-lg text-[10px] font-mono font-bold uppercase tracking-wider border border-primary/40 bg-primary/5 text-primary hover:bg-primary/15 hover:border-primary/60 transition-all shrink-0 flex items-center gap-1"
    >
      {t("ledger.pullIntoChat")}
    </button>
  );
}
