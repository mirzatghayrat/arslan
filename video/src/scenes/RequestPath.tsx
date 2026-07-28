import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Chip, Eyebrow, Mono} from '../components/primitives';
import {drawPath, ease, pop, ramp, typed} from '../lib/anim';
import {straight, wire, type Wire} from '../lib/geom';
import {color, font, label} from '../theme';

const HOST = {x: 862, y: 424};
const SPAWNS = [
  {
    x: 1272,
    y: 226,
    name: 'Research Analyst',
    kind: 'RESEARCH · WEB',
    work: 'fetch · 11 sources',
    at: 118,
  },
  {
    x: 1272,
    y: 424,
    name: 'Data & Chart Analyst',
    kind: 'ANALYTICS · VISUAL',
    work: 'python · sandboxed',
    at: 130,
  },
  {
    x: 1272,
    y: 622,
    name: 'Coding Assistant',
    kind: 'ENGINEERING · SWE',
    work: 'diff · 2 files',
    at: 142,
  },
];

const REQUEST = 'Chart last quarter against the plan and tell me what moved.';

const OUT: Wire = straight({x: 566, y: HOST.y}, {x: HOST.x - 68, y: HOST.y});
const LEGS: Wire[] = [
  wire(
    {x: HOST.x + 68, y: HOST.y},
    {x: HOST.x + 210, y: HOST.y},
    {x: SPAWNS[0].x - 190, y: SPAWNS[0].y},
    {x: SPAWNS[0].x - 46, y: SPAWNS[0].y},
  ),
  straight({x: HOST.x + 68, y: HOST.y}, {x: SPAWNS[1].x - 46, y: SPAWNS[1].y}),
  wire(
    {x: HOST.x + 68, y: HOST.y},
    {x: HOST.x + 210, y: HOST.y},
    {x: SPAWNS[2].x - 190, y: SPAWNS[2].y},
    {x: SPAWNS[2].x - 46, y: SPAWNS[2].y},
  ),
];

const RAILS = [
  {
    y: 812,
    title: 'KERNEL SANDBOX',
    detail: 'generated code runs network-denied · macOS seatbelt · fails closed',
    tone: color.green,
    at: 168,
  },
  {
    y: 892,
    title: 'SECOND BRAIN',
    detail: 'hybrid FTS5 + embedding recall · 6 notes matched · beliefs carry time',
    tone: color.violet,
    at: 186,
  },
];

/** Amber dot flying a wire, with a soft comet trail behind it. */
const Packet: React.FC<{w: Wire; t: number; tone?: string}> = ({
  w,
  t,
  tone = color.amberHi,
}) => {
  if (t <= 0 || t >= 1) return null;
  const head = w.at(t);
  const trail = [0.05, 0.1, 0.16].map((d) => w.at(Math.max(0, t - d)));
  return (
    <g>
      {trail.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={6 - i * 1.4} fill={tone} opacity={0.28 - i * 0.08} />
      ))}
      <circle cx={head.x} cy={head.y} r={7} fill={tone} />
      <circle cx={head.x} cy={head.y} r={15} fill={tone} opacity={0.18} />
    </g>
  );
};

