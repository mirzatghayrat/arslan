import { useMemo } from "react";

// Center "living core" for the second-brain sunburst — a pure-CSS Siri-style glow
// orb (no WebGL, no video): cool blue/purple/pink blobs swirling over a dark base
// with a breathing center bloom. Self-contained (its own dark interior) so it looks
// the same/good on both light and dark pages. Freezes under prefers-reduced-motion.

const CSS = `
.brain-orb { position: relative; border-radius: 50%; overflow: hidden; isolation: isolate;
  background: radial-gradient(circle at 50% 42%, #14162e 0%, #070810 78%);
  box-shadow: 0 0 0 1px rgba(180,200,255,0.10), inset 0 0 18px 2px rgba(0,0,0,0.55),
    inset 0 6px 14px -6px rgba(200,220,255,0.30); }
.brain-orb__blob { position: absolute; border-radius: 50%; filter: blur(11px);
  mix-blend-mode: screen; will-change: transform; }
.brain-orb__blob--a { left: -12%; top: -14%; width: 78%; height: 78%;
  background: radial-gradient(circle at 50% 50%, #4f7cff, transparent 68%);
  animation: brain-orb-a 9s ease-in-out infinite; }
.brain-orb__blob--b { right: -14%; bottom: -18%; width: 82%; height: 82%;
  background: radial-gradient(circle at 50% 50%, #9b5cff, transparent 68%);
  animation: brain-orb-b 11s ease-in-out infinite; }
.brain-orb__blob--c { left: -18%; bottom: -6%; width: 70%; height: 70%;
  background: radial-gradient(circle at 50% 50%, #ff5ca8, transparent 70%);
  animation: brain-orb-c 13s ease-in-out infinite; }
.brain-orb__blob--d { right: -6%; top: -10%; width: 60%; height: 60%;
  background: radial-gradient(circle at 50% 50%, #3fd7ff, transparent 72%);
  animation: brain-orb-a 10s ease-in-out infinite reverse; }
.brain-orb__bloom { position: absolute; inset: 30%; border-radius: 50%; z-index: 2; filter: blur(2px);
  background: radial-gradient(circle at 50% 42%, rgba(226,238,255,0.92), rgba(150,180,255,0.25) 52%, transparent 72%);
  animation: brain-orb-breathe 6s ease-in-out infinite; }
@keyframes brain-orb-a { 0%,100%{transform:translate(0,0) scale(1)} 33%{transform:translate(16%,12%) scale(1.18)} 66%{transform:translate(-8%,16%) scale(0.92)} }
@keyframes brain-orb-b { 0%,100%{transform:translate(0,0) scale(1.06)} 50%{transform:translate(-16%,-12%) scale(0.88)} }
@keyframes brain-orb-c { 0%,100%{transform:translate(0,0) scale(0.94)} 50%{transform:translate(14%,-12%) scale(1.22)} }
@keyframes brain-orb-breathe { 0%,100%{transform:scale(1);opacity:0.88} 50%{transform:scale(1.14);opacity:1} }
.brain-orb[data-static="1"] .brain-orb__blob, .brain-orb[data-static="1"] .brain-orb__bloom { animation: none; }
@media (prefers-reduced-motion: reduce) { .brain-orb__blob, .brain-orb__bloom { animation: none !important; } }
`;

export default function BrainOrbCore({ size = 124 }: { size?: number }) {
  const reduced = useMemo(
    () =>
      typeof window !== "undefined" &&
      !!window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  return (
    <div
      className="brain-orb"
      data-static={reduced ? "1" : "0"}
      style={{ width: size, height: size, pointerEvents: "none" }}
    >
      <style>{CSS}</style>
      <div className="brain-orb__blob brain-orb__blob--a" />
      <div className="brain-orb__blob brain-orb__blob--b" />
      <div className="brain-orb__blob brain-orb__blob--c" />
      <div className="brain-orb__blob brain-orb__blob--d" />
      <div className="brain-orb__bloom" />
    </div>
  );
}
