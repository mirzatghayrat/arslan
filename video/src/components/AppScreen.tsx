import React from 'react';
import {interpolate} from 'remotion';
import {Mark} from './Mark';
import {SCREEN} from './Mockup';
import {light} from '../lightTheme';
import {font} from '../theme';

/**
 * The Arslan client, laid out at the screen's own size so it can be composited
 * live onto a photographed display. Structure follows the real client — rail,
 * workspace header, content — rather than being invented for the film, so the
 * shots show something the product actually looks like.
 *
 * Every view fills its content box. An earlier pass positioned things at fixed
 * pixel offsets tuned for a taller screen, which left the bottom third of the
 * display empty in every shot: on a real machine that reads as an app that has
 * not finished loading. The rule here is that the piece carrying the idea — the
 * chart, the exam, the graph — takes `flex: 1` and absorbs whatever height is
 * left, so the layout is correct at whatever size the glass turns out to be.
 */

const RAIL = 320;
const HEAD = 78;

/** What each view gets to fill. */
export const CONTENT = {w: SCREEN.w - RAIL, h: SCREEN.h - HEAD};

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

const rise = (frame: number, start: number, len: number, px = 14) => ({
  opacity: ramp(frame, start, len),
  transform: `translateY(${(1 - ramp(frame, start, len)) * px}px)`,
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
        background: '#F6F8FA',
        padding: '24px 18px',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{display: 'flex', alignItems: 'center', gap: 13, padding: '0 8px 24px'}}>
        <Mark frame={140} size={34} tone={light.primary} />
        <div>
          <div style={{fontSize: 22, fontWeight: 650, letterSpacing: '-0.01em'}}>Arslan</div>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 11.5,
              color: light.subtle,
              letterSpacing: '0.1em',
            }}
          >
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
              gap: 13,
              padding: '13px 13px',
              borderRadius: 10,
              marginBottom: 4,
              background: on ? `${light.primary}18` : 'transparent',
              color: on ? light.primary : light.muted,
              fontSize: 18,
              fontWeight: on ? 600 : 450,
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 8,
                background: on ? light.primary : light.borderStrong,
                flexShrink: 0,
              }}
            />
            {n}
          </div>
        );
      })}

      <div style={{flex: 1}} />
      <div
        style={{
          padding: '14px 13px 4px',
          borderTop: `1px solid ${light.border}`,
          fontFamily: font.mono,
          fontSize: 12.5,
          color: light.subtle,
          lineHeight: 1.7,
        }}
      >
        <div>models · local</div>
        <div>egress · proxied</div>
      </div>
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
          padding: '0 34px',
          gap: 14,
          background: light.surface,
        }}
      >
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 13,
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
            fontSize: 13,
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

const Bubble: React.FC<{
  me?: boolean;
  children: React.ReactNode;
  o: number;
  max?: number;
}> = ({me, children, o, max = 760}) => (
  <div
    style={{
      alignSelf: me ? 'flex-end' : 'flex-start',
      maxWidth: max,
      background: me ? `${light.primary}14` : light.surface,
      border: `1px solid ${me ? `${light.primary}33` : light.border}`,
      borderRadius: 18,
      [me ? 'borderTopRightRadius' : 'borderTopLeftRadius']: 6,
      padding: '18px 22px',
      fontSize: 22,
      lineHeight: 1.5,
      opacity: o,
      transform: `translateY(${(1 - o) * 10}px)`,
    }}
  >
    {children}
  </div>
);

/**
 * The host thread answering, with the spawns it fanned out to.
 *
 * `extended` adds a second exchange after the chart. The 30-second cut does not
 * use it: that film is on this view for five seconds and the chart is the last
 * thing it has time to say. The 60 holds here for seven, and a screen that
 * finishes building and then sits still for four seconds reads as a screenshot
 * no matter what the camera is doing. The follow-up is also the more honest
 * picture of the product — the point of one thread is that you can keep asking.
 *
 * The pair grows in by height rather than fading in at full size, so the chart
 * above gives up its space smoothly instead of jumping.
 */
