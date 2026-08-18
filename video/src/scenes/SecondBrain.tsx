import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Chip, Eyebrow, Mono, Panel} from '../components/primitives';
import {easeInOut, pop, ramp} from '../lib/anim';
import {color, font, label} from '../theme';

type Node = {
  id: number;
  x: number;
  y: number;
  r: number;
  /** Position in the corpus' history, 0 = oldest. Drives the time scrub. */
  t: number;
  name?: string;
};

const NODES: Node[] = [
  {id: 1, x: 620, y: 470, r: 19, t: 0.08, name: '[[Q3 plan]]'},
  {id: 2, x: 466, y: 366, r: 13, t: 0.2, name: '[[EMEA renewals]]'},
  {id: 3, x: 774, y: 358, r: 13, t: 0.27, name: '[[pricing]]'},
  {id: 4, x: 758, y: 598, r: 13, t: 0.34, name: '[[churn cohort]]'},
  {id: 5, x: 458, y: 588, r: 13, t: 0.3, name: '[[warehouse]]'},
  {id: 6, x: 332, y: 470, r: 9, t: 0.44},
  {id: 7, x: 902, y: 470, r: 9, t: 0.53},
  {id: 8, x: 620, y: 300, r: 9, t: 0.5},
  {id: 9, x: 620, y: 662, r: 9, t: 0.61},
  {id: 10, x: 382, y: 688, r: 8, t: 0.69},
  {id: 11, x: 878, y: 688, r: 8, t: 0.73},
  {id: 12, x: 352, y: 300, r: 8, t: 0.79},
  {id: 13, x: 898, y: 292, r: 8, t: 0.85},
  {id: 14, x: 520, y: 752, r: 7, t: 0.91},
  {id: 15, x: 706, y: 742, r: 7, t: 0.96},
];

const EDGES: [number, number][] = [
  [1, 2], [1, 3], [1, 4], [1, 5], [2, 6], [5, 6], [3, 7], [4, 7],
  [1, 8], [8, 12], [8, 13], [1, 9], [9, 10], [9, 11], [5, 10],
  [4, 11], [10, 14], [11, 15], [2, 12], [3, 13],
];

const byId = (id: number) => NODES.find((n) => n.id === id)!;

const TRACK = {x0: 190, x1: 1150, y: 838};

