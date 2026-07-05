import { useEffect, useRef, useState } from "react";
import {
  layout,
  CATEGORIES,
  type OrreryNodeIn,
  type OrreryEdgeIn,
  type LaidNode,
  type OrreryCat,
} from "./orreryLayout";

interface Props {
  nodes: OrreryNodeIn[]; // includes one { id:"hub", cat:"hub", label:"YOU" }
  edges: OrreryEdgeIn[];
  onSelect?: (node: LaidNode | null) => void; // click a node -> parent opens detail panel
  className?: string;
}

// ---- math helpers (ported from reference) ----
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const clamp = (v: number, a: number, b: number) => (v < a ? a : v > b ? b : v);
const smooth = (t: number) => {
  t = clamp(t, 0, 1);
  return t * t * (3 - 2 * t);
};
const hex = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

// resolve a theme CSS var with fallback
function cssVar(name: string, fallback: string): string {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch {
    return fallback;
  }
}

// internal per-node runtime state layered over the laid node
interface RNode extends LaidNode {
  bx: number;
  by: number; // base screen position (recomputed on resize)
  sx: number;
  sy: number; // parallax screen position (per frame)
  appear: number;
  pulse: number;
  cur: number;
  phase: number;
  deg: number;
}
interface RLink {
  a: RNode;
  b: RNode;
}
interface Particle {
  l: RLink;
  t: number;
  sp: number;
  boost: boolean;
}

// category color mapping resolved from theme (falls back to reference hues)
function catColorMap(): Record<OrreryCat, string> {
  return {
    hub: cssVar("--hub", "#FFC773"),
    spawn: cssVar("--primary", "#F3A64A"),
    collection: cssVar("--success", "#7BD88F"),
    source: cssVar("--info", "#46C2B2"),
    pref: cssVar("--danger", "#EC7A9C"),
  };
}