export const ScreenThread: React.FC<{frame: number; extended?: boolean}> = ({
  frame,
  extended = false,
}) => {
  const bars = [0.42, 0.55, 0.48, 0.7, 0.63, 0.82, 0.74, 0.95];
  const follow = ramp(frame, 116, 30);
  return (
    <Shell active="Host session" title="Host session · one thread">
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '30px 34px 26px',
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <Bubble me o={ramp(frame, 0, 16)}>
          Chart last quarter against the plan and tell me what moved.
        </Bubble>

        <div style={{display: 'flex', gap: 14, flexShrink: 0}}>
          {[
            ['Research Analyst', 'fetch · 11 sources'],
            ['Data & Chart Analyst', 'python · sandboxed'],
            ['Coding Assistant', 'diff · 2 files'],
          ].map(([n, s], i) => (
            <div
              key={n}
              style={{
                flex: 1,
                minWidth: 0,
                background: light.surface,
                border: `1px solid ${light.border}`,
                borderRadius: 14,
                padding: '16px 18px',
                ...rise(frame, 12 + i * 6, 14, 12),
              }}
            >
              <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
                <span
                  style={{width: 10, height: 10, borderRadius: 10, background: light.primary}}
                />
                <span style={{fontSize: 17.5, fontWeight: 600}}>{n}</span>
              </div>
              <div
                style={{
                  marginTop: 10,
                  fontFamily: font.mono,
                  fontSize: 14,
                  color: light.muted,
                }}
              >
                {s}
              </div>
              <div
                style={{
                  marginTop: 13,
                  height: 5,
                  borderRadius: 5,
                  background: light.border,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${ramp(frame, 22 + i * 7, 40) * 100}%`,
                    background: light.primary,
                  }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* The answer.
            An earlier pass put the reply in its own bubble above a separate
            chart card. On the angled mock-ups that read as clutter: five
            full-width bands stacked on a plane sloping away from the lens, none
            of them the obvious place to look, in a shot that is on screen for
            four seconds. Folding the sentence into the chart's own header
            leaves the view with one thing to say and one place to say it. */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 16,
            padding: '22px 26px',
            display: 'flex',
            flexDirection: 'column',
            ...rise(frame, 44, 20, 16),
          }}
        >
          <div style={{fontSize: 22, lineHeight: 1.45, flexShrink: 0, maxWidth: 900}}>
            Revenue tracked <b>+8.4%</b> to plan. The whole gap is EMEA renewals.
          </div>
          <div
            style={{
              marginTop: 12,
              display: 'flex',
              alignItems: 'baseline',
              gap: 14,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                fontFamily: font.mono,
                fontSize: 13.5,
                color: light.subtle,
                letterSpacing: '0.1em',
              }}
            >
              Q3 ACTUAL VS PLAN · SAMPLE DATA
            </span>
            <span style={{flex: 1}} />
            <span style={{fontFamily: font.mono, fontSize: 15, color: light.success}}>+8.4%</span>
          </div>
          <div
            style={{
              flex: 1,
              minHeight: 0,
              marginTop: 16,
              display: 'flex',
              alignItems: 'flex-end',
              gap: 14,
            }}
          >
            {bars.map((v, i) => (
              <div
                key={i}
                style={{
                  flex: 1,
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'flex-end',
                }}
              >
                <div
                  style={{
                    height: `${v * 100 * ramp(frame, 58 + i * 3, 22)}%`,
                    borderRadius: 7,
                    background: i > 5 ? light.primary : `${light.primary}55`,
                  }}
                />
              </div>
            ))}
          </div>
        </div>

        {extended ? (
          <div
            style={{
              flexShrink: 0,
              maxHeight: follow * 250,
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              gap: 18,
            }}
          >
            <Bubble me o={ramp(frame, 122, 16)} max={620}>
              Which renewals, and who owns them?
            </Bubble>
            <Bubble o={ramp(frame, 156, 20)} max={880}>
              Three: <b>Northwind</b>, <b>Acorn Health</b>, <b>Lumen</b> — all with
              Dana. I put the account notes in your second brain.
            </Bubble>
          </div>
        ) : null}
      </div>
    </Shell>
  );
};

/** The evolution inbox: a candidate that passed its exam, waiting on you. */
export const ScreenPromotion: React.FC<{frame: number}> = ({frame}) => {
  const dims: [string, number, number][] = [
    ['faithfulness', 0.71, 0.86],
    ['task completion', 0.64, 0.81],
    ['tool discipline', 0.78, 0.83],
    ['honesty', 0.82, 0.82],
  ];
  const promoted = frame > 168;
  return (
    <Shell active="Evolution inbox" title="Evolution inbox · 1 proposal">
      {/* The pair sizes to its content and is centred, rather than stretched to
          the full height of the display. Stretched, both panels grew a dead
          band through their middle that read as an app still loading; centred,
          the same space becomes margin above and below and reads as layout. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '30px 34px',
          display: 'flex',
          alignItems: 'center',
        }}
      >
      <div style={{display: 'flex', gap: 26, width: '100%', alignItems: 'stretch'}}>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 16,
            padding: '24px 28px',
            display: 'flex',
            flexDirection: 'column',
            opacity: ramp(frame, 0, 16),
          }}
        >
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 13.5,
              color: light.subtle,
              letterSpacing: '0.14em',
              flexShrink: 0,
            }}
          >
            HELD-OUT EXAM · n=38 · SAMPLE DATA
          </div>
          {/* Spread over the full height with `space-evenly` these four read as
              four unrelated bars floating in a panel. Grouped at the top with a
              real gap, they read as one table — and the space that frees up
              goes to saying what the exam IS, which is the part of the gate
              that actually needs explaining. */}
          <div
            style={{
              marginTop: 24,
              display: 'flex',
              flexDirection: 'column',
              gap: 30,
            }}
          >
            {dims.map(([n, inc, cand], i) => {
              const v = interpolate(frame, [14 + i * 8, 44 + i * 8], [0, cand], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div key={n}>
                  <div
                    style={{display: 'flex', justifyContent: 'space-between', marginBottom: 9}}
                  >
                    <span style={{fontSize: 17.5, color: light.muted}}>{n}</span>
                    <span
                      style={{
                        fontFamily: font.mono,
                        fontSize: 16,
                        color: light.success,
                        fontWeight: 600,
                      }}
                    >
                      {v.toFixed(2)}
                    </span>
                  </div>
                  <div
                    style={{
                      position: 'relative',
                      height: 11,
                      borderRadius: 7,
                      background: '#EDF0F4',
                      overflow: 'hidden',
                    }}
                  >
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
                        width: 2.5,
                        background: light.surface,
                      }}
                    />
                  </div>
                  <div
                    style={{
                      marginTop: 7,
                      fontFamily: font.mono,
                      fontSize: 12.5,
                      color: light.subtle,
                    }}
                  >
                    incumbent {inc.toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>

          <div
            style={{
              marginTop: 30,
              borderTop: `1px solid ${light.border}`,
              paddingTop: 18,
              fontSize: 16.5,
              color: light.muted,
              lineHeight: 1.5,
              opacity: ramp(frame, 50, 20),
            }}
          >
            The exam is held out. The rewrite never sees these cases, so a
            candidate cannot be tuned into passing them.
          </div>
        </div>

        <div
          style={{
            width: 440,
            flexShrink: 0,
            background: light.surface,
            border: `1.5px solid ${promoted ? light.success : light.primary}`,
            borderRadius: 16,
            padding: '24px 26px',
            boxShadow: `0 14px 40px ${light.primary}22`,
            display: 'flex',
            flexDirection: 'column',
            ...rise(frame, 62, 18, 16),
          }}
        >
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 13.5,
              color: light.subtle,
              letterSpacing: '0.14em',
            }}
          >
            PROPOSAL · Research Analyst
          </div>
          <div style={{marginTop: 16, fontSize: 25, fontWeight: 600, lineHeight: 1.32}}>
            Prompt rev 8 passed on all four dimensions.
          </div>
          <div style={{marginTop: 18, display: 'flex', flexDirection: 'column', gap: 10}}>
            {[
              ['margin', '+0.13 avg'],
              ['regressions', 'none'],
              ['past runs', '214'],
            ].map(([k, v]) => (
              <div
                key={k}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontFamily: font.mono,
                  fontSize: 15,
                }}
              >
                <span style={{color: light.subtle}}>{k}</span>
                <span style={{color: light.ink}}>{v}</span>
              </div>
            ))}
          </div>

          {/* What is actually being proposed. Without it the panel is a score
              and a button, and the shot never says that the thing under review
              is a prompt the host rewrote. */}
          <div
            style={{
              marginTop: 20,
              border: `1px solid ${light.border}`,
              borderRadius: 11,
              overflow: 'hidden',
              fontFamily: font.mono,
              fontSize: 14,
              lineHeight: 1.65,
              opacity: ramp(frame, 76, 18),
            }}
          >
            <div
              style={{
                padding: '9px 13px',
                background: '#F6F8FA',
                color: light.subtle,
                letterSpacing: '0.1em',
                fontSize: 12,
              }}
            >
              PROMPT DIFF · REV 7 → 8
            </div>
            <div style={{padding: '10px 13px', background: '#FDF3EC', color: '#9A3412'}}>
              − cite sources where possible
            </div>
            <div style={{padding: '10px 13px', background: '#ECFDF5', color: '#065F46'}}>
              + cite a source for every claim, or say it is unsourced
            </div>
          </div>

          <div
            style={{
              marginTop: 26,
              height: 58,
              borderRadius: 12,
              background: promoted ? light.success : light.primary,
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 19,
              fontWeight: 700,
              letterSpacing: '0.02em',
              transform: `scale(${frame >= 166 && frame < 172 ? 0.96 : 1})`,
            }}
          >
            {promoted ? 'PROMOTED' : 'Promote'}
          </div>
          <div
            style={{
              marginTop: 14,
              fontSize: 15,
              color: light.subtle,
              textAlign: 'center',
            }}
          >
            Nothing ships until you press it
          </div>
        </div>
      </div>
      </div>
    </Shell>
  );
};

/** The second brain: notes that formed on their own, with a time axis. */
export const ScreenBrain: React.FC<{frame: number}> = ({frame}) => {
  /* Normalised so the graph fills whatever the glass turns out to be. */
  const nodes = [
    {x: 0.46, y: 0.5, r: 22, n: '[[Q3 plan]]'},
    {x: 0.26, y: 0.28, r: 14, n: '[[EMEA]]'},
    {x: 0.68, y: 0.28, r: 14, n: '[[pricing]]'},
    {x: 0.67, y: 0.74, r: 14, n: '[[churn]]'},
    {x: 0.25, y: 0.74, r: 14, n: '[[warehouse]]'},
    {x: 0.09, y: 0.5, r: 10, n: ''},
    {x: 0.85, y: 0.52, r: 10, n: ''},
    {x: 0.46, y: 0.1, r: 10, n: ''},
    {x: 0.46, y: 0.9, r: 10, n: ''},
  ];
  const edges: [number, number][] = [
    [0, 1], [0, 2], [0, 3], [0, 4], [1, 5], [4, 5], [2, 6], [3, 6], [0, 7], [0, 8],
  ];

  /* The graph owns the left of the content box; the belief card sits right. */
  const PAD = 34;
  const CARD = 430;
  const box = {
    w: CONTENT.w - PAD * 2 - CARD - 26,
    h: CONTENT.h - PAD * 2 - 96,
  };
  const at = (n: {x: number; y: number}) => ({x: n.x * box.w, y: n.y * box.h});
  const scrub = interpolate(frame, [70, 150], [100, 44], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <Shell active="Second brain" title="Second brain · 214 notes">
      <div style={{position: 'absolute', inset: 0, padding: PAD}}>
        <svg width={box.w} height={box.h} style={{position: 'absolute', left: PAD, top: PAD}}>
          {edges.map(([a, b], i) => (
            <line
              key={i}
              x1={at(nodes[a]).x}
              y1={at(nodes[a]).y}
              x2={at(nodes[b]).x}
              y2={at(nodes[b]).y}
              stroke={light.info}
              strokeWidth={1.6}
              opacity={0.32 * ramp(frame, 6 + i * 3, 18)}
            />
          ))}
          {nodes.map((nd, i) => (
            <circle
              key={i}
              cx={at(nd).x}
              cy={at(nd).y}
              r={nd.r * ramp(frame, i * 4, 16)}
              fill={nd.n ? light.primary : light.info}
            />
          ))}
        </svg>
        {nodes
          .filter((n) => n.n)
          .map((nd, i) => (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: PAD + at(nd).x + nd.r + 12,
                top: PAD + at(nd).y - 12,
                fontFamily: font.mono,
                fontSize: 15.5,
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
            right: PAD,
            top: PAD,
            width: CARD,
            background: light.surface,
            border: `1px solid ${light.border}`,
            borderRadius: 16,
            padding: '22px 24px',
            opacity: ramp(frame, 40, 18),
          }}
        >
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 13,
              color: light.subtle,
              letterSpacing: '0.14em',
            }}
          >
            BELIEF · WITH A TIME AXIS
          </div>
          <div style={{marginTop: 15, fontSize: 22, lineHeight: 1.4}}>
            EMEA renewals slip roughly two weeks past close.
          </div>
          {[
            ['took effect', '2026-03-14'],
            ['superseded', '2026-06-02'],
          ].map(([k, v]) => (
            <div
              key={k}
              style={{
                marginTop: 11,
                display: 'flex',
                justifyContent: 'space-between',
                fontFamily: font.mono,
                fontSize: 15,
              }}
            >
              <span style={{color: light.subtle}}>{k}</span>
              <span>{v}</span>
            </div>
          ))}
        </div>

        {/* time scrubber */}
        <div
          style={{
            position: 'absolute',
            left: PAD,
            right: PAD,
            bottom: PAD,
            opacity: ramp(frame, 60, 18),
          }}
        >
          <div style={{position: 'relative', height: 4, background: light.border, borderRadius: 4}}>
            <div
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                bottom: 0,
                width: `${scrub}%`,
                background: light.primary,
                borderRadius: 4,
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: -8,
                left: `${scrub}%`,
                width: 20,
                height: 20,
                marginLeft: -10,
                borderRadius: 20,
                background: light.primary,
              }}
            />
          </div>
          <div
            style={{
              marginTop: 14,
              display: 'flex',
              justifyContent: 'space-between',
              fontFamily: font.mono,
              fontSize: 13,
              color: light.subtle,
            }}
          >
            <span>FIRST BELIEF</span>
            <span>NOW</span>
          </div>
        </div>
      </div>
    </Shell>
  );
};

/**
 * The spawns ledger: every agent the host can hand work to, and what each one
 * is actually allowed to touch.
 *
 * Only the 60-second cut has room for this. The 30 has to assert that spawns
 * exist and move on; the 60 can show that they are a roster with capabilities
 * attached, which is the difference between "it has sub-agents" and "you raised
 * these and you decide what they hold".
 */
export const ScreenSpawns: React.FC<{frame: number}> = ({frame}) => {
  const rows: [string, string, string, boolean][] = [
    ['Research Analyst', 'fetch · browser', 'sources.md', true],
    ['Data & Chart Analyst', 'python · duckdb', 'charts.md', true],
    ['Coding Assistant', 'edit · shell', 'repo.md', true],
    ['Ops Runner', 'shell · k8s-mcp', 'runbooks.md', false],
    ['Inbox Triage', 'gmail-mcp', 'triage.md', true],
    ['Archivist', 'notes · search', 'brain.md', true],
  ];
  return (
    <Shell active="Spawns ledger" title="Spawns ledger · 6 spawns">
      <div style={{position: 'absolute', inset: 0, padding: '28px 34px', display: 'flex', flexDirection: 'column'}}>
        <div
          style={{
            display: 'flex',
            fontFamily: font.mono,
            fontSize: 12.5,
            color: light.subtle,
            letterSpacing: '0.14em',
            paddingBottom: 14,
            borderBottom: `1px solid ${light.border}`,
            flexShrink: 0,
          }}
        >
          <span style={{flex: 1.35}}>SPAWN</span>
          <span style={{flex: 1.15}}>TOOLS</span>
          <span style={{flex: 0.9}}>SKILL PACK</span>
          <span style={{width: 132, textAlign: 'right'}}>EGRESS</span>
        </div>

        <div style={{flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly'}}>
          {rows.map(([n, tools, pack, proxied], i) => (
            <div
              key={n}
              style={{
                display: 'flex',
                alignItems: 'center',
                borderBottom: i === rows.length - 1 ? 'none' : `1px solid ${light.border}`,
                paddingBottom: 16,
                paddingTop: 16,
                ...rise(frame, 6 + i * 7, 16, 10),
              }}
            >
              <span style={{flex: 1.35, display: 'flex', alignItems: 'center', gap: 12}}>
                <span style={{width: 9, height: 9, borderRadius: 9, background: light.primary, flexShrink: 0}} />
                <span style={{fontSize: 19, fontWeight: 600}}>{n}</span>
              </span>
              <span style={{flex: 1.15, fontFamily: font.mono, fontSize: 15, color: light.muted}}>{tools}</span>
              <span style={{flex: 0.9, fontFamily: font.mono, fontSize: 15, color: light.muted}}>{pack}</span>
              <span style={{width: 132, textAlign: 'right'}}>
                <span
                  style={{
                    fontFamily: font.mono,
                    fontSize: 13,
                    padding: '5px 11px',
                    borderRadius: 999,
                    background: proxied ? `${light.info}14` : '#F1F5F9',
                    color: proxied ? light.info : light.subtle,
                  }}
                >
                  {proxied ? 'proxied' : 'none'}
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </Shell>
  );
};

/**
 * Diagnostics, showing the sandbox refusing a direct connection.
 *
 * The claim this makes is the one worth making precisely: generated code has no
 * network at all, and the only route out is a proxy that holds the credentials
 * so the code never sees them. Two log lines say it better than a diagram does,
 * and unlike a diagram they look like something the product would actually
 * print.
 */
export const ScreenSafety: React.FC<{frame: number}> = ({frame}) => {
  const lines: [string, string, string][] = [
    ['run', 'sandbox start · net=none · fs=scratch', 'ok'],
    ['exec', 'charge_report.py · 84 lines · generated', 'ok'],
    ['deny', 'connect api.stripe.com:443 — no route from sandbox', 'deny'],
    ['deny', 'resolve api.stripe.com — no resolver in namespace', 'deny'],
    ['route', 'credential proxy · key held outside the sandbox', 'ok'],
    ['ok', 'GET /v1/charges 200 · 41ms · 1 of 1 allowed host', 'ok'],
    ['note', 'the generated code never saw the key', 'note'],
  ];
  const tone = {
    ok: light.success,
    deny: light.danger,
    note: light.subtle,
  } as const;

  return (
    <Shell active="Diagnostics" title="Diagnostics · sandbox">
      {/* Sized to its content and centred rather than stretched. Given
          `flex: 1` the log became a dark slab most of a display tall with seven
          short lines at the top of it, which on a warm set is the most
          conspicuous empty space in either film. */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '28px 34px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 24,
        }}
      >
        <div style={{display: 'flex', gap: 16, flexShrink: 0}}>
          {[
            ['NETWORK', 'denied', light.danger],
            ['FILESYSTEM', 'scratch only', light.warning],
            ['EGRESS', 'proxy only', light.info],
          ].map(([k, v, c], i) => (
            <div
              key={k}
              style={{
                flex: 1,
                background: light.surface,
                border: `1px solid ${light.border}`,
                borderRadius: 14,
                padding: '16px 18px',
                ...rise(frame, 4 + i * 8, 16, 12),
              }}
            >
              <div style={{fontFamily: font.mono, fontSize: 12, color: light.subtle, letterSpacing: '0.14em'}}>
                {k}
              </div>
              <div style={{marginTop: 9, fontSize: 21, fontWeight: 600, color: c as string}}>{v}</div>
            </div>
          ))}
        </div>

        <div
          style={{
            flexShrink: 0,
            background: '#0F172A',
            borderRadius: 16,
            padding: '26px 30px',
            fontFamily: font.mono,
            fontSize: 18,
            lineHeight: 2.15,
            color: '#CBD5E1',
            overflow: 'hidden',
            ...rise(frame, 26, 18, 14),
          }}
        >
          {lines.map(([tag, text, t], i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 16,
                opacity: ramp(frame, 34 + i * 13, 12),
              }}
            >
              <span style={{color: tone[t as keyof typeof tone], width: 82, flexShrink: 0}}>
                {tag}
              </span>
              <span style={{color: t === 'deny' ? '#FCA5A5' : '#CBD5E1'}}>{text}</span>
            </div>
          ))}
          <div
            style={{
              marginTop: 12,
              width: 11,
              height: 22,
              background: light.primary,
              opacity: frame > 130 && Math.floor(frame / 15) % 2 === 0 ? 1 : 0,
            }}
          />
        </div>

        <div
          style={{
            fontSize: 17,
            color: light.muted,
            lineHeight: 1.5,
            maxWidth: 940,
            opacity: ramp(frame, 140, 22),
          }}
        >
          Generated code runs with no network at all. The credential proxy is
          the only route out, and it holds the key — so a leak has nothing to
          leak.
        </div>
      </div>
    </Shell>
  );
};
