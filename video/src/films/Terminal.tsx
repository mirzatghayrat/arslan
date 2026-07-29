import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {font} from '../theme';

/**
 * FILM 1 of 4 — "CLI".
 *
 * Dark, monospace, no photography, no chrome. The whole film happens inside a
 * terminal and a TUI, on the assumption that the audience for a local-first
 * agent orchestrator lives in one. It is the only cut of the four with no
 * product screenshot in it at all: the argument is that Arslan's interface is
 * text, and text is what the film is made of.
 *
 * Shot vocabulary, from the shotcraft library:
 *   - `typewriter-moves` A — the command is the fuse. 2f/char, square-wave
 *     block cursor, and on Enter a 6f crash zoom to 3.2x into a hard cut. Not
 *     a dissolve: a dissolve would break the cause-and-effect the whole open
 *     rests on.
 *   - `ai-stream-response` — the summary lands first and is allowed to be read
 *     before any evidence arrives, so the shot says "conclusion, then working"
 *     rather than "log spam".
 *   - `command-palette-summon` — the world dims and blurs, the palette drops
 *     past its mark and comes back, candidates stagger, typing collapses the
 *     list by height rather than fading it.
 *   - `beat-cut-moves` A — the sprint: five hard cuts at 16/12/8/6/4 frames.
 *     Halving, not decreasing linearly, or it does not read as acceleration.
 */

const C = {
  bg: '#08090B',
  panel: '#0E1013',
  rule: '#1E2228',
  ruleHi: '#2C323A',
  ink: '#E6E9EE',
  dim: '#7C848F',
  faint: '#4A515B',
  amber: '#F2A03C',
  green: '#4ADE80',
  red: '#F87171',
  blue: '#60A5FA',
};

const MONO = font.mono;

/** Frame-quantised typing. Any easing here reads as a loading bar, not typing. */
const typeAt = (frame: number, start: number, text: string, step = 2) =>
  text.slice(0, Math.max(0, Math.floor((frame - start) / step)));

/** Square wave. A cursor that fades is a web page, not a terminal. */
const blockCursor = (frame: number) => (frame % 12 < 6 ? 1 : 0);

const ramp = (frame: number, start: number, len: number, easing = Easing.out(Easing.cubic)) =>
  interpolate(frame, [start, start + len], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing,
  });

/* ------------------------------------------------------------------ */
/* 1. The fuse: a command, and the crash into the product.             */

const CMD = 'arslan host --local --spawns 6';

