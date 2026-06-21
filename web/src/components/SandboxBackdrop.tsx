import { useState } from "react";
import { useThemeStore } from "../stores/themeStore";
import Prism from "./backgrounds/Prism";

// Ambient prism halo behind the spawn welcome card (empty state only).
// Sits behind the card, bleeds slightly past it, and is radial-masked so it
// fades to nothing at the edges — a soft "misty" glow with no hard border.
// Motion = a recorded loop at /prism-{dark,light}.mp4 when present (cheap,
// battery), else the live WebGL prism (also the recording source). The card on
// top supplies the frosted glass + per-palette tint; honours reduced-motion.
const REDUCED =
  typeof window !== "undefined" &&
  !!window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const FEATHER = "radial-gradient(ellipse 75% 75% at 50% 50%, #000 32%, transparent 72%)";

export function SandboxBackdrop() {
  const mode = useThemeStore((s) => s.mode);
  const [videoFailed, setVideoFailed] = useState(false);

  if (REDUCED) return null;

  const videoSrc = mode === "light" ? "/prism-light.mp4" : "/prism-dark.mp4";
  const showVideo = !videoFailed;
  // No frosted layer — the prism shows directly. Light needs near-full opacity
  // to read on a white panel; dark a touch less so it doesn't overpower.
  const motionOpacity = mode === "light" ? "opacity-90" : "opacity-80";

  return (
    <div
      className="absolute -inset-6 z-0 overflow-hidden pointer-events-none rounded-[2rem]"
      aria-hidden="true"
      style={{ WebkitMaskImage: FEATHER, maskImage: FEATHER }}
    >
      {showVideo ? (
        <video
          key={videoSrc}
          src={videoSrc}
          className={`absolute inset-0 w-full h-full object-cover ${motionOpacity}`}
          autoPlay
          loop
          muted
          playsInline
          onError={() => setVideoFailed(true)}
        />
      ) : (
        <div className={`absolute inset-0 ${motionOpacity}`}>
          <Prism
            animationType="rotate"
            timeScale={0.4}
            glow={0.95}
            bloom={1}
            noise={0.3}
            scale={3.2}
            suspendWhenOffscreen
          />
        </div>
      )}
      {/* faint palette wash so the halo leans toward the active accent */}
      <div className="absolute inset-0 bg-primary/[0.05]" />
    </div>
  );
}
