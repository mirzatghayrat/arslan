import type { StreamUsage } from "../api/client.types";
import { fmtTok, fmtUsd } from "../lib/usageFormat";

/**
 * S3-M3: small muted usage chip in the bubble corner — `1.2k tok · $0.003`.
 * Honesty rules (mirroring the backend):
 *   - estimated tokens carry a ≈ prefix;
 *   - usd == null renders NO dollar figure at all (unknown ≠ free — never $0).
 * Styled to match the existing timestamp/meta small text (mono, tabular-nums).
 */
export default function UsageChip({ usage }: { usage: StreamUsage }) {
  return (
    <div
      data-testid="usage-chip"
      className="mt-1.5 text-[10px] font-mono tabular-nums text-subtle-foreground select-none"
    >
      {usage.estimated ? "≈ " : ""}
      {fmtTok(usage.tokens_total)} tok
      {usage.usd != null ? ` · ${fmtUsd(usage.usd)}` : ""}
    </div>
  );
}
