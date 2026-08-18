import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Chip, Eyebrow, Mono, Panel} from '../components/primitives';
import {countTo, ease, pop, ramp} from '../lib/anim';
import {color, font, label} from '../theme';

const COL_W = 520;
const GAP = 50;
const X0 = 130;
const TOP = 286;
const H = 434;

// Centre of the Promote button, derived from the panel box so the cursor,
// the click ripple and the button itself can never drift apart.
const BTN = {x: 130 + 2 * (520 + 50) + 26 + (520 - 52 - 14 - 150) / 2, y: 286 + 434 - 24 - 27};

const colX = (i: number) => X0 + i * (COL_W + GAP);

/** Held-out exam dimensions. Candidate must not regress on any of them. */
const DIMS = [
  {name: 'faithfulness', incumbent: 0.71, candidate: 0.86},
  {name: 'task completion', incumbent: 0.64, candidate: 0.81},
  {name: 'tool discipline', incumbent: 0.78, candidate: 0.83},
  {name: 'honesty', incumbent: 0.82, candidate: 0.82},
];

const DIFF = [
  {sign: '-', text: 'Answer the user question.', at: 46},
  {sign: '+', text: 'Answer the question. State what you', at: 60},
  {sign: '+', text: 'could not verify, and why.', at: 70},
  {sign: '-', text: 'Use tools when helpful.', at: 84},
  {sign: '+', text: 'Prefer recall before you assume.', at: 96},
];

const StageHead: React.FC<{i: number; n: string; title: string}> = ({i, n, title}) => {
  const frame = useCurrentFrame();
  const p = ramp(frame, 6 + i * 8, 20);
  return (
    <div
      style={{
        position: 'absolute',
        left: colX(i),
        top: TOP - 58,
        width: COL_W,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        opacity: p,
        transform: `translateY(${(1 - p) * 8}px)`,
      }}
    >
      <span
        style={{
          ...label,
          fontSize: 13,
          fontWeight: 600,
          color: color.amber,
          border: `1px solid ${color.amber}59`,
          borderRadius: 6,
          padding: '4px 9px',
        }}
      >
        {n}
      </span>
      <span style={{...label, fontSize: 14, fontWeight: 500, color: color.muted}}>
        {title}
      </span>
    </div>
  );
};

