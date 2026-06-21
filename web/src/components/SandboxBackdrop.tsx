import { useState } from "react";
import { useThemeStore } from "../stores/themeStore";
import Prism from "./backgrounds/Prism";

// Ambient backdrop for the spawn direct-channel.
// Motion layer = a recorded prism loop when present at /prism-{dark,light}.mp4
// (cheap, battery-friendly), else the live WebGL prism (also the recording
// source). A token-driven frosted-glass layer on top carries the per-palette
// color and keeps chat content readable in both modes. Honours reduced-motion.
const REDUCED =
  typeof window !== "undefined" &&
  !!window.matchMedia &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function SandboxBackdrop() {
  const mode = useThemeStore((s) => s.mode);
  const [videoFailed, setVideoFailed] = useState(false);

  const videoSrc = mode === "light" ? "/prism-light.mp4" : "/prism-dark.mp4";
  const showVideo = !REDUCED && !videoFailed;
  const showLive = !REDUCED && videoFailed;

  // Light mode needs a dimmer motion layer + thicker frost so content stays crisp.
  const motionOpacity = mode === "light" ? "opacity-40" : "opacity-70";
  const frostBg = mode === "light" ? "bg-surface/65" : "bg-surface/45";

  return (
    <div className="absolute inset-0 z-0 overflow-hidden pointer-events-none" aria-hidden="true">
      {showVideo && (
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
      )}
      {showLive && (
        <div className={`absolute inset-0 ${motionOpacity}`}>
          <Prism
            animationType="rotate"
            timeScale={0.4}
            glow={0.6}
            bloom={0.8}
            noise={0.3}
            scale={4}
            suspendWhenOffscreen
          />
        </div>
      )}
      {/* Frosted glass — token-driven, so it tints per palette + mode and keeps content legible. */}
      <div className={`absolute inset-0 backdrop-blur-md ${frostBg}`} />
      <div className="absolute inset-0 bg-primary/[0.02]" />
    </div>
  );
}
