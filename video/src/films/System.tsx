import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {font} from '../theme';

/**
 * FILM 3 of 4 — "SYSTEM".
 *
 * Near-black, and the only cut of the four that shows the architecture rather
 * than the interface. No UI, no photography, no page: a host node, six spawns
 * at different depths, and light travelling between them. The argument is
 * structural — this is what the thing IS — where the CLI cut argues by
 * demonstration and the press cut argues by assertion.
 *
 * Shot vocabulary, from the shotcraft library:
 *   - `glow-flyline-moves` C (orb-flyline-relay) — the whole spine. Three
 *     heavily blurred orbs drift on crossed periods as an ambient floor; arcs
 *     grow from host to spawn with a bright head leading and the tail falling
 *     off behind it; and on the frame a line lands, the nearest orb surges on
 *     THAT frame. The card is emphatic that the surge must be same-frame — two
 *     frames out and the ambient layer and the event layer read as two
 *     unrelated animations instead of one answering the other.
 *   - `depth-layer-moves` — parallax between the orb floor (0.35), the node
 *     plane (1.0) and a foreground dust layer (1.4), and exactly one
 *     dolly-zoom, at the gate. Once per film, per the card.
 *   - `cloner-depth-echo` — the spawn ring sits at six different z values, so
 *     the camera move produces real parallax between them rather than a flat
 *     rotation.
 *
 * The ambient layer freezes last and the event layer resolves first, which is
 * the card's rule for how a shot like this comes to rest.
 */

const S = {
  bg: '#050609',
  ink: '#E8EDF5',
  dim: '#8A93A3',
  faint: '#4C5462',
  amber: '#F2A03C',
  cyan: '#5EE7E0',
  violet: '#9B8CFF',
  green: '#4ADE80',
};

const ramp = (f: number, s: number, l: number, e = Easing.out(Easing.cubic)) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

const CX = 960;
const CY = 540;

/** Six spawns on a ring, each at its own depth so the camera gets parallax. */
const SPAWNS = [
  {a: -90, r: 330, z: -180, label: 'research', tone: S.cyan},
  {a: -30, r: 380, z: 60, label: 'data', tone: S.amber},
  {a: 30, r: 340, z: -60, label: 'coding', tone: S.cyan},
  {a: 90, r: 370, z: 140, label: 'ops', tone: S.violet},
  {a: 150, r: 345, z: -120, label: 'triage', tone: S.amber},
  {a: 210, r: 385, z: 20, label: 'archivist', tone: S.violet},
];

const posOf = (s: (typeof SPAWNS)[number]) => {
  const rad = (s.a * Math.PI) / 180;
  return {x: CX + Math.cos(rad) * s.r, y: CY + Math.sin(rad) * s.r * 0.62};
};

/** A quadratic bezier bulging away from the centre. */
const arcOf = (s: (typeof SPAWNS)[number]) => {
  const p = posOf(s);
  const mx = (CX + p.x) / 2;
  const my = (CY + p.y) / 2;
  const dx = p.x - CX;
  const dy = p.y - CY;
  const len = Math.hypot(dx, dy) || 1;
  // Perpendicular offset, so no two arcs sit on top of each other.
  const k = 0.26;
  return {
    p,
    c: {x: mx + (-dy / len) * len * k, y: my + (dx / len) * len * k},
  };
};

const bezierAt = (
  t: number,
  a: {x: number; y: number},
  c: {x: number; y: number},
  b: {x: number; y: number},
) => ({
  x: (1 - t) * (1 - t) * a.x + 2 * (1 - t) * t * c.x + t * t * b.x,
  y: (1 - t) * (1 - t) * a.y + 2 * (1 - t) * t * c.y + t * t * b.y,
});

/**
 * `glow-flyline-moves` A. Three orbs, amplitudes summing well past 240px and
 * periods deliberately not commensurate — same-period drift reads as the whole
 * frame swaying rather than as three independent things.
 */
const ORBS = [
  {x: 520, y: 340, r: 640, tone: '242,160,60', peak: 0.32, px: 118, py: 92, ax: 190, ay: 120},
  {x: 1420, y: 620, r: 560, tone: '94,231,224', peak: 0.22, px: 134, py: 106, ax: 150, ay: 160},
  {x: 900, y: 880, r: 700, tone: '155,140,255', peak: 0.18, px: 92, py: 128, ax: 210, ay: 90},
];

