/**
 * usageFormat.ts — S3-M3 cost visibility number formatting, shared by the
 * bubble usage chip, the EvalDock conversation cumulative line and the
 * Diagnostics usage card.
 *
 * Honesty invariants mirrored from the backend (server/api/usage.py):
 *   - usd == null means "cost unknown" and must render as NOTHING (never $0);
 *   - $0 is reserved for genuinely free (local) models;
 *   - estimated figures always carry a ≈ prefix at the call site.
 */

/** Trim a fixed-decimal string's trailing zeros ("1.0" → "1", "0.0030" → "0.003"). */
function trimZeros(s: string): string {
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

/** Token count: <1000 raw, then `1.2k`, then `8.7M`. */
export function fmtTok(n: number): string {
  if (n < 1000) return String(n);
  const k = n / 1000;
  if (k < 1000) return `${trimZeros(k.toFixed(1))}k`;
  return `${trimZeros((k / 1000).toFixed(1))}M`;
}

/** USD: "$0" only for a genuinely free call; micro-costs keep 4 decimals
 *  ("$0.003"), anything ≥ 1¢ renders as normal currency ("$1.50"). */
export function fmtUsd(usd: number): string {
  if (usd === 0) return "$0";
  if (usd >= 0.01) return `$${usd.toFixed(2)}`;
  return `$${trimZeros(usd.toFixed(4))}`;
}

/** Duration: "0.8s", "41s", "2m 57s", "1h 3m". */
export function fmtMs(ms: number): string {
  if (ms < 1000) return `${trimZeros((ms / 1000).toFixed(1))}s`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 ? `${m}m ${s % 60}s` : `${m}m`;
  return m % 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 60)}h`;
}