export const RequestPath: React.FC = () => {
  const frame = useCurrentFrame();

  const req = typed(frame, 26, REQUEST, 46);
  const send = ramp(frame, 74, 14);
  const outPacket = interpolate(frame, [78, 100], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });
  const hostLive = pop(frame, 96);
  const routing = ramp(frame, 100, 18);

  // Return leg: spawns answer, packets converge back through the host.
  const back = interpolate(frame, [228, 258], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });
  const backOut = interpolate(frame, [252, 274], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });
  const answer = pop(frame, 268);
  const caption = ramp(frame, 10, 24);

  return (
    <Plate plate="02" title="Request path" quiet>
      <div style={{position: 'absolute', left: 120, top: 84}}>
        <Eyebrow delay={2}>One request, end to end</Eyebrow>
      </div>

      {/* ---- wiring layer ---- */}
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <defs>
          <filter id="wire-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" />
          </filter>
        </defs>

        <path
          d={OUT.d}
          stroke={color.ruleHi}
          strokeWidth={1.5}
          fill="none"
          {...drawPath(send, OUT.length)}
        />

        {LEGS.map((w, i) => {
          const p = ramp(frame, 102 + i * 9, 26);
          const settled = frame > 150;
          return (
            <g key={i}>
              <path
                d={w.d}
                stroke={settled ? color.amberDeep : color.ruleHi}
                strokeWidth={1.5}
                fill="none"
                {...drawPath(p, w.length)}
              />
              {settled ? (
                <path
                  d={w.d}
                  stroke={color.amber}
                  strokeWidth={1}
                  fill="none"
                  opacity={0.5 + Math.sin((frame - 150) / 9 + i) * 0.2}
                  filter="url(#wire-glow)"
                />
              ) : null}
            </g>
          );
        })}

        {/* Drop lines tying host + spawns to the substrate rails. */}
        {[HOST, ...SPAWNS].map((n, i) => {
          const p = ramp(frame, 160 + i * 6, 22);
          // The host circle is larger than a spawn circle, so it needs a
          // deeper start or the dashed line pokes out from inside the disc.
          const top = n.y + (i === 0 ? 78 : 56);
          return (
            <line
              key={i}
              x1={n.x}
              y1={top}
              x2={n.x}
              y2={top + (RAILS[1].y - 22 - top) * p}
              stroke={color.rule}
              strokeWidth={1}
              strokeDasharray="4 7"
            />
          );
        })}

        {RAILS.map((r, i) => {
          const p = ramp(frame, r.at, 26);
          return (
            <line
              key={i}
              x1={140}
              y1={r.y}
              x2={140 + (1780 - 140) * p}
              stroke={r.tone}
              strokeWidth={1.5}
              y2={r.y}
              opacity={0.5}
            />
          );
        })}

        <Packet w={OUT} t={outPacket} />
        {LEGS.map((w, i) => {
          const t = interpolate(frame, [104 + i * 9, 132 + i * 9], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: ease,
          });
          return <Packet key={i} w={w} t={t} />;
        })}
        {LEGS.map((w, i) => (
          <Packet key={`b${i}`} w={w} t={1 - back} tone={color.green} />
        ))}
        <Packet w={OUT} t={1 - backOut} tone={color.green} />
      </svg>

      {/* ---- the one thread ---- */}
      <div
        style={{
          position: 'absolute',
          left: 120,
          top: 222,
          width: 446,
          borderRadius: 18,
          border: `1px solid ${color.rule}`,
          background: `linear-gradient(170deg, ${color.panel}, ${color.plate})`,
          boxShadow: '0 24px 60px rgba(0,0,0,0.5)',
          overflow: 'hidden',
          opacity: ramp(frame, 4, 20),
        }}
      >
        <div
          style={{
            padding: '14px 20px',
            borderBottom: `1px solid ${color.rule}`,
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <span style={{width: 9, height: 9, borderRadius: 9, background: color.amber}} />
          <Mono size={14} tone={color.muted} tracking="0.16em">
            ORCHESTRATOR SESSION
          </Mono>
        </div>

        <div style={{padding: '26px 22px 24px', minHeight: 236}}>
          <div
            style={{
              background: `${color.amber}14`,
              border: `1px solid ${color.amber}3a`,
              borderRadius: 14,
              borderTopRightRadius: 4,
              padding: '16px 18px',
              fontSize: 21,
              lineHeight: 1.45,
              color: color.ink,
              minHeight: 62,
            }}
          >
            {req}
            {req.length < REQUEST.length && frame > 24 ? (
              <span
                style={{
                  display: 'inline-block',
                  width: 2,
                  height: 22,
                  background: color.amber,
                  marginLeft: 3,
                  verticalAlign: 'text-bottom',
                  opacity: Math.floor(frame / 8) % 2 ? 1 : 0.15,
                }}
              />
            ) : null}
          </div>

          <div
            style={{
              marginTop: 20,
              display: 'flex',
              gap: 8,
              flexWrap: 'wrap',
              opacity: routing,
            }}
          >
            <Chip tone={color.amber} size={13}>
              routing
            </Chip>
            <Chip tone={color.mutedDim} size={13}>
              3 spawns
            </Chip>
          </div>

          <div
            style={{
              marginTop: 22,
              opacity: Math.min(1, answer * 1.2),
              transform: `translateY(${(1 - answer) * 14}px)`,
              background: color.panelHi,
              border: `1px solid ${color.rule}`,
              borderRadius: 14,
              borderTopLeftRadius: 4,
              padding: '16px 18px',
            }}
          >
            <div style={{fontSize: 19, lineHeight: 1.5, color: color.inkSoft}}>
              Revenue tracked +8.4% to plan; the gap is all in EMEA renewals.
              Chart and the query are attached.
            </div>
            <div style={{marginTop: 12, display: 'flex', gap: 8}}>
              <Chip tone={color.green} size={12}>
                answered in 1 thread
              </Chip>
            </div>
          </div>
        </div>
      </div>

      {/* ---- host node ---- */}
      <div
        style={{
          position: 'absolute',
          left: HOST.x - 68,
          top: HOST.y - 68,
          width: 136,
          height: 136,
          borderRadius: 999,
          border: `1.5px solid ${color.amber}`,
          background: `radial-gradient(circle at 50% 40%, ${color.amberInk}, ${color.plate})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${0.6 + hostLive * 0.4})`,
          opacity: Math.min(1, hostLive * 1.6),
          boxShadow: `0 0 ${44 + Math.sin(frame / 12) * 14}px ${color.amber}4d`,
        }}
      >
        <div style={{textAlign: 'center'}}>
          <div style={{...label, fontSize: 12, color: color.amberSoft, fontWeight: 600}}>
            HOST
          </div>
          <div style={{...label, fontSize: 12, color: color.amberSoft, fontWeight: 600}}>
            AGENT
          </div>
        </div>
      </div>

      {/* ---- spawn nodes ---- */}
      {SPAWNS.map((s, i) => {
        const p = pop(frame, s.at);
        const busy = frame > s.at + 20 && frame < 236;
        const done = frame >= 236;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: s.x - 46,
              top: s.y - 46,
              display: 'flex',
              alignItems: 'center',
              gap: 20,
              opacity: Math.min(1, p * 1.5),
              transform: `translateX(${(1 - p) * 26}px)`,
            }}
          >
            <div
              style={{
                width: 92,
                height: 92,
                borderRadius: 999,
                flexShrink: 0,
                border: `1.5px solid ${done ? color.green : color.amber}`,
                background: `radial-gradient(circle at 50% 35%, ${color.panelHi}, ${color.plate})`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: busy
                  ? `0 0 ${26 + Math.sin(frame / 7 + i * 2) * 12}px ${color.amber}44`
                  : `0 0 24px ${done ? color.green : color.amber}26`,
              }}
            >
              <span
                style={{
                  ...label,
                  fontSize: 13,
                  fontWeight: 600,
                  color: done ? color.green : color.amberSoft,
                }}
              >
                {done ? '✓' : `S${i + 1}`}
              </span>
            </div>

            <div style={{paddingTop: 4}}>
              <div
                style={{
                  fontSize: 25,
                  fontWeight: 600,
                  color: color.ink,
                  letterSpacing: '-0.01em',
                }}
              >
                {s.name}
              </div>
              <div
                style={{
                  ...label,
                  fontSize: 12,
                  color: color.mutedDim,
                  marginTop: 6,
                  fontWeight: 500,
                }}
              >
                {s.kind}
              </div>
              <div style={{marginTop: 12, opacity: ramp(frame, s.at + 24, 18)}}>
                <Chip tone={done ? color.green : color.amber} size={13}>
                  {done ? 'returned' : s.work}
                </Chip>
              </div>
            </div>
          </div>
        );
      })}

      {/* ---- substrate rails ---- */}
      {RAILS.map((r, i) => {
        const p = ramp(frame, r.at + 10, 22);
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: 140,
              top: r.y + 14,
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              opacity: p,
              transform: `translateY(${(1 - p) * 8}px)`,
            }}
          >
            <span
              style={{
                ...label,
                fontSize: 14,
                fontWeight: 600,
                color: r.tone,
              }}
            >
              {r.title}
            </span>
            <span style={{width: 1, height: 16, background: color.rule}} />
            <span
              style={{
                fontFamily: font.mono,
                fontSize: 16,
                color: color.mutedDim,
                letterSpacing: '0.02em',
              }}
            >
              {r.detail}
            </span>
          </div>
        );
      })}

      {/* ---- closing caption ---- */}
      <div
        style={{
          position: 'absolute',
          left: 120,
          top: 120,
          opacity: caption,
          transform: `translateY(${(1 - caption) * 10}px)`,
        }}
      >
        <div style={{fontSize: 40, fontWeight: 500, color: color.inkSoft}}>
          You ask once. <span style={{color: color.amber}}>One thread answers.</span>
        </div>
      </div>
    </Plate>
  );
};