const Orbs: React.FC<{frame: number; surge: number}> = ({frame, surge}) => {
  // Ambient freezes last: it eases to a stop after the events have resolved.
  const live = interpolate(frame, [740, 860], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.sin),
  });
  return (
    <>
      {ORBS.map((o, i) => {
        const t = frame * live;
        const x = o.x + Math.sin((t / o.px) * Math.PI * 2) * o.ax;
        const y = o.y + Math.cos((t / o.py) * Math.PI * 2) * o.ay;
        const op = o.peak * (1 + (i === 0 ? surge * 1.6 : surge * 0.5));
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x - o.r / 2,
              top: y - o.r / 2,
              width: o.r,
              height: o.r,
              borderRadius: '50%',
              background: `radial-gradient(circle, rgba(${o.tone},${op}) 0%, rgba(${o.tone},0) 70%)`,
              filter: 'blur(100px)',
            }}
          />
        );
      })}
    </>
  );
};

const Node: React.FC<{
  x: number;
  y: number;
  r: number;
  tone: string;
  label?: string;
  on: number;
  pulse: number;
}> = ({x, y, r, tone, label, on, pulse}) => (
  <>
    <div
      style={{
        position: 'absolute',
        left: x - r,
        top: y - r,
        width: r * 2,
        height: r * 2,
        borderRadius: '50%',
        background: tone,
        opacity: on,
        boxShadow: `0 0 ${28 + pulse * 60}px ${8 + pulse * 22}px ${tone}${pulse > 0.02 ? '55' : '22'}`,
        transform: `scale(${1 + pulse * 0.28})`,
      }}
    />
    {label ? (
      <div
        style={{
          position: 'absolute',
          left: x + r + 16,
          top: y - 13,
          fontFamily: font.mono,
          fontSize: 21,
          letterSpacing: '0.1em',
          color: S.dim,
          opacity: on,
        }}
      >
        {label}
      </div>
    ) : null}
  </>
);

/* ------------------------------------------------------------------ */

export const SYSTEM_FRAMES = 900;

/** Frame each arc lands. Spacing tightens: the fan-out is accelerating. */
const OUT_CUE = [150, 166, 180, 192, 202, 210];
const BACK_CUE = [330, 344, 356, 366, 374, 380];

