import { useMemo } from "react";

import Strands from "../backgrounds/Strands";

// Center "living core" for the second-brain sunburst — a real reactbits Strands
// WebGL animation (flowing sinusoidal light-strands + glass sphere overlay),
// clipped to a circle so it reads as a breathing orb. The breathing pulse is a
// cheap CSS transform (not a shader uniform) so it costs nothing extra on the
// GPU side. Freezes (no breathing, speed=0) under prefers-reduced-motion.
export default function BrainOrbCore({ size = 124 }: { size?: number }) {
  const reduced = useMemo(
    () =>
      typeof window !== "undefined" &&
      !!window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const box: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: "50%",
    overflow: "hidden",
    position: "relative",
    pointerEvents: "none",
    background: "transparent",
    boxShadow: "0 10px 34px -12px rgba(90,120,255,0.45)",
    animation: reduced ? "none" : "brain-orb-breathe 5.5s ease-in-out infinite",
  };

  return (
    <div data-orb-strands="1" style={box}>
      <style>{"@keyframes brain-orb-breathe{0%,100%{transform:scale(1)}50%{transform:scale(1.045)}}"}</style>
      <Strands
        colors={["#6aa0ff", "#8f7bff", "#ff72c0", "#5fe0ff"]}
        count={7}
        speed={reduced ? 0 : 0.9}
        amplitude={1}
        thickness={2.4}
        glow={1}
        glass
        glassSize={1}
        style={{ width: "100%", height: "100%" }}
      />
    </div>
  );
}
