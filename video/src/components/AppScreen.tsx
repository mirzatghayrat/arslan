import React from 'react';
import {interpolate} from 'remotion';
import {Mark} from './Mark';
import {SCREEN} from './MacBook';
import {light} from '../lightTheme';
import {font} from '../theme';

/**
 * The Arslan client, laid out at the laptop's native screen size so it can be
 * rendered live inside the 3D world. Structure follows the real client —
 * sidebar rail, workspace header, content — rather than being invented for the
 * film, so the shots show something the product actually looks like.
 */

const RAIL = 300;
const HEAD = 74;

const NAV = [
  'Host session',
  'Spawns ledger',
  'Capabilities',
  'Second brain',
  'Evolution inbox',
  'Diagnostics',
];

const ramp = (frame: number, start: number, len: number) =>
  interpolate(frame, [start, start + len], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

export const Shell: React.FC<{
  active: string;
  title: string;
  children: React.ReactNode;
}> = ({active, title, children}) => (
  <div
    style={{
      width: SCREEN.w,
      height: SCREEN.h,
      display: 'flex',
      background: light.background,
      fontFamily: font.sans,
      color: light.ink,
    }}
  >
    {/* rail */}
    <div
      style={{
        width: RAIL,
        flexShrink: 0,
        borderRight: `1px solid ${light.border}`,
        background: '#F7F9FB',
        padding: '22px 18px',
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '0 8px 20px'}}>
        <Mark frame={140} size={30} tone={light.primary} />
        <div>
          <div style={{fontSize: 19, fontWeight: 650, letterSpacing: '-0.01em'}}>Arslan</div>
          <div style={{fontFamily: font.mono, fontSize: 10.5, color: light.subtle, letterSpacing: '0.1em'}}>
            ORCHESTRATOR
          </div>
        </div>
      </div>
      {NAV.map((n) => {
        const on = n === active;
        return (
          <div
            key={n}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '11px 12px',
              borderRadius: 9,
              marginBottom: 3,
              background: on ? `${light.primary}18` : 'transparent',
              color: on ? light.primary : light.muted,
              fontSize: 16,
              fontWeight: on ? 600 : 450,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: 7,
                background: on ? light.primary : light.borderStrong,
                flexShrink: 0,
              }}
            />
            {n}
          </div>
        );
      })}
    </div>

    {/* content */}
    <div style={{flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column'}}>
      <div
        style={{
          height: HEAD,
          flexShrink: 0,
          borderBottom: `1px solid ${light.border}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 30px',
          gap: 14,
          background: light.surface,
        }}
      >
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 11.5,
            letterSpacing: '0.18em',
            color: light.subtle,
            textTransform: 'uppercase',
          }}
        >
          {title}
        </span>
        <span style={{flex: 1}} />
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 11.5,
            color: light.success,
            letterSpacing: '0.1em',
          }}
        >
          ● LOCAL
        </span>
      </div>
      <div style={{flex: 1, minHeight: 0, position: 'relative'}}>{children}</div>
    </div>
  </div>
);

/* ------------------------------------------------------------------ */

const Bubble: React.FC<{me?: boolean; children: React.ReactNode; o: number}> = ({
  me,
  children,
  o,
}) => (
  <div
    style={{
      alignSelf: me ? 'flex-end' : 'flex-start',
      maxWidth: 660,
      background: me ? `${light.primary}14` : light.surface,
      border: `1px solid ${me ? `${light.primary}33` : light.border}`,
      borderRadius: 16,
      [me ? 'borderTopRightRadius' : 'borderTopLeftRadius']: 5,
      padding: '15px 19px',
      fontSize: 19,
      lineHeight: 1.5,
      opacity: o,
      transform: `translateY(${(1 - o) * 10}px)`,
    }}
  >
    {children}
  </div>
);

/** The host thread answering, with the spawns it fanned out to. */
export const ScreenThread: React.FC<{frame: number}> = ({frame}) => (
  <Shell active="Host session" title="Host session · one thread">
    <div style={{padding: '34px 40px', display: 'flex', flexDirection: 'column', gap: 18}}>
      <Bubble me o={ramp(frame, 0, 16)}>
        Chart last quarter against the plan and tell me what moved.
      </Bubble>

      <div style={{display: 'flex', gap: 12, opacity: ramp(frame, 20, 16)}}>
        {[
          ['Research Analyst', 'fetch · 11 sources'],
          ['Data & Chart Analyst', 'python · sandboxed'],
          ['Coding Assistant', 'diff · 2 files'],
        ].map(([n, s], i) => (
          <div
            key={n}
            style={{
              flex: 1,
              background: light.surface,
              border: `1px solid ${light.border}`,
              borderRadius: 13,
              padding: '14px 16px',
              opacity: ramp(frame, 22 + i * 7, 14),
              transform: `translateY(${(1 - ramp(frame, 22 + i * 7, 14)) * 12}px)`,
            }}
          >
            <div style={{display: 'flex', alignItems: 'center', gap: 9}}>
              <span style={{width: 9, height: 9, borderRadius: 9, background: light.primary}} />
              <span style={{fontSize: 15.5, fontWeight: 600}}>{n}</span>
            </div>
            <div
              style={{
                marginTop: 9,
                fontFamily: font.mono,
                fontSize: 12.5,
                color: light.muted,
              }}
            >
              {s}
            </div>
            <div
              style={{
                marginTop: 11,
                height: 4,
                borderRadius: 4,
                background: light.border,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${ramp(frame, 34 + i * 8, 42) * 100}%`,
                  background: light.primary,
                }}
              />
            </div>
          </div>
        ))}
      </div>

      <Bubble o={ramp(frame, 78, 18)}>
        Revenue tracked <b>+8.4%</b> to plan. The whole gap is EMEA renewals — chart
        and the query are attached.
      </Bubble>

      <div style={{opacity: ramp(frame, 92, 18)}}>
        <div
          style={{
            width: 660,
            height: 230,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 14,
            padding: 18,
            display: 'flex',
            alignItems: 'flex-end',
            gap: 12,
          }}
        >
          {[0.42, 0.55, 0.48, 0.7, 0.63, 0.82, 0.74, 0.95].map((v, i) => (
            <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%'}}>
              <div
                style={{
                  height: `${v * 100 * ramp(frame, 96 + i * 3, 20)}%`,
                  borderRadius: 6,
                  background: i > 5 ? light.primary : `${light.primary}55`,
                }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  </Shell>
);

/** The evolution inbox: a candidate that passed its exam, waiting on you. */
export const ScreenPromotion: React.FC<{frame: number}> = ({frame}) => {
  const dims: [string, number, number][] = [
    ['faithfulness', 0.71, 0.86],
    ['task completion', 0.64, 0.81],
    ['tool discipline', 0.78, 0.83],
    ['honesty', 0.82, 0.82],
  ];
  const promoted = frame > 118;
  return (
    <Shell active="Evolution inbox" title="Evolution inbox · 1 proposal">
      <div style={{padding: '34px 40px', display: 'flex', gap: 28}}>
        <div
          style={{
            flex: 1,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 15,
            padding: '22px 24px',
            opacity: ramp(frame, 0, 16),
          }}
        >
          <div style={{fontFamily: font.mono, fontSize: 12.5, color: light.subtle, letterSpacing: '0.14em'}}>
            HELD-OUT EXAM · n=38
          </div>
          <div style={{marginTop: 20, display: 'flex', flexDirection: 'column', gap: 17}}>
            {dims.map(([n, inc, cand], i) => {
              const v = interpolate(frame, [14 + i * 8, 44 + i * 8], [0, cand], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div key={n}>
                  <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 7}}>
                    <span style={{fontSize: 15, color: light.muted}}>{n}</span>
                    <span style={{fontFamily: font.mono, fontSize: 14, color: light.success, fontWeight: 600}}>
                      {v.toFixed(2)}
                    </span>
                  </div>
                  <div style={{position: 'relative', height: 9, borderRadius: 6, background: '#EDF0F4', overflow: 'hidden'}}>
                    <div
                      style={{
                        position: 'absolute',
                        inset: 0,
                        width: `${v * 100}%`,
                        background: `linear-gradient(90deg, ${light.primary}, ${light.success})`,
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        top: 0,
                        bottom: 0,
                        left: `${inc * 100}%`,
                        width: 2,
                        background: light.surface,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div
          style={{
            width: 420,
            flexShrink: 0,
            background: light.surface,
            border: `1.5px solid ${promoted ? light.success : light.primary}`,
            borderRadius: 15,
            padding: '22px 24px',
            boxShadow: `0 14px 40px ${light.primary}22`,
            opacity: ramp(frame, 62, 18),
            transform: `translateY(${(1 - ramp(frame, 62, 18)) * 16}px)`,
          }}
        >
          <div style={{fontFamily: font.mono, fontSize: 12.5, color: light.subtle, letterSpacing: '0.14em'}}>
            PROPOSAL · Research Analyst
          </div>
          <div style={{marginTop: 14, fontSize: 22, fontWeight: 600, lineHeight: 1.32}}>
            Prompt rev 8 passed on all four dimensions.
          </div>
          <div style={{marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8}}>
            {[['margin', '+0.13 avg'], ['regressions', 'none']].map(([k, v]) => (
              <div key={k} style={{display: 'flex', justifyContent: 'space-between', fontFamily: font.mono, fontSize: 14}}>
                <span style={{color: light.subtle}}>{k}</span>
                <span style={{color: light.ink}}>{v}</span>
              </div>
            ))}
          </div>
          <div
            style={{
              marginTop: 20,
              height: 50,
              borderRadius: 11,
              background: promoted ? light.success : light.primary,
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 17,
              fontWeight: 700,
              letterSpacing: '0.02em',
              transform: `scale(${frame >= 116 && frame < 122 ? 0.96 : 1})`,
            }}
          >
            {promoted ? 'PROMOTED' : 'Promote'}
          </div>
          <div style={{marginTop: 12, fontSize: 13.5, color: light.subtle, textAlign: 'center'}}>
            Nothing ships until you press it
          </div>
        </div>
      </div>
    </Shell>
  );
};

/** The second brain: notes that formed on their own, with a time axis. */
export const ScreenBrain: React.FC<{frame: number}> = ({frame}) => {
  const nodes = [
    {x: 470, y: 300, r: 20, n: '[[Q3 plan]]'},
    {x: 300, y: 190, r: 13, n: '[[EMEA]]'},
    {x: 650, y: 190, r: 13, n: '[[pricing]]'},
    {x: 640, y: 420, r: 13, n: '[[churn]]'},
    {x: 300, y: 420, r: 13, n: '[[warehouse]]'},
    {x: 160, y: 300, r: 9, n: ''},
    {x: 790, y: 300, r: 9, n: ''},
    {x: 470, y: 120, r: 9, n: ''},
    {x: 470, y: 490, r: 9, n: ''},
  ];
  const edges: [number, number][] = [
    [0, 1], [0, 2], [0, 3], [0, 4], [1, 5], [4, 5], [2, 6], [3, 6], [0, 7], [0, 8],
  ];
  return (
    <Shell active="Second brain" title="Second brain · 214 notes">
      <div style={{position: 'absolute', inset: 0, padding: '20px 40px'}}>
        <svg width={900} height={580} style={{position: 'absolute', left: 40, top: 20}}>
          {edges.map(([a, b], i) => (
            <line
              key={i}
              x1={nodes[a].x}
              y1={nodes[a].y}
              x2={nodes[b].x}
              y2={nodes[b].y}
              stroke={light.info}
              strokeWidth={1.4}
              opacity={0.3 * ramp(frame, 6 + i * 3, 18)}
            />
          ))}
          {nodes.map((nd, i) => (
            <circle
              key={i}
              cx={nd.x}
              cy={nd.y}
              r={nd.r * ramp(frame, i * 4, 16)}
              fill={nd.n ? light.primary : light.info}
            />
          ))}
        </svg>
        {nodes.filter((n) => n.n).map((nd, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: 40 + nd.x + nd.r + 10,
              top: 20 + nd.y - 11,
              fontFamily: font.mono,
              fontSize: 14,
              color: light.muted,
              opacity: ramp(frame, 24 + i * 4, 16),
            }}
          >
            {nd.n}
          </div>
        ))}

        <div
          style={{
            position: 'absolute',
            right: 40,
            top: 34,
            width: 430,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 15,
            padding: '20px 22px',
            opacity: ramp(frame, 40, 18),
          }}
        >
          <div style={{fontFamily: font.mono, fontSize: 12, color: light.subtle, letterSpacing: '0.14em'}}>
            BELIEF · WITH A TIME AXIS
          </div>
          <div style={{marginTop: 13, fontSize: 19, lineHeight: 1.4}}>
            EMEA renewals slip roughly two weeks past close.
          </div>
          {[['took effect', '2026-03-14'], ['superseded', '2026-06-02']].map(([k, v]) => (
            <div key={k} style={{marginTop: 9, display: 'flex', justifyContent: 'space-between', fontFamily: font.mono, fontSize: 13.5}}>
              <span style={{color: light.subtle}}>{k}</span>
              <span>{v}</span>
            </div>
          ))}
        </div>

        {/* time scrubber */}
        <div style={{position: 'absolute', left: 40, right: 40, bottom: 42, opacity: ramp(frame, 60, 18)}}>
          <div style={{position: 'relative', height: 3, background: light.border, borderRadius: 3}}>
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                bottom: 0,
                width: `${interpolate(frame, [70, 150], [100, 44], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}%`,
                background: light.primary,
                borderRadius: 3,
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: -7,
                left: `${interpolate(frame, [70, 150], [100, 44], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}%`,
                width: 17,
                height: 17,
                marginLeft: -8,
                borderRadius: 17,
                background: light.primary,
              }}
            />
          </div>
          <div style={{marginTop: 12, display: 'flex', justifyContent: 'space-between', fontFamily: font.mono, fontSize: 12, color: light.subtle}}>
            <span>FIRST BELIEF</span>
            <span>NOW</span>
          </div>
        </div>
      </div>
    </Shell>
  );
};