export const PromotionGate: React.FC = () => {
  const frame = useCurrentFrame();

  const verdict = ramp(frame, 186, 18);
  const proposal = pop(frame, 206);

  // Cursor travels to the Promote button and clicks at frame 262.
  const cursorT = interpolate(frame, [232, 260], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });
  const clicked = frame >= 262;
  const press = frame >= 262 && frame < 268 ? 0.94 : 1;
  const promoted = ramp(frame, 266, 14);

  const cursorX = 1150 + (BTN.x - 1150) * cursorT;
  const cursorY = 940 + (BTN.y - 940) * cursorT;

  return (
    <Plate plate="04" title="Promotion gate" quiet>
      <div style={{position: 'absolute', left: 130, top: 104}}>
        <Eyebrow delay={2}>Self-evolution with an exam gate</Eyebrow>
        <div
          style={{
            marginTop: 20,
            fontSize: 40,
            fontWeight: 500,
            color: color.inkSoft,
            opacity: ramp(frame, 10, 22),
          }}
        >
          It rewrites its own prompt —{' '}
          <span style={{color: color.amber}}>then has to earn the change.</span>
        </div>
      </div>

      <StageHead i={0} n="01" title="Rewrite from run history" />
      <StageHead i={1} n="02" title="Held-out exam" />
      <StageHead i={2} n="03" title="Your inbox" />

      {/* Connectors between the three stages */}
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {[0, 1].map((i) => {
          const p = ramp(frame, 120 + i * 78, 20);
          const x = colX(i) + COL_W;
          const y = TOP + H / 2;
          return (
            <g key={i} opacity={p}>
              <line
                x1={x + 8}
                y1={y}
                x2={x + 8 + (GAP - 26) * p}
                y2={y}
                stroke={color.amber}
                strokeWidth={1.5}
              />
              <polygon
                points={`${x + GAP - 10},${y} ${x + GAP - 22},${y - 6} ${x + GAP - 22},${y + 6}`}
                fill={color.amber}
                opacity={p}
              />
            </g>
          );
        })}
      </svg>

      {/* ---- 01 · rewrite ---- */}
      <Panel
        style={{
          position: 'absolute',
          left: colX(0),
          top: TOP,
          width: COL_W,
          height: H,
          padding: '24px 26px',
          opacity: ramp(frame, 22, 18),
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <Mono size={14} tone={color.muted} tracking="0.14em">
            SYSTEM PROMPT · rev 7 → 8
          </Mono>
          <Chip tone={color.amber} size={11}>
            auto
          </Chip>
        </div>

        <div style={{marginTop: 24, display: 'flex', flexDirection: 'column', gap: 12}}>
          {DIFF.map((d, i) => {
            const p = ramp(frame, d.at, 12);
            const add = d.sign === '+';
            return (
              <div
                key={i}
                style={{
                  display: 'flex',
                  gap: 12,
                  alignItems: 'flex-start',
                  opacity: p,
                  transform: `translateX(${(1 - p) * 14}px)`,
                  background: add ? `${color.green}12` : `${color.red}0f`,
                  border: `1px solid ${add ? `${color.green}2e` : `${color.red}26`}`,
                  borderRadius: 8,
                  padding: '9px 12px',
                }}
              >
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 16,
                    color: add ? color.green : color.red,
                    fontWeight: 600,
                  }}
                >
                  {d.sign}
                </span>
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 15.5,
                    lineHeight: 1.4,
                    color: add ? color.inkSoft : color.faint,
                    textDecoration: add ? 'none' : 'line-through',
                  }}
                >
                  {d.text}
                </span>
              </div>
            );
          })}
        </div>

        <div
          style={{
            position: 'absolute',
            left: 26,
            right: 26,
            bottom: 22,
            borderTop: `1px solid ${color.rule}`,
            paddingTop: 14,
          }}
        >
          <Mono size={14} tone={color.faint}>
            drawn from 214 past runs · traces + LLM-judge evals
          </Mono>
        </div>
      </Panel>

      {/* ---- 02 · exam ---- */}
      <Panel
        style={{
          position: 'absolute',
          left: colX(1),
          top: TOP,
          width: COL_W,
          height: H,
          padding: '24px 26px',
          opacity: ramp(frame, 118, 18),
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <Mono size={14} tone={color.muted} tracking="0.14em">
            HELD-OUT TASKS · n=38
          </Mono>
          <Chip tone={verdict > 0.4 ? color.green : color.mutedDim} size={11}>
            {verdict > 0.4 ? 'pass' : 'scoring'}
          </Chip>
        </div>

        <div style={{marginTop: 26, display: 'flex', flexDirection: 'column', gap: 22}}>
          {DIMS.map((d, i) => {
            const start = 132 + i * 11;
            const inc = countTo(frame, start, 14, d.incumbent);
            const cand = countTo(frame, start + 12, 20, d.candidate);
            const shown = ramp(frame, start, 10);
            return (
              <div key={d.name} style={{opacity: shown}}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                    marginBottom: 9,
                  }}
                >
                  <Mono size={15} tone={color.inkSoft}>
                    {d.name}
                  </Mono>
                  <Mono size={15} tone={color.green} weight={600}>
                    {cand.toFixed(2)}
                    <span style={{color: color.faint, fontWeight: 400}}>
                      {' '}
                      / {d.incumbent.toFixed(2)}
                    </span>
                  </Mono>
                </div>
                <div
                  style={{
                    position: 'relative',
                    height: 10,
                    borderRadius: 6,
                    background: color.panelHi,
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      width: `${inc * 100}%`,
                      background: color.faint,
                    }}
                  />
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      width: `${cand * 100}%`,
                      background: `linear-gradient(90deg, ${color.amber}, ${color.green})`,
                    }}
                  />
                  {/* Incumbent watermark, drawn over the candidate fill — the
                      grey bar underneath is invisible whenever the candidate
                      wins, which is the only case that matters here. */}
                  <div
                    style={{
                      position: 'absolute',
                      top: 0,
                      bottom: 0,
                      left: `${inc * 100}%`,
                      width: 2,
                      background: color.void,
                      opacity: 0.75,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div
          style={{
            position: 'absolute',
            left: 26,
            right: 26,
            bottom: 22,
            opacity: verdict,
          }}
        >
          <div
            style={{
              borderTop: `1px solid ${color.rule}`,
              paddingTop: 14,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span style={{color: color.green, fontSize: 18}}>✓</span>
            <Mono size={14} tone={color.green}>
              no dimension below incumbent
            </Mono>
          </div>
        </div>
      </Panel>

      {/* ---- 03 · proposal ---- */}
      <Panel
        tone={promoted > 0.5 ? color.green : color.amber}
        glow={0.5 + promoted * 0.4}
        style={{
          position: 'absolute',
          left: colX(2),
          top: TOP,
          width: COL_W,
          height: H,
          padding: '24px 26px',
          opacity: Math.min(1, proposal * 1.4),
          transform: `translateY(${(1 - proposal) * 26}px)`,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
          <Mono size={14} tone={color.amberSoft} tracking="0.14em">
            PROPOSAL · Research Analyst
          </Mono>
          <Chip tone={promoted > 0.5 ? color.green : color.amber} size={11} filled={promoted > 0.5}>
            {promoted > 0.5 ? 'promoted' : 'awaiting you'}
          </Chip>
        </div>

        <div style={{marginTop: 26, fontSize: 26, fontWeight: 500, color: color.ink, lineHeight: 1.3}}>
          Prompt revision passed the gate on all four dimensions.
        </div>

        <div style={{marginTop: 22, display: 'flex', flexDirection: 'column', gap: 10}}>
          {[
            ['candidate', 'rev 8'],
            ['incumbent', 'rev 7'],
            ['margin', '+0.13 avg'],
            ['regressions', 'none'],
          ].map(([k, v]) => (
            <div
              key={k}
              style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}
            >
              <Mono size={15} tone={color.mutedDim}>
                {k}
              </Mono>
              <Mono size={15} tone={color.inkSoft}>
                {v}
              </Mono>
            </div>
          ))}
        </div>

        <div
          style={{
            position: 'absolute',
            left: 26,
            right: 26,
            bottom: 24,
            display: 'flex',
            gap: 14,
          }}
        >
          <div
            style={{
              flex: 1,
              height: 54,
              borderRadius: 10,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background:
                promoted > 0.5
                  ? color.green
                  : `linear-gradient(180deg, ${color.amberHi}, ${color.amber})`,
              color: color.void,
              fontWeight: 700,
              fontSize: 18,
              letterSpacing: '0.04em',
              transform: `scale(${press})`,
              boxShadow: clicked ? 'none' : `0 0 30px ${color.amber}55`,
            }}
          >
            {promoted > 0.5 ? 'PROMOTED' : 'PROMOTE'}
          </div>
          <div
            style={{
              width: 150,
              height: 54,
              borderRadius: 10,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: `1px solid ${color.rule}`,
              color: color.muted,
              fontSize: 17,
              opacity: promoted > 0.5 ? 0.35 : 1,
            }}
          >
            Dismiss
          </div>
        </div>
      </Panel>

      {/* Cursor */}
      {cursorT > 0 && frame < 292 ? (
        <svg
          width={26}
          height={30}
          viewBox="0 0 26 30"
          style={{
            position: 'absolute',
            left: cursorX,
            top: cursorY,
            filter: 'drop-shadow(0 3px 6px rgba(0,0,0,0.7))',
          }}
        >
          <path
            d="M2 2 L2 22 L7.5 17 L11 25.5 L15 23.5 L11.5 15.5 L19 15 Z"
            fill={color.ink}
            stroke={color.void}
            strokeWidth={1.4}
          />
        </svg>
      ) : null}

      {/* Click ripple */}
      {clicked && frame < 282 ? (
        <div
          style={{
            position: 'absolute',
            left: BTN.x - 60,
            top: BTN.y - 60,
            width: 120,
            height: 120,
            borderRadius: 999,
            border: `2px solid ${color.amberSoft}`,
            opacity: interpolate(frame, [262, 282], [0.85, 0]),
            transform: `scale(${interpolate(frame, [262, 282], [0.25, 1.5])})`,
          }}
        />
      ) : null}

      <div
        style={{
          position: 'absolute',
          left: 130,
          bottom: 128,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          opacity: ramp(frame, 200, 22),
        }}
      >
        <span style={{width: 40, height: 1, background: color.amberDeep}} />
        <Mono size={19} tone={color.muted}>
          Fail → discarded, you never see it. Pass → a readable diff. It lands
          only when you click Promote.
        </Mono>
      </div>
    </Plate>
  );
};