const Boot: React.FC<{frame: number}> = ({frame}) => {
  const typed = typeAt(frame, 14, CMD, 2);
  const done = typed.length === CMD.length;
  const enter = 74;

  // The crash. origin pinned to the command line itself, so the frame dives
  // into the words that caused it.
  const z = interpolate(frame, [enter, enter + 6], [1, 3.2], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.cubic),
  });
  const blur = interpolate(frame, [enter + 4, enter + 6], [0, 10], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        transform: `scale(${z})`,
        transformOrigin: '324px 512px',
        filter: blur ? `blur(${blur}px)` : undefined,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 200,
          top: 400,
          fontFamily: MONO,
          fontSize: 52,
          lineHeight: 1.9,
          color: C.ink,
        }}
      >
        <div style={{color: C.faint, fontSize: 26, letterSpacing: '0.12em'}}>
          LOCAL · NOTHING LEAVES THIS MACHINE
        </div>
        <div style={{marginTop: 22}}>
          <span style={{color: C.amber}}>$ </span>
          {typed}
          <span
            style={{
              display: 'inline-block',
              width: 25,
              height: 52,
              marginLeft: 4,
              verticalAlign: '-8px',
              background: C.ink,
              opacity: done && frame > enter - 6 ? 1 : blockCursor(frame),
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------------ */
/* 2. The TUI. Everything after the fuse lives in this frame.          */

const Chrome: React.FC<{title: string; children: React.ReactNode; right?: string}> = ({
  title,
  children,
  right = 'local',
}) => (
  <AbsoluteFill style={{background: C.bg, fontFamily: MONO}}>
    <div
      style={{
        position: 'absolute',
        inset: '52px 76px',
        background: C.panel,
        border: `1px solid ${C.rule}`,
        borderRadius: 10,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          height: 64,
          flexShrink: 0,
          borderBottom: `1px solid ${C.rule}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 26px',
          gap: 16,
          fontSize: 20,
          color: C.dim,
          letterSpacing: '0.1em',
        }}
      >
        <span style={{color: C.amber}}>▚</span>
        <span style={{color: C.ink}}>arslan</span>
        <span style={{color: C.faint}}>—</span>
        <span>{title}</span>
        <span style={{flex: 1}} />
        <span style={{color: C.green}}>● {right}</span>
      </div>
      <div style={{flex: 1, minHeight: 0, position: 'relative'}}>{children}</div>
    </div>
  </AbsoluteFill>
);

/** `ai-stream-response`: the answer, then the working, then a single close. */
const Stream: React.FC<{frame: number}> = ({frame}) => {
  const rows: [string, string][] = [
    ['research-analyst', 'fetched 11 sources · sandboxed'],
    ['data-analyst', 'ran q3_actuals.py · duckdb'],
    ['data-analyst', 'built chart · 8 periods'],
    ['coding-assistant', 'patched report.ts · 2 files'],
    ['archivist', 'wrote 3 notes to second brain'],
    ['host', 'merged 5 results into one thread'],
  ];
  // Cues tighten but stay countable — work accelerating, not a log flushing.
  const cue = [40, 51, 61, 70, 78, 85];

  return (
    <div style={{position: 'absolute', inset: 0, padding: '44px 52px'}}>
      <div style={{fontSize: 27, color: C.dim}}>
        <span style={{color: C.amber}}>❯ </span>
        chart last quarter against the plan and tell me what moved
      </div>

      {/* The conclusion lands first and is given room to be read. */}
      <div
        style={{
          marginTop: 34,
          fontSize: 50,
          lineHeight: 1.42,
          color: C.ink,
          maxWidth: 1520,
          opacity: ramp(frame, 18, 12),
        }}
      >
        Revenue tracked <span style={{color: C.green}}>+8.4%</span> to plan. The whole
        gap is EMEA renewals.
      </div>

      <div style={{marginTop: 48, display: 'flex', flexDirection: 'column', gap: 22}}>
        {rows.map(([who, what], i) => {
          const p = ramp(frame, cue[i], 12);
          // The status glyph lags the row it belongs to — a receipt, not a
          // decoration, so it must not arrive with the thing it confirms.
          const s = frame - cue[i] - 3;
          const glyph = s < 8 ? '◌' : s < 18 ? '◍' : '✔';
          const gc = s < 18 ? C.dim : C.green;
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 26,
                fontSize: 29,
                alignItems: 'baseline',
                opacity: p,
                transform: `translateY(${(1 - p) * 18}px)`,
                filter: p < 1 ? `blur(${(1 - p) * 6}px)` : undefined,
              }}
            >
              <span style={{color: gc, width: 32}}>{glyph}</span>
              <span style={{color: C.amber, width: 350}}>{who}</span>
              <span style={{color: C.dim}}>{what}</span>
            </div>
          );
        })}
      </div>

      <div
        style={{
          position: 'absolute',
          left: 52,
          right: 52,
          bottom: 40,
          borderTop: `1px solid ${C.rule}`,
          paddingTop: 24,
          fontSize: 24,
          color: C.faint,
          display: 'flex',
          gap: 44,
          opacity: ramp(frame, 96, 14),
        }}
      >
        <span>5 spawns</span>
        <span>1 thread</span>
        <span>0 bytes egress</span>
        <span style={{flex: 1}} />
        <span style={{color: C.dim}}>2.9s</span>
      </div>
    </div>
  );
};

/** `command-palette-summon`. */
const Palette: React.FC<{frame: number}> = ({frame}) => {
  const dim = ramp(frame, 0, 10);
  const drop = interpolate(frame, [6, 21], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.bezier(0.16, 1.4, 0.4, 1), // overshoot, then back
  });
  const query = typeAt(frame, 50, 'pro', 5);
  const narrowed = query.length >= 2;
  const rows = [
    ['Promote a candidate', '⏎'],
    ['Prompt diff · rev 7 → 8', '⌘D'],
    ['Spawn a new agent', '⌘N'],
    ['Open second brain', '⌘B'],
    ['Revoke capability', '⌘⇧R'],
  ];
  const keep = narrowed ? 2 : 5;

  return (
    <>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `rgba(4,5,7,${0.55 * dim})`,
          backdropFilter: `blur(${10 * dim}px)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: '50%',
          top: 110,
          width: 1040,
          marginLeft: -520,
          background: '#111418',
          border: `1px solid ${C.ruleHi}`,
          borderRadius: 12,
          boxShadow: '0 30px 90px rgba(0,0,0,0.7)',
          overflow: 'hidden',
          opacity: drop,
          transform: `translateY(${(1 - drop) * -20}px)`,
        }}
      >
        <div
          style={{
            padding: '28px 30px',
            borderBottom: `1px solid ${C.rule}`,
            fontSize: 32,
            color: C.ink,
            display: 'flex',
            gap: 12,
          }}
        >
          <span style={{color: C.amber}}>⌘K</span>
          <span>
            {query}
            <span
              style={{
                display: 'inline-block',
                width: 16,
                height: 32,
                marginLeft: 3,
                verticalAlign: '-5px',
                background: C.ink,
                opacity: frame > 74 ? 1 : blockCursor(frame),
              }}
            />
          </span>
        </div>
        {rows.map(([label, key], i) => {
          // Collapse by height, not opacity: the point is that the list is
          // being squeezed, and a fade has no squeeze in it.
          const out = i >= keep;
          const h = out ? interpolate(frame, [62, 74], [72, 0], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          }) : 72;
          if (h <= 0.5) return null;
          const appear = ramp(frame, 20 + i * 4, 10);
          const on = i === 0 && frame > 76;
          return (
            <div
              key={label}
              style={{
                height: h,
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                padding: '0 30px',
                fontSize: 27,
                color: on ? C.ink : C.dim,
                background: on ? 'rgba(242,160,60,0.10)' : 'transparent',
                borderLeft: `2px solid ${on ? C.amber : 'transparent'}`,
                opacity: appear,
                transform: `translateY(${(1 - appear) * 8}px)`,
              }}
            >
              <span style={{flex: 1}}>{label}</span>
              <span style={{color: C.faint, fontSize: 21}}>{key}</span>
            </div>
          );
        })}
      </div>
    </>
  );
};

