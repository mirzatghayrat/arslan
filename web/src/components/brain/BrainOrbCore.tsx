import { useMemo } from "react";

// Center "living core" for the second-brain sunburst — a pure-CSS Siri-style glow
// orb (no WebGL, no video): cool blue/purple/pink blobs swirling over a dark base
// with a breathing center bloom. Self-contained (its own dark interior) so it looks
// the same/good on both light and dark pages. Freezes under prefers-reduced-motion.

const CSS = `
.brain-orb { position: relative; border-radius: 50%; overflow: hidden; isolation: isolate;
  background: radial-gradient(circle at 50% 42%, #23264e 0%, #0c0d1f 84%);
  box-shadow: 0 0 0 1px rgba(190,205,255,0.16), inset 0 8px 16px -8px rgba(220,232,255,0.40); }
/* interior color fields — light blur only, so colors stay crisp (not frosted) */
.brain-orb__blob { position: absolute; border-radius: 50%; filter: blur(4px);
  mix-blend-mode: screen; will-change: transform; }
.brain-orb__blob--a { left: -10%; top: -12%; width: 74%; height: 74%;
  background: radial-gradient(circle at 50% 50%, #4f7cff, transparent 66%);
  animation: brain-orb-a 9s ease-in-out infinite; }
.brain-orb__blob--b { right: -12%; bottom: -16%; width: 80%; height: 80%;
  background: radial-gradient(circle at 50% 50%, #a15cff, transparent 66%);
  animation: brain-orb-b 11s ease-in-out infinite; }
.brain-orb__blob--c { left: -14%; bottom: -4%; width: 66%; height: 66%;
  background: radial-gradient(circle at 50% 50%, #ff5ca8, transparent 68%);
  animation: brain-orb-c 13s ease-in-out infinite; }
.brain-orb__blob--d { right: -4%; top: -8%; width: 56%; height: 56%;
  background: radial-gradient(circle at 50% 50%, #3fd7ff, transparent 70%);
  animation: brain-orb-a 10s ease-in-out infinite reverse; }
/* crisp colorful gradient rim (Siri edge), slowly rotating */
.brain-orb__rim { position: absolute; inset: 0; border-radius: 50%; z-index: 2; opacity: 1;
  background: conic-gradient(from 0deg, #5b8cff, #b06bff, #ff6bb0, #ffc46b, #4fe0ff, #5b8cff);
  filter: saturate(1.3) brightness(1.12);
  -webkit-mask: radial-gradient(circle, transparent 58%, #000 70%, #000 92%, transparent 99%);
  mask: radial-gradient(circle, transparent 58%, #000 70%, #000 92%, transparent 99%);
  animation: brain-orb-spin 16s linear infinite; }
/* sharp glossy specular highlight */
.brain-orb__bloom { position: absolute; left: 28%; top: 22%; width: 30%; height: 26%; border-radius: 50%; z-index: 3;
  background: radial-gradient(circle at 50% 50%, rgba(255,255,255,0.95), rgba(255,255,255,0.18) 46%, transparent 68%);
  filter: blur(0.5px); animation: brain-orb-breathe 6s ease-in-out infinite; }
@keyframes brain-orb-a { 0%,100%{transform:translate(0,0) scale(1)} 33%{transform:translate(14%,10%) scale(1.14)} 66%{transform:translate(-8%,14%) scale(0.94)} }
@keyframes brain-orb-b { 0%,100%{transform:translate(0,0) scale(1.05)} 50%{transform:translate(-14%,-10%) scale(0.9)} }
@keyframes brain-orb-c { 0%,100%{transform:translate(0,0) scale(0.95)} 50%{transform:translate(12%,-10%) scale(1.18)} }
@keyframes brain-orb-breathe { 0%,100%{transform:scale(1);opacity:0.9} 50%{transform:scale(1.1);opacity:1} }
@keyframes brain-orb-spin { to { transform: rotate(360deg); } }
.brain-orb[data-static="1"] .brain-orb__blob, .brain-orb[data-static="1"] .brain-orb__bloom, .brain-orb[data-static="1"] .brain-orb__rim { animation: none; }
@media (prefers-reduced-motion: reduce) { .brain-orb__blob, .brain-orb__bloom, .brain-orb__rim { animation: none !important; } }
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
      <div className="brain-orb__rim" />
      <div className="brain-orb__bloom" />
    </div>
  );
}
