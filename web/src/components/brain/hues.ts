/** Map a stable string key (a category / domain / "ft:<fileType>") to one of the
 * ten neutral second-brain hue tokens (--hue-1..--hue-10). FNV-1a keeps the same
 * key on the same slot across renders; the tokens themselves adapt to light/dark
 * via CSS (see theme/tokens.css), so callers never hardcode hex. */
export function hueIndex(key: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return (h % 10) + 1;
}

/** Fixed hues for the three Second-Brain content types so the sunburst wedges and
 * the panel cards share one color per type (material=blue, learning=teal,
 * profile=purple). These are the ONLY keys that bypass the hash. */
const TYPE_HUE: Record<string, string> = {
  material: "var(--hue-6)",
  learning: "var(--hue-5)",
  profile: "var(--hue-8)",
};

export function hueVar(key: string): string {
  if (key in TYPE_HUE) return TYPE_HUE[key];
  return `var(--hue-${hueIndex(key)})`;
}