export const System: React.FC = () => {
  const f = useCurrentFrame();

  /* ---- camera ------------------------------------------------------ */
  // Push in slowly through the fan-out, hold at the gate, then pull way out.
  const zoom = interpolate(
    f,
    [0, 140, 300, 440, 470, 620, 900],
    [1.34, 1.18, 1.06, 1.02, 1.02, 0.93, 0.88],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.4, 0, 0.2, 1)},
  );
  const yaw = interpolate(f, [0, 300, 620, 900], [-14, -4, 9, 13], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const tilt = interpolate(f, [0, 620, 900], [16, 9, 7], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });

  // `depth-layer-moves` — the one dolly-zoom in the film, at the gate: the
  // world expands past the lens while the gate itself is pinned to the frame.
  const dolly = interpolate(f, [452, 520], [1, 2.1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.4, 0, 0.2, 1),
  });
  const atGate = f >= 440 && f < 600;

  /* ---- resonance: the surge is driven by landing frames --------------- */
  let surge = 0;
  for (const c of [...OUT_CUE, ...BACK_CUE]) {
    const d = f - c;
    if (d >= 0 && d < 20) surge = Math.max(surge, ramp(f, c, 5) * (1 - ramp(f, c + 5, 15)));
  }

  const hostOn = ramp(f, 30, 40);
  const hostPulse = Math.max(
    ramp(f, 30, 30) * (1 - ramp(f, 60, 30)) * 0.6,
    ...BACK_CUE.map((c) => ramp(f, c, 4) * (1 - ramp(f, c + 4, 16))),
  );

  return (
    <AbsoluteFill style={{background: S.bg, overflow: 'hidden'}}>
      {/* Ambient floor. Parallax coefficient 0.35 — it barely moves. */}
      <AbsoluteFill
        style={{transform: `scale(${1 + (zoom - 1) * 0.35})`, opacity: 0.95}}
      >
        <Orbs frame={f} surge={surge} />
      </AbsoluteFill>

      {/* The system plane. It dims under the close: the diagram has carried
          the film and now has to get out of the way of the one piece of type
          that has to be read. */}
      <AbsoluteFill
        style={{
          opacity: 1 - ramp(f, 700, 54) * 0.72,
          perspective: 1600,
          transform: atGate ? `scale(${dolly})` : undefined,
          filter: atGate ? `blur(${(dolly - 1) * 3.2}px)` : undefined,
        }}
      >
        <AbsoluteFill
          style={{
            transformStyle: 'preserve-3d',
            transform: `scale(${zoom}) rotateX(${tilt}deg) rotateY(${yaw}deg)`,
          }}
        >
          <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
            {SPAWNS.map((s, i) => {
              const {p, c} = arcOf(s);
              const d = `M ${CX} ${CY} Q ${c.x} ${c.y} ${p.x} ${p.y}`;
              const L = Math.hypot(p.x - CX, p.y - CY) * 1.22;

              const out = ramp(f, OUT_CUE[i] - 22, 22);
              const back = ramp(f, BACK_CUE[i] - 20, 20);
              const live = f < 300 ? out : back;
              const dir = f < 300 ? 1 : -1;
              if (live <= 0) return null;

              return (
                <g key={i}>
                  <path
                    d={d}
                    stroke={s.tone}
                    strokeWidth={3.5}
                    fill="none"
                    opacity={0.5 * live}
                    strokeDasharray={L}
                    strokeDashoffset={L * (1 - live) * dir}
                    strokeLinecap="round"
                  />
                </g>
              );
            })}
          </svg>

          {/* Light heads, mounted only while their arc is growing — an opacity
              of zero is not the same as gone, and this film has to actually
              come to rest. */}
          {SPAWNS.map((s, i) => {
            const {p, c} = arcOf(s);
            const out = ramp(f, OUT_CUE[i] - 22, 22);
            const back = ramp(f, BACK_CUE[i] - 20, 20);
            const growing = f < 300 ? out > 0 && out < 1 : back > 0 && back < 1;
            if (!growing) return null;
            const t = f < 300 ? out : 1 - back;
            const q = bezierAt(t, {x: CX, y: CY}, c, p);
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: q.x - 7,
                  top: q.y - 7,
                  width: 14,
                  height: 14,
                  borderRadius: '50%',
                  background: '#fff',
                  boxShadow: `0 0 26px 10px ${s.tone}88`,
                }}
              />
            );
          })}

          {/* Spawn ring. Each at its own z, so the camera gets real parallax. */}
          {SPAWNS.map((s, i) => {
            const p = posOf(s);
            const on = ramp(f, 96 + i * 7, 26);
            const pulse = Math.max(
              ramp(f, OUT_CUE[i], 4) * (1 - ramp(f, OUT_CUE[i] + 4, 16)),
              ramp(f, BACK_CUE[i] - 20, 4) * (1 - ramp(f, BACK_CUE[i] - 16, 16)),
            );
            return (
              <div key={i} style={{position: 'absolute', inset: 0, transform: `translateZ(${s.z}px)`}}>
                <Node x={p.x} y={p.y} r={13} tone={s.tone} label={s.label} on={on} pulse={pulse} />
              </div>
            );
          })}

          {/* The host. */}
          <Node x={CX} y={CY} r={26} tone={S.ink} on={hostOn} pulse={hostPulse} />
        </AbsoluteFill>
      </AbsoluteFill>

      {/* Foreground dust — parallax 1.4, drifting past the lens. */}
      <AbsoluteFill style={{transform: `scale(${1 + (zoom - 1) * 1.4})`, filter: 'blur(3px)'}}>
        {Array.from({length: 14}).map((_, i) => {
          const seed = (i * 2654435761) % 1000;
          const x = (seed % 1900) + 10;
          const y = ((seed * 7) % 1040) + 20;
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: x + Math.sin((f + i * 40) / 90) * 26,
                top: y + Math.cos((f + i * 27) / 110) * 18,
                width: 3,
                height: 3,
                borderRadius: '50%',
                background: '#fff',
                opacity: 0.16,
              }}
            />
          );
        })}
      </AbsoluteFill>

      {/* Captions. Mono, small, bottom-left — a system readout, not a slogan. */}
      <Caption f={f} />

      {/* The gate. The one moment the film states a rule instead of drawing it. */}
      {f >= 440 && f < 640 ? <Gate f={f - 440} /> : null}

      {f >= 700 ? <Cta f={f - 700} /> : null}
    </AbsoluteFill>
  );
};

const LINES: [number, number, string][] = [
  [40, 140, 'one host agent · running on this machine'],
  [150, 300, 'six spawns · each with only the capabilities you handed it'],
  [320, 430, 'every result comes back to one thread'],
];

