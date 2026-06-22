import { useId } from "react";
import { avatarInnerSvg, AVATAR_COUNT } from "./avatars/faceLibrary";

// FNV-1a hash → stable per seed string.
function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

interface SpawnAvatarProps {
  // Stable identity — the spawn's name (consistent across sidebar / cards / messages).
  seed: string;
  size?: number;
  className?: string;
}

// A spawn's avatar = one of the curated line faces + a generated colour, both
// derived deterministically from `seed`, so a given spawn always looks the same.
export function SpawnAvatar({ seed, size = 36, className = "" }: SpawnAvatarProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const h = hashStr(seed || "spawn");
  const index = h % AVATAR_COUNT;
  const hue = h % 360;
  const color = `hsl(${hue} 60% 50%)`;
  const fid = `avwob-${uid}`;
  const inner =
    `<defs><filter id="${fid}" x="-25%" y="-25%" width="150%" height="150%">` +
    `<feTurbulence type="fractalNoise" baseFrequency="0.018" numOctaves="2" seed="${(index % 9) + 2}" result="n"/>` +
    `<feDisplacementMap in="SourceGraphic" in2="n" scale="3.2"/></filter></defs>` +
    `<g filter="url(#${fid})">${avatarInnerSvg(index, color)}</g>`;
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.28),
        background: `hsl(${hue} 60% 50% / 0.12)`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        flexShrink: 0,
      }}
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 100 100"
        width={Math.round(size * 0.86)}
        height={Math.round(size * 0.86)}
        dangerouslySetInnerHTML={{ __html: inner }}
      />
    </div>
  );
}