export const SecondBrain: React.FC = () => {
  const frame = useCurrentFrame();

  /** Growth: nodes land in history order between frames 14 and 120. */
  const grown = interpolate(frame, [14, 120], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  /**
   * Scrub: the handle rides back to an earlier instant, then returns to now.
   * Anything newer than the handle drops out of the graph while it is back.
   */
  const scrub = interpolate(frame, [146, 182, 206, 232], [1, 0.36, 0.36, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: easeInOut,
  });

  const scrubUi = ramp(frame, 132, 20);
  const inbox = pop(frame, 178);
  const handleX = TRACK.x0 + (TRACK.x1 - TRACK.x0) * scrub;

  const vis = (n: Node) => {
    const born = n.t <= grown ? 1 : 0;
    const inWindow = n.t <= scrub + 0.02 ? 1 : 0.07;
    return born * (0.14 + 0.86 * inWindow);
  };

  return (
    <Plate plate="05" title="Second brain" quiet>
      <div style={{position: 'absolute', left: 190, top: 104}}>
        <Eyebrow delay={2} tone={color.violet}>
          A second brain with a time axis
        </Eyebrow>
        <div
          style={{
            marginTop: 20,
            fontSize: 40,
            fontWeight: 500,
            color: color.inkSoft,
            opacity: ramp(frame, 10, 22),
          }}
        >
          Memory forms on its own —{' '}
          <span style={{color: color.amber}}>and every belief carries time.</span>
        </div>
      </div>

      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <defs>
          <filter id="node-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {EDGES.map(([a, b], i) => {
          const na = byId(a);
          const nb = byId(b);
          const o = Math.min(vis(na), vis(nb));
          return (
            <line
              key={i}
              x1={na.x}
              y1={na.y}
              x2={nb.x}
              y2={nb.y}
              stroke={color.violet}
              strokeWidth={1}
              opacity={o * 0.34}
            />
          );
        })}

        {NODES.map((n) => {
          const o = vis(n);
          const breathe = 1 + Math.sin(frame / 15 + n.id) * 0.035;
          return (
            <g key={n.id} opacity={o}>
              <circle
                cx={n.x}
                cy={n.y}
                r={n.r * breathe}
                fill={n.name ? color.amber : color.violet}
                filter={n.name ? 'url(#node-glow)' : undefined}
              />
              <circle
                cx={n.x}
                cy={n.y}
                r={n.r * breathe + 7}
                fill="none"
                stroke={n.name ? color.amber : color.violet}
                strokeWidth={1}
                opacity={0.28}
              />
            </g>
          );
        })}

        {/* Time track */}
        <g opacity={scrubUi}>
          <line
            x1={TRACK.x0}
            y1={TRACK.y}
            x2={TRACK.x1}
            y2={TRACK.y}
            stroke={color.rule}
            strokeWidth={2}
          />
          <line
            x1={TRACK.x0}
            y1={TRACK.y}
            x2={handleX}
            y2={TRACK.y}
            stroke={color.amber}
            strokeWidth={2}
          />
          {Array.from({length: 13}).map((_, i) => {
            const x = TRACK.x0 + ((TRACK.x1 - TRACK.x0) * i) / 12;
            return (
              <line
                key={i}
                x1={x}
                y1={TRACK.y - 6}
                x2={x}
                y2={TRACK.y + 6}
                stroke={color.rule}
                strokeWidth={1}
              />
            );
          })}
          <circle cx={handleX} cy={TRACK.y} r={11} fill={color.amber} />
          <circle cx={handleX} cy={TRACK.y} r={20} fill={color.amber} opacity={0.2} />
        </g>
      </svg>

      {/* Node labels sit in HTML so they get real font rendering. */}
      {NODES.filter((n) => n.name).map((n) => (
        <div
          key={n.id}
          style={{
            position: 'absolute',
            left: n.x + n.r + 12,
            top: n.y - 12,
            fontFamily: font.mono,
            fontSize: 16,
            color: color.amberSoft,
            letterSpacing: '0.02em',
            opacity: vis(n),
            whiteSpace: 'nowrap',
          }}
        >
          {n.name}
        </div>
      ))}

      <div
        style={{
          position: 'absolute',
          left: TRACK.x0,
          top: TRACK.y + 26,
          width: TRACK.x1 - TRACK.x0,
          display: 'flex',
          justifyContent: 'space-between',
          opacity: scrubUi,
        }}
      >
        <Mono size={14} tone={color.faint}>
          FIRST BELIEF
        </Mono>
        <Mono size={14} tone={color.amber}>
          {scrub > 0.95 ? 'NOW' : `T − ${Math.round((1 - scrub) * 118)} DAYS`}
        </Mono>
        <Mono size={14} tone={color.faint}>
          NOW
        </Mono>
      </div>

      {/* ---- right column ---- */}
      <Panel
        style={{
          position: 'absolute',
          left: 1244,
          top: 236,
          width: 540,
          padding: '24px 26px',
          opacity: ramp(frame, 60, 20),
        }}
      >
        <Mono size={14} tone={color.muted} tracking="0.14em">
          BELIEF · WITH A TIME AXIS
        </Mono>
        <div style={{marginTop: 18, fontSize: 23, color: color.ink, lineHeight: 1.35}}>
          EMEA renewals slip roughly two weeks past close.
        </div>
        <div style={{marginTop: 20, display: 'flex', flexDirection: 'column', gap: 11}}>
          {[
            ['took effect', '2026-03-14'],
            ['superseded', scrub > 0.7 ? '2026-06-02' : '— still current'],
            ['source', 'session distillation'],
          ].map(([k, v]) => (
            <div key={k} style={{display: 'flex', justifyContent: 'space-between'}}>
              <Mono size={15} tone={color.mutedDim}>
                {k}
              </Mono>
              <Mono size={15} tone={color.inkSoft}>
                {v}
              </Mono>
            </div>
          ))}
        </div>
        <div style={{marginTop: 20, display: 'flex', gap: 8}}>
          <Chip tone={color.violet} size={12}>
            hybrid FTS5 + embedding
          </Chip>
          <Chip tone={color.mutedDim} size={12}>
            [[wiki-linked]]
          </Chip>
        </div>
      </Panel>

      <Panel
        tone={color.amber}
        glow={0.35}
        style={{
          position: 'absolute',
          left: 1244,
          top: 602,
          width: 540,
          padding: '24px 26px',
          opacity: Math.min(1, inbox * 1.4),
          transform: `translateY(${(1 - inbox) * 22}px)`,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <Mono size={14} tone={color.amberSoft} tracking="0.14em">
            INBOX · MEMORY EDIT
          </Mono>
          <Chip tone={color.amber} size={11}>
            proposed
          </Chip>
        </div>
        <div style={{marginTop: 16, fontSize: 21, color: color.inkSoft, lineHeight: 1.4}}>
          The model wants to delete{' '}
          <span style={{fontFamily: font.mono, color: color.ink}}>
            “Q1 target = 4.2M”
          </span>
          .
        </div>
        <div style={{marginTop: 18, display: 'flex', gap: 12}}>
          <div
            style={{
              flex: 1,
              height: 46,
              borderRadius: 9,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: `1px solid ${color.amber}`,
              color: color.amberSoft,
              fontSize: 16,
            }}
          >
            Accept
          </div>
          <div
            style={{
              flex: 1,
              height: 46,
              borderRadius: 9,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: `1px solid ${color.rule}`,
              color: color.muted,
              fontSize: 16,
            }}
          >
            Dismiss
          </div>
        </div>
        <div style={{marginTop: 16, ...label, fontSize: 11.5, color: color.faint}}>
          Nothing is overwritten silently
        </div>
      </Panel>
    </Plate>
  );
};