export default function KnowledgeOrrery({ nodes, edges, onSelect, className }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // tag overlay state (React div for crisp text)
  const [tag, setTag] = useState<{
    x: number;
    y: number;
    label: string;
    type: string;
    meta: string;
    color: string;
  } | null>(null);
  const [hidden, setHidden] = useState<Set<OrreryCat>>(new Set());
  const [search, setSearch] = useState("");

  // keep latest interactive state readable from the rAF loop without re-subscribing
  const hiddenRef = useRef(hidden);
  hiddenRef.current = hidden;
  const searchRef = useRef(search);
  searchRef.current = search;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom returns null — mount without throwing

    const RM =
      typeof matchMedia === "function" &&
      matchMedia("(prefers-reduced-motion:reduce)").matches;

    const COLORS = catColorMap();
    const catColor = (n: RNode) => COLORS[n.cat] ?? "#ffffff";

    // ---- build runtime nodes from layout() ----
    const laid = layout(nodes);
    const rnodes: RNode[] = laid.map((n) => ({
      ...n,
      bx: 0,
      by: 0,
      sx: 0,
      sy: 0,
      appear: 0,
      pulse: 0,
      cur: 0,
      phase: (n.id.length * 1.37) % 6.28,
      deg: 0,
    }));
    const byId = new Map(rnodes.map((n) => [n.id, n]));
    const hub = rnodes.find((n) => n.cat === "hub") ?? rnodes[0];

    // ---- build links ----
    const rlinks: RLink[] = [];
    for (const e of edges) {
      const a = byId.get(e.a);
      const b = byId.get(e.b);
      if (!a || !b) continue;
      rlinks.push({ a, b });
      a.deg++;
      b.deg++;
    }

    // ---- geometry ----
    let W = 0,
      H = 0,
      DPR = 1,
      CX = 0,
      CY = 0,
      R = 0;

    // ---- offscreen nebula (built once per resize) ----
    const neb = document.createElement("canvas");
    const nbx = neb.getContext("2d");
    function buildNebula() {
      if (!nbx) return;
      neb.width = W;
      neb.height = H;
      nbx.clearRect(0, 0, W, H);
      nbx.fillStyle = "#080A0D";
      nbx.fillRect(0, 0, W, H);
      const blobs: [string, number, number, number, number][] = [
        ["#3A2A12", CX, CY * 0.9, R * 1.5, 0.5],
        ["#241A44", CX - R * 0.6, CY - R * 0.5, R * 1.1, 0.32],
        ["#0E3A38", CX + R * 0.7, CY + R * 0.55, R * 1.1, 0.3],
        ["#3A1626", CX - R * 0.55, CY + R * 0.6, R * 0.8, 0.24],
        ["#2A2038", CX + R * 0.5, CY - R * 0.6, R * 0.7, 0.22],
      ];
      nbx.filter = "blur(70px)";
      for (const [c, x, y, r, a] of blobs) {
        const g = nbx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, hex(c, a));
        g.addColorStop(1, hex(c, 0));
        nbx.fillStyle = g;
        nbx.fillRect(0, 0, W, H);
      }
      nbx.filter = "none";
      for (let i = 0; i < 220; i++) {
        const x = Math.random() * W,
          y = Math.random() * H,
          r = Math.random() * 1.1 + 0.15;
        nbx.fillStyle = hex("#9FB0C6", Math.random() * 0.5 + 0.08);
        nbx.beginPath();
        nbx.arc(x, y, r, 0, 6.28);
        nbx.fill();
      }
    }

    function resize() {
      DPR = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas!.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      canvas!.width = W * DPR;
      canvas!.height = H * DPR;
      ctx!.setTransform(DPR, 0, 0, DPR, 0, 0);
      CX = W / 2;
      CY = H / 2;
      R = (Math.min(W, H) / 2) * 0.92;
      buildNebula();
      for (const n of rnodes) {
        n.bx = CX + Math.cos(n.angle) * R * n.rf;
        n.by = CY + Math.sin(n.angle) * R * n.rf;
      }
    }

    // ---- particles ----
    const parts: Particle[] = [];
    const emit = (l: RLink, boost = false) =>
      parts.push({ l, t: 0, sp: 0.0035 + Math.random() * 0.004, boost });

    const bez = (l: RLink, t: number) => {
      const a = l.a,
        b = l.b,
        mx = (a.sx + b.sx) / 2,
        my = (a.sy + b.sy) / 2,
        dx = b.sx - a.sx,
        dy = b.sy - a.sy,
        d = Math.hypot(dx, dy) || 1,
        bow = d * 0.17,
        cx = mx - (dy / d) * bow,
        cy = my + (dx / d) * bow,
        u = 1 - t;
      return {
        x: u * u * a.sx + 2 * u * t * cx + t * t * b.sx,
        y: u * u * a.sy + 2 * u * t * cy + t * t * b.sy,
        cx,
        cy,
      };
    };

    // ---- interaction state ----
    let hover: RNode | null = null;
    let sel: RNode | null = null;
    let rawmx = -1,
      rawmy = -1;
    let camx = 0,
      camy = 0,
      tgx = 0,
      tgy = 0,
      introT = 0,
      dimG = 0;

    const isHidden = (n: RNode) => hiddenRef.current.has(n.cat);
    const vis = (n: RNode) => n.cat === "hub" || !isHidden(n);

    const onMove = (e: MouseEvent) => {
      const r = canvas!.getBoundingClientRect();
      rawmx = e.clientX - r.left;
      rawmy = e.clientY - r.top;
      tgx = (rawmx / W - 0.5) * 2;
      tgy = (rawmy / H - 0.5) * 2;
    };
    const onLeave = () => {
      tgx = 0;
      tgy = 0;
      hover = null;
      rawmx = -1;
      rawmy = -1;
      setTag(null);
    };
    const onClick = () => {
      if (hover) {
        sel = hover;
        sel.pulse = 1.2;
        onSelectRef.current?.(hover as LaidNode);
      } else {
        sel = null;
        onSelectRef.current?.(null);
      }
    };
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    canvas.addEventListener("click", onClick);

    // ---- resize observer ----
    const ro = new ResizeObserver(() => resize());
    ro.observe(wrap);

    const CATBYKEY = new Map(CATEGORIES.map((c) => [c.key, c]));
    const catLabel = (cat: OrreryCat) =>
      cat === "hub" ? "You" : CATBYKEY.get(cat)?.label ?? cat;

    let raf = 0;
    const t0 = performance.now();

    function frame(now: number) {
      const c = ctx!;
      const t = (now - t0) / 1000;
      c.setTransform(DPR, 0, 0, DPR, 0, 0);
      c.clearRect(0, 0, W, H);
      introT = RM ? 1 : Math.min(1, introT + 0.012);

      // eased camera parallax
      if (!RM) {
        camx = lerp(camx, tgx * 20, 0.06);
        camy = lerp(camy, tgy * 20, 0.06);
      } else {
        camx = 0;
        camy = 0;
      }

      const focus = hover || sel;
      dimG = lerp(dimG, focus ? 1 : 0, 0.12);

      // screen positions with depth parallax
      for (const n of rnodes) {
        const pax = lerp(3, 24, n.z);
        n.sx = n.bx + (camx * pax) / 12;
        n.sy = n.by + (camy * pax) / 12;
      }

      // hover hit-test
      if (rawmx >= 0) {
        let best: RNode | null = null,
          bd = 1e9;
        for (const n of rnodes) {
          if (n.cat === "hub" || !vis(n) || n.appear < 0.5) continue;
          const d = Math.hypot(rawmx - n.sx, rawmy - n.sy);
          if (d < Math.max(15, n.size * 2.3) && d < bd) {
            bd = d;
            best = n;
          }
        }
        if (best !== hover) {
          hover = best;
          canvas!.style.cursor = best ? "pointer" : "default";
        }
      }

      // 1) nebula (far plane)
      const ns = 1.06;
      c.save();
      c.translate(CX + camx * 0.35, CY + camy * 0.35);
      c.scale(ns, ns);
      c.translate(-CX, -CY);
      c.globalAlpha = lerp(0, 1, smooth(introT * 1.3));
      c.drawImage(neb, 0, 0, W, H);
      c.globalAlpha = 1;
      c.restore();

      // 2) structure plane: rings + rim labels
      c.save();
      c.translate(camx * 0.5, camy * 0.5);
      const rings = [0.3, ...CATEGORIES.map((cd) => cd.rf[1])];
      for (const rf of rings) {
        c.strokeStyle = hex("#FFFFFF", 0.04 * introT);
        c.lineWidth = 1;
        c.beginPath();
        c.arc(CX, CY, R * rf, 0, 6.283);
        c.stroke();
      }
      c.font = "600 11px ui-monospace, Menlo, monospace";
      for (const cd of CATEGORIES) {
        const a = (cd.angDeg * Math.PI) / 180,
          rr = R * 0.955;
        c.save();
        c.translate(CX + Math.cos(a) * rr, CY + Math.sin(a) * rr);
        let rot = a;
        if (rot > Math.PI / 2 || rot < -Math.PI / 2) rot += Math.PI;
        c.rotate(rot);
        c.textAlign = "center";
        c.fillStyle = hex(COLORS[cd.key], 0.5 * introT);
        if ("letterSpacing" in c) (c as unknown as { letterSpacing: string }).letterSpacing = "3px";
        c.fillText(cd.label.toUpperCase(), 0, 0);
        c.restore();
      }
      c.restore();

      const near = (n: RNode) =>
        !!focus &&
        (n === focus ||
          rlinks.some(
            (l) => (l.a === focus && l.b === n) || (l.b === focus && l.a === n),
          ));

      // 3) edges
      for (const l of rlinks) {
        if (!vis(l.a) || !vis(l.b) || l.a.appear < 0.05 || l.b.appear < 0.05) continue;
        const touch = !!focus && (l.a === focus || l.b === focus);
        const al = (touch ? 0.55 : lerp(0.14, 0.03, dimG)) * Math.min(l.a.appear, l.b.appear);
        const g = c.createLinearGradient(l.a.sx, l.a.sy, l.b.sx, l.b.sy);
        g.addColorStop(0, hex(catColor(l.a), al));
        g.addColorStop(1, hex(catColor(l.b), al));
        c.strokeStyle = g;
        c.lineWidth = touch ? 1.6 : 1;
        const b = bez(l, 0.5);
        c.beginPath();
        c.moveTo(l.a.sx, l.a.sy);
        c.quadraticCurveTo(b.cx, b.cy, l.b.sx, l.b.sy);
        c.stroke();
      }

      // 4) particles (skip when reduced motion)
      c.globalCompositeOperation = "lighter";
      if (!RM && rlinks.length) {
        for (let i = parts.length - 1; i >= 0; i--) {
          const p = parts[i];
          p.t += p.sp;
          if (p.t >= 1 || !vis(p.l.a) || !vis(p.l.b)) {
            parts.splice(i, 1);
            if (parts.length < 14)
              emit(rlinks[(Math.random() * rlinks.length) | 0]);
            continue;
          }
          const pt = bez(p.l, p.t),
            col = catColor(p.l.b),
            rr = p.boost ? 3.2 : 1.9;
          const g = c.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, rr * 3.2);
          g.addColorStop(0, hex(col, 0.95));
          g.addColorStop(1, hex(col, 0));
          c.fillStyle = g;
          c.beginPath();
          c.arc(pt.x, pt.y, rr * 3.2, 0, 6.283);
          c.fill();
        }
        // keep the field seeded
        if (parts.length < 14) emit(rlinks[(Math.random() * rlinks.length) | 0]);
      }

      const searchQ = searchRef.current.trim().toLowerCase();

      // 5) node glows — depth sorted (far first)
      const order = rnodes.filter((n) => n.cat !== "hub").sort((a, b) => a.z - b.z);
      for (const n of order) {
        if (!vis(n)) continue;
        if (!RM) {
          const start = n.rf * 0.55;
          n.appear = smooth((introT - start) / 0.5);
        } else n.appear = 1;
        if (n.appear <= 0) continue;
        if (n.pulse > 0) n.pulse = Math.max(0, n.pulse - 0.018);
        const hit = !!searchQ && n.label.toLowerCase().includes(searchQ);
        const tgt = hover === n || sel === n ? 1 : 0;
        n.cur = lerp(n.cur, tgt, 0.16);
        let d = lerp(1, near(n) ? 1 : 0.16, dimG);
        if (searchQ) d *= hit ? 1 : 0.12;
        const tw = RM ? 1 : 1 + 0.1 * Math.sin(t * 1.2 + n.phase);
        const depth = lerp(0.55, 1.15, n.z);
        const base = n.size * (0.5 + n.imp * 0.6) * depth * (1 + n.cur * 0.6) * (1 + n.pulse) * n.appear;
        const gr = base * 3.6 * (hit ? 1.5 : 1),
          core = lerp(0.35, 0.62, n.z);
        const g = c.createRadialGradient(n.sx, n.sy, 0, n.sx, n.sy, gr);
        g.addColorStop(0, hex(catColor(n), (0.5 + n.cur * 0.3) * d * tw * lerp(0.6, 1, n.z)));
        g.addColorStop(core, hex(catColor(n), 0.14 * d * tw));
        g.addColorStop(1, hex(catColor(n), 0));
        c.fillStyle = g;
        c.beginPath();
        c.arc(n.sx, n.sy, gr, 0, 6.283);
        c.fill();
      }

      // 6) node cores + spawn labels
      c.globalCompositeOperation = "source-over";
      for (const n of order) {
        if (!vis(n) || n.appear <= 0) continue;
        const hit = !!searchQ && n.label.toLowerCase().includes(searchQ);
        let d = lerp(1, near(n) ? 1 : 0.2, dimG);
        if (searchQ) d *= hit ? 1 : 0.14;
        const depth = lerp(0.55, 1.15, n.z),
          rr = n.size * 0.4 * (0.6 + n.imp * 0.55) * depth * (1 + n.cur * 0.5) * (1 + n.pulse * 0.8) * n.appear;
        c.fillStyle = hex("#080A0D", d * Math.min(1, n.z + 0.3));
        c.beginPath();
        c.arc(n.sx, n.sy, rr + 1.7, 0, 6.283);
        c.fill();
        c.fillStyle = hex(catColor(n), 0.95 * d);
        c.beginPath();
        c.arc(n.sx, n.sy, rr, 0, 6.283);
        c.fill();
        if (n.cat === "spawn") {
          c.strokeStyle = hex(catColor(n), 0.45 * d);
          c.lineWidth = 1;
          c.beginPath();
          c.arc(n.sx, n.sy, rr + 4.5, 0, 6.283);
          c.stroke();
          c.fillStyle = hex("#EEF1F5", (near(n) || dimG < 0.3 ? 0.85 : 0.28) * d);
          c.font = "500 11px system-ui, -apple-system, sans-serif";
          c.textAlign = "center";
          c.fillText(n.label, n.sx, n.sy + rr + 17);
        }
      }

      // 7) hub — the light source
      hub.appear = RM ? 1 : Math.min(1, hub.appear + 0.02);
      const hx = CX + camx * 2,
        hy = CY + camy * 2,
        pl = RM ? 1 : 1 + 0.05 * Math.sin(t * 1.5);
      c.globalCompositeOperation = "lighter";
      for (const [r, a] of [
        [95, 0.16],
        [60, 0.3],
        [30, 0.5],
      ] as const) {
        const g = c.createRadialGradient(hx, hy, 0, hx, hy, r * pl);
        g.addColorStop(0, hex("#FFD9A0", a * hub.appear));
        g.addColorStop(1, hex("#F5A93F", 0));
        c.fillStyle = g;
        c.beginPath();
        c.arc(hx, hy, r * pl, 0, 6.283);
        c.fill();
      }
      c.globalCompositeOperation = "source-over";
      for (let i = 0; i < 3; i++) {
        c.strokeStyle = hex("#FFC773", (0.2 - i * 0.05) * hub.appear);
        c.lineWidth = 1;
        c.beginPath();
        c.arc(hx, hy, (16 + i * 9) * pl, 0, 6.283);
        c.stroke();
      }
      c.fillStyle = hex("#FFEBCB", hub.appear);
      c.beginPath();
      c.arc(hx, hy, 7.5 * pl, 0, 6.283);
      c.fill();
      c.fillStyle = hex("#0A0C10", 0.92 * hub.appear);
      c.font = "600 9.5px ui-monospace, Menlo, monospace";
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(hub.label || "YOU", hx, hy + 0.5);
      c.textBaseline = "alphabetic";

      // tag overlay (React div)
      if (hover) {
        setTag({
          x: Math.min(rawmx + 18, W - 258),
          y: rawmy + 16,
          label: hover.label,
          type: catLabel(hover.cat),
          meta: (hover.meta ?? "") + (hover.deg ? ` · ${hover.deg} links` : ""),
          color: catColor(hover),
        });
      } else {
        setTag(null);
      }

      raf = requestAnimationFrame(frame);
    }

    resize();
    // seed a few particles
    if (!RM) for (let i = 0; i < 8 && rlinks.length; i++) emit(rlinks[(Math.random() * rlinks.length) | 0]);
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mouseleave", onLeave);
      canvas.removeEventListener("click", onClick);
    };
  }, [nodes, edges]);

  // counts per category for legend chips
  const counts = new Map<OrreryCat, number>();
  for (const n of nodes) if (n.cat !== "hub") counts.set(n.cat, (counts.get(n.cat) ?? 0) + 1);
  const COLORS = catColorMap();

  const toggleCat = (k: OrreryCat) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  return (
    <div
      ref={wrapRef}
      className={className}
      style={{ position: "relative", width: "100%", height: "100%", overflow: "hidden" }}
    >
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />

      {/* legend chips */}
      <div
        style={{
          position: "absolute",
          top: 16,
          right: 16,
          display: "flex",
          flexDirection: "column",
          gap: 2,
          zIndex: 5,
        }}
      >
        {CATEGORIES.map((c) => {
          const off = hidden.has(c.key);
          return (
            <div
              key={c.key}
              onClick={() => toggleCat(c.key)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                fontSize: 11,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "var(--muted, #828A97)",
                cursor: "pointer",
                userSelect: "none",
                padding: "6px 9px",
                borderRadius: 8,
                minWidth: 160,
                fontFamily: "ui-monospace, Menlo, monospace",
                opacity: off ? 0.32 : 1,
              }}
            >
              <span
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: "50%",
                  background: COLORS[c.key],
                  boxShadow: off ? "none" : `0 0 10px 1px ${COLORS[c.key]}`,
                  flex: "none",
                }}
              />
              {c.label}
              <span style={{ marginLeft: "auto", color: "var(--faint, #4A515C)", fontVariantNumeric: "tabular-nums" }}>
                {counts.get(c.key) ?? 0}
              </span>
            </div>
          );
        })}
      </div>

      {/* search */}
      <div
        style={{
          position: "absolute",
          bottom: 20,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 5,
        }}
      >
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search your knowledge…"
          autoComplete="off"
          style={{
            background: "rgba(16,18,23,.62)",
            border: "1px solid rgba(255,255,255,.09)",
            borderRadius: 999,
            padding: "10px 17px",
            color: "var(--ink, #D2D6DE)",
            fontSize: 13,
            outline: "none",
            width: 220,
            backdropFilter: "blur(16px)",
          }}
        />
      </div>

      {/* hover tag */}
      {tag && (
        <div
          style={{
            position: "absolute",
            left: tag.x,
            top: tag.y,
            zIndex: 8,
            pointerEvents: "none",
            background: "rgba(12,14,18,.86)",
            border: "1px solid rgba(255,255,255,.09)",
            borderRadius: 11,
            padding: "11px 14px",
            backdropFilter: "blur(14px)",
            maxWidth: 250,
            boxShadow: "0 12px 44px rgba(0,0,0,.55)",
          }}
        >
          <div
            style={{
              fontSize: 9.5,
              letterSpacing: "0.24em",
              textTransform: "uppercase",
              fontFamily: "ui-monospace, Menlo, monospace",
              marginBottom: 4,
              color: tag.color,
            }}
          >
            {tag.type}
          </div>
          <div style={{ fontSize: 14, color: "#F1F3F6", lineHeight: 1.3, fontWeight: 450 }}>{tag.label}</div>
          {tag.meta && (
            <div style={{ fontSize: 11, color: "var(--muted, #828A97)", marginTop: 5, fontFamily: "ui-monospace, Menlo, monospace" }}>
              {tag.meta}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
