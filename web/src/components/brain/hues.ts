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

export function hueVar(key: string): string {
  return `var(--hue-${hueIndex(key)})`;
}