const Caption: React.FC<{f: number}> = ({f}) => (
  <>
    {LINES.map(([a, b, text]) => {
      const o = ramp(f, a, 16) * (1 - ramp(f, b - 14, 14));
      if (o <= 0.01) return null;
      return (
        <div
          key={text}
          style={{
            position: 'absolute',
            left: 96,
            bottom: 86,
            fontFamily: font.mono,
            fontSize: 26,
            letterSpacing: '0.06em',
            color: S.dim,
            opacity: o,
            transform: `translateY(${(1 - ramp(f, a, 16)) * 12}px)`,
          }}
        >
          <span style={{color: S.amber}}>▸ </span>
          {text}
        </div>
      );
    })}
  </>
);

const Gate: React.FC<{f: number}> = ({f}) => {
  const on = ramp(f, 0, 20);
  const passed = f > 118;
  return (
    <AbsoluteFill
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: on * (1 - ramp(f, 176, 24)),
      }}
    >
      <div
        style={{
          width: 900,
          border: `1px solid ${passed ? S.green : S.amber}66`,
          background: 'rgba(5,7,11,0.72)',
          backdropFilter: 'blur(8px)',
          padding: '38px 46px',
          fontFamily: font.mono,
        }}
      >
        <div style={{fontSize: 21, letterSpacing: '0.16em', color: S.faint}}>
          PROMOTION GATE · HELD-OUT EXAM n=38 · SAMPLE DATA
        </div>
        <div style={{marginTop: 26, display: 'flex', flexDirection: 'column', gap: 14}}>
          {([
            ['faithfulness', 0.71, 0.86],
            ['task completion', 0.64, 0.81],
            ['tool discipline', 0.78, 0.83],
            ['honesty', 0.82, 0.82],
          ] as [string, number, number][]).map(([k, a, b], i) => {
            const v = interpolate(f, [22 + i * 8, 58 + i * 8], [a, b], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: Easing.out(Easing.cubic),
            });
            return (
              <div key={k} style={{display: 'flex', fontSize: 24, color: S.dim}}>
                <span style={{flex: 1}}>{k}</span>
                <span style={{color: S.faint, marginRight: 24}}>{a.toFixed(2)}</span>
                <span style={{color: S.green}}>{v.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
        <div
          style={{
            marginTop: 32,
            padding: '18px 0',
            textAlign: 'center',
            fontSize: 27,
            letterSpacing: '0.12em',
            color: passed ? S.green : S.amber,
            border: `1px solid ${passed ? S.green : S.amber}`,
            background: passed ? 'rgba(74,222,128,0.08)' : 'rgba(242,160,60,0.08)',
          }}
        >
          {passed ? '✔ PROMOTED BY YOU' : '⏎ AWAITING YOUR PROMOTE'}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Cta: React.FC<{f: number}> = ({f}) => {
  const a = ramp(f, 2, 30, Easing.bezier(0.16, 1.2, 0.3, 1));
  const b = ramp(f, 24, 30, Easing.bezier(0.16, 1.2, 0.3, 1));
  return (
    <AbsoluteFill
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        fontFamily: font.sans,
        textAlign: 'center',
        background: `radial-gradient(72% 62% at 50% 50%, rgba(5,6,9,${0.9 * ramp(f, 0, 30)}) 0%, rgba(5,6,9,${0.35 * ramp(f, 0, 30)}) 100%)`,
      }}
    >
      <div
        style={{
          fontSize: 128,
          fontWeight: 700,
          letterSpacing: '-0.05em',
          color: S.ink,
          opacity: a,
          transform: `translateY(${(1 - a) * 24}px)`,
          textShadow: '0 0 80px rgba(242,160,60,0.28)',
        }}
      >
        Arslan
      </div>
      <div
        style={{
          marginTop: 18,
          fontSize: 30,
          color: S.dim,
          opacity: a,
          maxWidth: 900,
        }}
      >
        One host agent. Spawns you raised. Nothing ships until you press Promote.
      </div>
      <div
        style={{
          marginTop: 46,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 16,
          padding: '24px 46px',
          borderRadius: 999,
          background: S.ink,
          color: '#07090D',
          fontSize: 30,
          fontWeight: 650,
          opacity: b,
          transform: `translateY(${(1 - b) * 18}px)`,
          boxShadow: '0 24px 70px rgba(94,231,224,0.20)',
        }}
      >
        <span>↓</span> Download for macOS
      </div>
      <div
        style={{
          marginTop: 20,
          fontFamily: font.mono,
          fontSize: 20,
          letterSpacing: '0.1em',
          color: S.faint,
          opacity: b,
        }}
      >
        macOS 11+ · Apple Silicon · signed &amp; notarized · MIT
      </div>
    </AbsoluteFill>
  );
};
