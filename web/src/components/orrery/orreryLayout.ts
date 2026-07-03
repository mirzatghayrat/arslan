export type OrreryCat = "hub" | "spawn" | "source" | "pref";

export interface OrreryNodeIn {
  id: string;
  cat: OrreryCat;
  label: string;
  meta?: string;
  imp?: number; // 0..1 importance (size), default 0.6
}
export interface OrreryEdgeIn { a: string; b: string; }

export interface LaidNode extends OrreryNodeIn {
  angle: number; // radians
  rf: number;    // radius factor 0..1 of R
  z: number;     // depth 0(far)..1(near)
  size: number;
  imp: number;
}

export interface CategoryDef {
  key: OrreryCat;
  label: string;
  angDeg: number;        // sector center in degrees
  rf: [number, number];  // radius band [inner, outer]
}

// 3 real categories (collections deferred — no backend model yet). Hub is central.
export const CATEGORIES: CategoryDef[] = [
  { key: "spawn",  label: "Spawns",      angDeg: -90, rf: [0.30, 0.45] },
  { key: "pref",   label: "Preferences", angDeg: 180, rf: [0.28, 0.43] },
  { key: "source", label: "Sources",     angDeg:  90, rf: [0.62, 0.86] },
];
const BAND_DEG = 46; // angular half-band per sector (deterministic jitter range)

// deterministic 0..1 from a string id — replaces Math.random for stable, testable layout
export function hash01(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  h ^= h << 13; h >>>= 0;
  h ^= h >> 17;
  h ^= h << 5; h >>>= 0;
  return (h >>> 0) / 4294967296;
}

export function layout(nodes: OrreryNodeIn[]): LaidNode[] {
  const byKey = new Map(CATEGORIES.map((c) => [c.key, c]));
  return nodes.map((n) => {
    if (n.cat === "hub") {
      return { ...n, angle: 0, rf: 0, z: 1, size: 16, imp: n.imp ?? 1 };
    }
    const c = byKey.get(n.cat);
    const j1 = hash01(n.id + "a");
    const j2 = hash01(n.id + "b");
    const angle = (c ? c.angDeg : 0) * Math.PI / 180 + (j1 - 0.5) * BAND_DEG * Math.PI / 180;
    const rf = c ? c.rf[0] + j2 * (c.rf[1] - c.rf[0]) : 0.5;
    const z = Math.max(0.12, Math.min(1, 1 - rf * 0.92 + (hash01(n.id + "z") - 0.5) * 0.14));
    const size = n.cat === "spawn" ? 7.5 : n.cat === "source" ? 4.5 : 5;
    return { ...n, angle, rf, z, size, imp: n.imp ?? 0.6 };
  });
}

// screen position from a laid node given center + radius
export function toXY(n: LaidNode, cx: number, cy: number, R: number) {
  return { x: cx + Math.cos(n.angle) * R * n.rf, y: cy + Math.sin(n.angle) * R * n.rf };
}
