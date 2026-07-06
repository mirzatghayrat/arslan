import { useMemo, useState } from "react";
import { useThemeStore } from "../../stores/themeStore";
import Orb from "../backgrounds/Orb";

// Center "living core" for the second-brain sunburst. Mirrors SandboxBackdrop:
// a recorded loop at /orb-{dark,light}.mp4 when present (cheap, battery), else the
// live WebGL Orb (also the recording source). Honours reduced-motion (static core).
const MASK = "radial-gradient(circle at 50% 50%, #000 62%, transparent 78%)";

export default function BrainOrbCore({ size = 124 }: { size?: number }) {
  const mode = useThemeStore((s) => s.mode);
  const [videoFailed, setVideoFailed] = useState(false);
  // useMemo (not module-level) so tests can control window.matchMedia per-test before render.
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
    WebkitMaskImage: MASK,
    maskImage: MASK,
    pointerEvents: "none",
  };

  if (reduced) {
    return (
      <div
        data-static-core="1"
        style={{
          ...box,
          background:
            "radial-gradient(circle at 50% 45%, color-mix(in srgb, var(--hub) 55%, transparent), transparent 70%)",
        }}
      />
    );
  }

  const videoSrc = mode === "light" ? "/orb-light.mp4" : "/orb-dark.mp4";
  if (!videoFailed) {
    return (
      <div style={box}>
        <video
          key={videoSrc}
          src={videoSrc}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
          autoPlay
          loop
          muted
          playsInline
          onError={() => setVideoFailed(true)}
        />
      </div>
    );
  }
  return (
    <div style={box}>
      <Orb hue={230} rotateOnHover={false} hoverIntensity={0.15} />
    </div>
  );
}
