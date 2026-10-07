import { useEffect, useState } from "react";

/** The asking card's countdown ring (0.1.55): amber, mono digits, m:ss. */
export function Countdown({ expiresAt, totalMs, size = 40 }: { expiresAt: number; totalMs: number; size?: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const left = Math.max(0, expiresAt - now);
  const r = size / 2 - 3;
  const c = 2 * Math.PI * r;
  const frac = totalMs > 0 ? Math.min(1, left / totalMs) : 0;
  const s = Math.ceil(left / 1000);
  const label = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return (
    <span data-testid="ask-countdown" className="relative inline-flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }} role="timer" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" className="absolute inset-0">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--fill-strong)" strokeWidth={3} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--ask)" strokeWidth={3} strokeLinecap="round"
          strokeDasharray={`${(c * frac).toFixed(1)} ${c.toFixed(1)}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span className="relative font-mono text-[11px] font-semibold tracking-tight text-ask">{label}</span>
    </span>
  );
}