/** The gate, as a diff and a table. The one screen that has to be read. */
const Gate: React.FC<{frame: number}> = ({frame}) => {
  const dims: [string, number, number][] = [
    ['faithfulness', 0.71, 0.86],
    ['task completion', 0.64, 0.81],
    ['tool discipline', 0.78, 0.83],
    ['honesty', 0.82, 0.82],
  ];
  const promoted = frame > 128;
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        padding: '44px 52px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <div style={{fontSize: 24, color: C.faint, letterSpacing: '0.14em'}}>
        EVOLUTION INBOX · 1 PROPOSAL · HELD-OUT EXAM n=38 · SAMPLE DATA
      </div>

      <div style={{marginTop: 44, display: 'flex', gap: 60}}>
        <div style={{flex: 1}}>
          {dims.map(([n, inc, cand], i) => {
            const v = interpolate(frame, [16 + i * 9, 48 + i * 9], [inc, cand], {
              extrapolateLeft: 'clamp',
              extrapolateRight: 'clamp',
              easing: Easing.out(Easing.cubic),
            });
            const w = 520;
            return (
              <div key={n} style={{marginBottom: 40, opacity: ramp(frame, 10 + i * 6, 12)}}>
                <div style={{display: 'flex', fontSize: 29, color: C.dim}}>
                  <span style={{flex: 1}}>{n}</span>
                  <span style={{color: C.faint, marginRight: 26}}>
                    {inc.toFixed(2)}
                  </span>
                  <span style={{color: C.green}}>{v.toFixed(2)}</span>
                </div>
                <div
                  style={{
                    marginTop: 14,
                    height: 12,
                    width: w,
                    background: '#171B20',
                    position: 'relative',
                  }}
                >
                  <div
                    style={{
                      position: 'absolute',
                      inset: 0,
                      width: v * w,
                      background: `linear-gradient(90deg, ${C.amber}, ${C.green})`,
                    }}
                  />
                  <div
                    style={{
                      position: 'absolute',
                      top: -3,
                      bottom: -3,
                      left: inc * w,
                      width: 2,
                      background: C.ruleHi,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div style={{width: 700, opacity: ramp(frame, 58, 16)}}>
          <div style={{fontSize: 23, color: C.faint, letterSpacing: '0.14em'}}>
            PROMPT DIFF · REV 7 → 8
          </div>
          <div style={{marginTop: 20, fontSize: 25, lineHeight: 1.85}}>
            <div style={{color: C.red, background: 'rgba(248,113,113,0.07)', padding: '8px 14px'}}>
              − cite sources where possible
            </div>
            <div style={{color: C.green, background: 'rgba(74,222,128,0.07)', padding: '8px 14px'}}>
              + cite a source for every claim, or say it is unsourced
            </div>
          </div>
          <div
            style={{
              marginTop: 40,
              padding: '24px 28px',
              border: `1px solid ${promoted ? C.green : C.amber}`,
              color: promoted ? C.green : C.amber,
              fontSize: 30,
              letterSpacing: '0.1em',
              textAlign: 'center',
              background: promoted ? 'rgba(74,222,128,0.08)' : 'rgba(242,160,60,0.08)',
              transform: `scale(${frame >= 126 && frame < 132 ? 0.97 : 1})`,
            }}
          >
            {promoted ? '✔ PROMOTED' : '⏎ PROMOTE'}
          </div>
          <div style={{marginTop: 18, fontSize: 22, color: C.faint, textAlign: 'center'}}>
            nothing ships until you press it
          </div>
        </div>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------ */
/* 3. The sprint and the close.                                        */

/**
 * `beat-cut-moves` A. Cuts at 0/49/65/77/85/91/95 relative to the sprint —
 * intervals of 16/12/8/6/4, each roughly half the last. Decreasing them
 * linearly does not read as acceleration; this does.
 */
const SPRINT_CUTS = [0, 49, 65, 77, 85, 91, 95];
const SPRINT_VIEWS: {zoom: number; ox: string; oy: string}[] = [
  {zoom: 1, ox: '50%', oy: '50%'},
  {zoom: 1.8, ox: '26%', oy: '34%'},
  {zoom: 1, ox: '50%', oy: '50%'},
  {zoom: 2.6, ox: '74%', oy: '62%'},
  {zoom: 1.8, ox: '30%', oy: '70%'},
  {zoom: 2.6, ox: '62%', oy: '30%'},
  {zoom: 1.06, ox: '50%', oy: '50%'},
];

const Sprint: React.FC<{frame: number}> = ({frame}) => {
  let i = 0;
  for (let k = 0; k < SPRINT_CUTS.length; k++) if (frame >= SPRINT_CUTS[k]) i = k;
  const v = SPRINT_VIEWS[i];
  const cutFrame = frame === SPRINT_CUTS[i];
  // The last cut lands back on the wide and holds, easing in a touch. A sprint
  // needs a full stop or the energy has nowhere to go.
  const settle = i === SPRINT_CUTS.length - 1 ? ramp(frame, 95, 20) : 0;
  const zoom = v.zoom + settle * 0.06;

  return (
    <AbsoluteFill style={{background: C.bg, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          transform: `scale(${zoom})`,
          transformOrigin: `${v.ox} ${v.oy}`,
          filter: cutFrame ? 'brightness(1.05)' : undefined,
        }}
      >
        <Chrome title="host session">
          <Stream frame={200} />
        </Chrome>
      </AbsoluteFill>
      {cutFrame ? (
        <AbsoluteFill style={{background: 'rgba(255,255,255,0.06)'}} />
      ) : null}
    </AbsoluteFill>
  );
};

const Cta: React.FC<{frame: number}> = ({frame}) => {
  const line1 = typeAt(frame, 8, 'brew install --cask arslan', 2);
  const box = ramp(frame, 60, 20);
  return (
    <AbsoluteFill
      style={{
        background: C.bg,
        fontFamily: MONO,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div style={{width: 1180}}>
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 120,
            fontWeight: 700,
            letterSpacing: '-0.045em',
            color: C.ink,
            opacity: ramp(frame, 0, 16),
          }}
        >
          Arslan
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 32,
            color: C.dim,
            opacity: ramp(frame, 6, 16),
          }}
        >
          One host agent. Spawns you raised. Nothing ships until you press Promote.
        </div>

        <div
          style={{
            marginTop: 54,
            padding: '28px 32px',
            border: `1px solid ${C.rule}`,
            borderRadius: 8,
            background: C.panel,
            fontSize: 34,
            color: C.ink,
          }}
        >
          <span style={{color: C.amber}}>$ </span>
          {line1}
          <span
            style={{
              display: 'inline-block',
              width: 17,
              height: 34,
              marginLeft: 3,
              verticalAlign: '-4px',
              background: C.ink,
              opacity: blockCursor(frame),
            }}
          />
        </div>

        <div
          style={{
            marginTop: 34,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 16,
            padding: '24px 44px',
            borderRadius: 6,
            background: C.amber,
            color: '#140B02',
            fontFamily: font.sans,
            fontSize: 30,
            fontWeight: 650,
            opacity: box,
            transform: `translateY(${(1 - box) * 14}px)`,
          }}
        >
          <span>↓</span> Download for macOS
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: 21,
            color: C.faint,
            letterSpacing: '0.08em',
            opacity: box,
          }}
        >
          macOS 11+ · Apple Silicon · signed &amp; notarized · MIT
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------------ */

export const TERMINAL_FRAMES = 900;

export const Terminal: React.FC = () => {
  const f = useCurrentFrame();

  if (f < 80) return <Boot frame={f} />;

  if (f < 250) {
    // Lands at 1.06 and eases back to 1 — the classic settle after a crash in.
    const s = interpolate(f, [80, 88], [1.06, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    });
    return (
      <AbsoluteFill style={{background: C.bg, transform: `scale(${s})`}}>
        <Chrome title="host session">
          <Stream frame={f - 80} />
        </Chrome>
      </AbsoluteFill>
    );
  }

  if (f < 420) {
    return (
      <Chrome title="host session">
        <Stream frame={200} />
        <Palette frame={f - 250} />
      </Chrome>
    );
  }

  if (f < 640) {
    return (
      <Chrome title="evolution inbox" right="1 proposal">
        <Gate frame={f - 420} />
      </Chrome>
    );
  }

  if (f < 760) return <Sprint frame={f - 640} />;

  return <Cta frame={f - 760} />;
};
