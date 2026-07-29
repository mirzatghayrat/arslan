import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {font} from '../theme';

/**
 * FILM 4 of 4 — "PULSE".
 *
 * Bright, saturated, and the only cut of the four with any real violence in it.
 * Where the press cut states and the system cut explains, this one hits: cards
 * thrown into a grid, a number slammed down hard enough to shake the frame, an
 * odometer counting up, and three shutter flashes. It is the cut built for a
 * feed, where the first second decides everything.
 *
 * Shot vocabulary, from the shotcraft library:
 *   - `deck-deal-flyin` — a段落-level anticipation beat first (the stack presses
 *     down and the top card pulls back against the throw), then cards deal out
 *     on a hard-accelerating cue curve, 4f between the first pair collapsing
 *     towards 0.2f. Evenly spaced cues read as mechanical immediately. The
 *     anticipation is段落-level and NOT per-card, which would flatten the
 *     acceleration it exists to set up.
 *   - `slam-entrance-moves` B (score-slam) — six frames of Easing.in(quad),
 *     because ease-out is a thing being set down and ease-in is a thing being
 *     dropped. On the landing frame: ring, dust and shake all at once, with
 *     the ring's expansion on out-cubic and its fade on linear — sharing one
 *     curve makes it vanish before it has finished opening.
 *   - `odometer-digit-roll` — each digit its own strip, decelerating to half a
 *     row past its target and snapping back. Left to right, 7f apart: that
 *     stagger is the "tk, tk, tk" the move exists for.
 *   - `beat-cut-moves` B (paparazzi-flash) — three flashes at tightening
 *     intervals, each cutting to a closer crop of the same frame. Ordered wide
 *     → card → number, because any other order reads as a mis-cut.
 */

const K = {
  paper: '#FFFFFF',
  ink: '#0B0A08',
  amber: '#E9761B',
  amberDeep: '#C25A0B',
  cream: '#FFF3E2',
  green: '#0E9F6E',
  grey: '#8B8578',
  rule: '#E4DFD5',
};

const ramp = (f: number, s: number, l: number, e = Easing.out(Easing.cubic)) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/** Deterministic jitter. Math.random would differ between render passes. */
const jit = (k: number, m: number) => (((k * 7919) % (m * 2 + 1)) - m);

/* ================================================================== */
/* 1. deck-deal-flyin                                                  */

const DECK = [
  ['Host session', 'one thread'],
  ['Research Analyst', 'fetch · 11 sources'],
  ['Data & Chart', 'python · duckdb'],
  ['Coding Assistant', 'diff · 2 files'],
  ['Ops Runner', 'shell · k8s'],
  ['Inbox Triage', 'gmail-mcp'],
  ['Archivist', 'notes · search'],
  ['Second brain', '214 notes'],
  ['Evolution inbox', '1 proposal'],
  ['Capabilities', '6 grants'],
  ['Diagnostics', 'net denied'],
  ['Spawns ledger', '6 spawns'],
];

const CARD_W = 418;
const CARD_H = 198;
const GRID_X = 4;
const gridPos = (i: number) => ({
  x: 122 + (i % GRID_X) * (CARD_W + 26),
  y: 288 + Math.floor(i / GRID_X) * (CARD_H + 26),
});

const Deal: React.FC<{f: number}> = ({f}) => {
  const SX = 960 - CARD_W / 2;
  const SY = 470;

  // Section-level anticipation: the stack loads before it throws. Amplitude has
  // to clear the eye's threshold — the card is explicit that a few pixels tests
  // as nothing at all.
  const load = ramp(f, 8, 16, Easing.out(Easing.cubic)) * (1 - ramp(f, 26, 6));

  return (
    <AbsoluteFill style={{background: K.paper, fontFamily: font.sans}}>
      <div
        style={{
          position: 'absolute',
          left: 132,
          top: 116,
          fontSize: 76,
          fontWeight: 720,
          letterSpacing: '-0.045em',
          color: K.ink,
          opacity: ramp(f, 96, 20),
          transform: `translateY(${(1 - ramp(f, 96, 20)) * 18}px)`,
        }}
      >
        Everything it can do, in one place.
      </div>

      {DECK.map((c, i) => {
        // Hard-accelerating deal: gaps collapse from 4f towards nothing.
        const cue = 30 + 4 * i - 0.16 * i * (i - 1);
        const g = gridPos(i);
        const fly = ramp(f, cue, 8, Easing.bezier(0.3, 0, 0.2, 1));
        const settle = ramp(f, cue + 8, 4, Easing.bezier(0.3, 0, 0.25, 1.15));
        const press = ramp(f, cue + 12, 2);

        if (f < cue) {
          // Still on the stack: physical layering plus deterministic jitter.
          const lift = load * (40 + (i === DECK.length - 1 ? 30 : 0));
          return (
            <div
              key={i}
              style={{
                position: 'absolute',
                left: SX + jit(i, 8),
                top: SY + i * -3 + lift,
                width: CARD_W,
                height: CARD_H,
                background: K.paper,
                border: `2px solid ${K.ink}`,
                borderRadius: 14,
                transform: `rotate(${jit(i + 3, 3)}deg)`,
                boxShadow: '0 10px 30px rgba(0,0,0,0.10)',
              }}
            />
          );
        }

        const x = SX + (g.x - SX) * fly;
        const y = SY + (g.y - SY) * fly - Math.sin(fly * Math.PI) * 90;
        const sc =
          (1 + Math.sin(fly * Math.PI) * 0.06) * (1 - settle * 0) * (1 - (1 - press) * 0.004);
        const rot = jit(i + 3, 3) * (1 - fly) + (1 - settle) * 1.2;

        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: CARD_W,
              height: CARD_H,
              background: i === 0 ? K.amber : K.paper,
              color: i === 0 ? K.paper : K.ink,
              border: `2px solid ${K.ink}`,
              borderRadius: 14,
              padding: '26px 28px',
              transform: `rotate(${rot}deg) scale(${sc})`,
              boxShadow: fly < 1 ? '0 26px 50px rgba(0,0,0,0.16)' : '0 4px 14px rgba(0,0,0,0.07)',
              filter: fly < 1 ? `blur(${(1 - fly) * 5}px)` : undefined,
            }}
          >
            <div style={{fontSize: 33, fontWeight: 680, letterSpacing: '-0.02em'}}>{c[0]}</div>
            <div
              style={{
                marginTop: 12,
                fontFamily: font.mono,
                fontSize: 20,
                color: i === 0 ? 'rgba(255,255,255,0.85)' : K.grey,
              }}
            >
              {c[1]}
            </div>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 2. score-slam                                                       */

const Slam: React.FC<{f: number}> = ({f}) => {
  const LAND = 26;
  // ease-IN: a thing being dropped, not a thing being set down.
  const drop = interpolate(f, [LAND - 6, LAND], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.in(Easing.quad),
  });
  const scale = 1 + drop * 1.5;
  const rot = drop * 5;

  // Expansion on out-cubic, fade on linear. One shared curve and the ring is
  // gone before it has finished opening.
  const t = f - LAND;
  const ringR = t >= 0 && t < 16 ? 80 + ramp(f, LAND, 14) * 780 : 0;
  const ringO = t >= 0 && t < 16 ? 1 - t / 16 : 0;
  const shake = t >= 0 && t < 5 ? Math.sin(t * 3.4) * 18 * Math.exp(-t * 0.8) : 0;

  return (
    <AbsoluteFill
      style={{
        background: K.paper,
        fontFamily: font.sans,
        transform: `translate(${shake}px, ${shake * 0.6}px)`,
      }}
    >
      {/* neighbours, pushed 3f after the hit — being shoved, not moving with it */}
      {[-1, 1].map((side) => {
        const push = t >= 3 ? Math.cos((t - 3) / 2) * Math.exp(-(t - 3) / 8) : 0;
        const on = t >= 3 && t < 44 ? push : 0;
        return (
          <div
            key={side}
            style={{
              position: 'absolute',
              top: 400,
              left: side < 0 ? 92 : 1420,
              width: 400,
              height: 280,
              background: K.paper,
              border: `2px solid ${K.rule}`,
              borderRadius: 16,
              padding: '26px 28px',
              transform: `translateX(${on * 30 * side}px) rotate(${on * 3 * side}deg)`,
              opacity: ramp(f, 4, 16),
            }}
          >
            <div style={{fontFamily: font.mono, fontSize: 19, color: K.grey}}>
              {side < 0 ? 'INCUMBENT' : 'REGRESSIONS'}
            </div>
            <div style={{marginTop: 14, fontSize: 62, fontWeight: 720, color: K.grey}}>
              {side < 0 ? '0.71' : 'none'}
            </div>
          </div>
        );
      })}

      {ringR > 0 ? (
        <div
          style={{
            position: 'absolute',
            left: 960 - ringR / 2,
            top: 540 - ringR / 2,
            width: ringR,
            height: ringR,
            borderRadius: '50%',
            border: `5px solid ${K.amber}`,
            opacity: ringO * 0.8,
          }}
        />
      ) : null}

      {t >= 0 && t < 22
        ? Array.from({length: 22}).map((_, i) => {
            const ang = (i / 22) * Math.PI * 2 + 0.3;
            const dist = (160 + jit(i, 80)) * ramp(f, LAND, 18);
            return (
              <div
                key={i}
                style={{
                  position: 'absolute',
                  left: 960 + Math.cos(ang) * dist,
                  top: 540 + Math.sin(ang) * dist * 0.7,
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: K.amber,
                  opacity: 1 - t / 22,
                }}
              />
            );
          })
        : null}

      <div
        style={{
          position: 'absolute',
          left: 560,
          top: 330,
          width: 800,
          background: K.amber,
          color: K.paper,
          borderRadius: 20,
          padding: '46px 52px',
          transform: `scale(${scale}) rotate(${rot}deg)`,
          boxShadow: `0 ${30 + drop * 60}px ${60 + drop * 80}px rgba(0,0,0,${0.2 + drop * 0.2})`,
        }}
      >
        <div style={{fontFamily: font.mono, fontSize: 22, letterSpacing: '0.16em', opacity: 0.85}}>
          HELD-OUT EXAM · n=38 · SAMPLE DATA
        </div>
        <div style={{marginTop: 18, fontSize: 168, fontWeight: 780, letterSpacing: '-0.05em', lineHeight: 1}}>
          0.86
        </div>
        <div style={{marginTop: 10, fontSize: 34, fontWeight: 600}}>
          faithfulness, up from 0.71
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 132,
          bottom: 120,
          fontSize: 46,
          fontWeight: 680,
          letterSpacing: '-0.03em',
          color: K.ink,
          opacity: ramp(f, 46, 20),
        }}
      >
        It has to pass an exam it has never seen.
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 3. odometer-digit-roll                                              */

const Odometer: React.FC<{f: number}> = ({f}) => {
  const digits = '214'.split('');
  const ROW = 268;

  const allLocked = 20 + (digits.length - 1) * 7 + 22;
  const pulse = ramp(f, allLocked, 4) * (1 - ramp(f, allLocked + 4, 6));

  return (
    <AbsoluteFill
      style={{
        background: K.ink,
        color: K.paper,
        fontFamily: font.sans,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          display: 'flex',
          transform: `scale(${1 + pulse * 0.035})`,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {digits.map((d, i) => {
          const start = 20 + i * 7;
          const target = Number(d);
          // Decelerate to half a row past, then snap back. No overshoot and it
          // reads as sliding to a stop, which is not a mechanism.
          const over = ramp(f, start, 16, Easing.out(Easing.cubic));
          const back = ramp(f, start + 16, 6, Easing.out(Easing.cubic));
          const spins = 3 + i;
          const pos = over * (spins * 10 + target + 0.5) - back * 0.5;
          const moving = f > start && f < start + 16;

          return (
            <div
              key={i}
              style={{
                width: 196,
                height: ROW,
                overflow: 'hidden',
                position: 'relative',
              }}
            >
              {[0, -1, 1].map((gh) => (
                <div
                  key={gh}
                  style={{
                    position: 'absolute',
                    left: 0,
                    right: 0,
                    top: 0,
                    transform: `translateY(${-(pos % 10) * ROW + gh * ROW * 0.5}px)`,
                    opacity: gh === 0 ? 1 : moving ? (gh === -1 ? 0.25 : 0.12) : 0,
                  }}
                >
                  {Array.from({length: 20}).map((_, n) => (
                    <div
                      key={n}
                      style={{
                        height: ROW,
                        fontSize: 246,
                        fontWeight: 800,
                        lineHeight: `${ROW}px`,
                        textAlign: 'center',
                        letterSpacing: '-0.04em',
                      }}
                    >
                      {n % 10}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 26,
          fontSize: 42,
          fontWeight: 600,
          color: K.amber,
          opacity: ramp(f, allLocked, 16),
        }}
      >
        notes it wrote for you, on its own
      </div>
      <div
        style={{
          marginTop: 14,
          fontFamily: font.mono,
          fontSize: 24,
          color: 'rgba(255,255,255,0.42)',
          opacity: ramp(f, allLocked + 8, 16),
        }}
      >
        second brain · with a time axis · sample data
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 4. paparazzi-flash                                                  */

/**
 * The frame the three flashes cut into, at three magnifications.
 *
 * The log panel is deliberately tall enough that the tightest crop is still
 * full of it. An earlier pass had a short panel, and magnifying it left white
 * bands top and bottom — a crop has to be a crop of something, not a blow-up
 * floating on the page.
 */
const LOG: [string, string, string][] = [
  ['run', 'sandbox start \u00b7 net=none \u00b7 fs=scratch', 'ok'],
  ['exec', 'charge_report.py \u00b7 84 lines \u00b7 generated', 'ok'],
  ['deny', 'connect api.stripe.com:443 \u2014 no route', 'deny'],
  ['deny', 'resolve api.stripe.com \u2014 no resolver', 'deny'],
  ['route', 'credential proxy \u00b7 key held outside', 'ok'],
  ['note', 'the code never saw the key', 'note'],
];

const FlashFrame: React.FC<{zoom: number; ox: string; oy: string; settle: number}> = ({
  zoom,
  ox,
  oy,
  settle,
}) => (
  <AbsoluteFill style={{background: K.paper, overflow: 'hidden'}}>
    <AbsoluteFill
      style={{
        transform: `scale(${zoom * (1 + (1 - settle) * 0.03)}) translateY(${(1 - settle) * -16}px)`,
        transformOrigin: `${ox} ${oy}`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          left: 122,
          top: 96,
          fontFamily: font.sans,
          fontSize: 70,
          fontWeight: 720,
          letterSpacing: '-0.045em',
          color: K.ink,
          maxWidth: 1400,
        }}
      >
        Generated code runs with no network at all.
      </div>
      <div
        style={{
          position: 'absolute',
          left: 122,
          top: 268,
          width: 1676,
          height: 700,
          background: K.ink,
          borderRadius: 18,
          padding: '44px 48px',
          fontFamily: font.mono,
          fontSize: 34,
          lineHeight: 2.5,
          color: '#CBD5E1',
        }}
      >
        {LOG.map(([tag, text, tone], i) => (
          <div key={i} style={{display: 'flex', gap: 22}}>
            <span
              style={{
                color: tone === 'deny' ? '#F87171' : tone === 'note' ? K.amber : K.green,
                width: 130,
                flexShrink: 0,
              }}
            >
              {tag}
            </span>
            <span style={{color: tone === 'deny' ? '#FCA5A5' : '#CBD5E1'}}>{text}</span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  </AbsoluteFill>
);

const FLASH = [30, 52, 70];
/* Wide, then the log block, then the refusal itself. Layer by layer closer —
   the card is explicit that any other ordering reads as a mis-cut. */
const CROPS = [
  {zoom: 1, ox: '50%', oy: '50%'},
  {zoom: 1.95, ox: '34%', oy: '52%'},
  {zoom: 3.3, ox: '38%', oy: '50%'},
];

const Paparazzi: React.FC<{f: number}> = ({f}) => {
  let i = 0;
  for (let k = 0; k < FLASH.length; k++) if (f >= FLASH[k]) i = k + 1;
  const crop = CROPS[Math.min(i, CROPS.length - 1)];
  const since = i === 0 ? 99 : f - FLASH[i - 1];
  const settle = ramp(f, i === 0 ? 0 : FLASH[i - 1], 6);

  // The pre-roll has to be alive or there is nothing for the flash to freeze.
  const drift = i === 0 ? 1 + ramp(f, 0, 30) * 0.05 : 1;

  let flash = 0;
  for (const c of FLASH) if (f >= c && f < c + 4) flash = Math.max(flash, 1 - (f - c) / 4);

  const shakeX = flash > 0.5 ? jit(f, 2) : 0;

  return (
    <AbsoluteFill style={{transform: `translate(${shakeX}px, ${jit(f + 5, 2) * (flash > 0.5 ? 1 : 0)}px)`}}>
      <AbsoluteFill style={{transform: `scale(${drift})`}}>
        <FlashFrame zoom={crop.zoom} ox={crop.ox} oy={crop.oy} settle={settle} />
      </AbsoluteFill>
      {flash > 0 ? (
        <AbsoluteFill style={{background: '#fff', opacity: flash * 0.95}} />
      ) : null}
      {since > 40 && i === 3 ? null : null}
    </AbsoluteFill>
  );
};

/* ================================================================== */
/* 5. the line, and the close                                          */

const Statement: React.FC<{f: number}> = ({f}) => {
  const words = ['Nothing', 'ships', 'until', 'you', 'press', 'Promote.'];
  return (
    <AbsoluteFill
      style={{
        background: K.amber,
        color: K.paper,
        fontFamily: font.sans,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: '0 132px',
      }}
    >
      <div style={{display: 'flex', flexWrap: 'wrap', gap: '0 30px'}}>
        {words.map((w, i) => {
          const p = ramp(f, 6 + i * 5, 20, Easing.bezier(0.16, 1.25, 0.3, 1));
          return (
            <span
              key={i}
              style={{display: 'inline-block', overflow: 'hidden', lineHeight: 0.96, paddingBottom: 14}}
            >
              <span
                style={{
                  display: 'inline-block',
                  transform: `translateY(${(1 - p) * 118}%)`,
                  fontSize: 156,
                  fontWeight: 780,
                  letterSpacing: '-0.05em',
                }}
              >
                {w}
              </span>
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const Cta: React.FC<{f: number}> = ({f}) => {
  // Starts on the cut, not four frames after it: the statement beat ends
  // on the same frame, so any delay here is a white flash.
  const a = ramp(f, 0, 24, Easing.bezier(0.16, 1.25, 0.3, 1));
  const b = ramp(f, 22, 24, Easing.bezier(0.16, 1.25, 0.3, 1));
  return (
    <AbsoluteFill
      style={{
        background: K.paper,
        fontFamily: font.sans,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          fontSize: 190,
          fontWeight: 780,
          letterSpacing: '-0.055em',
          color: K.ink,
          opacity: a,
          transform: `translateY(${(1 - a) * 30}px)`,
        }}
      >
        Arslan
      </div>
      <div style={{marginTop: 8, fontSize: 36, color: K.grey, opacity: a, maxWidth: 1000}}>
        One host agent. Spawns you raised.
      </div>
      <div
        style={{
          marginTop: 50,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 18,
          padding: '28px 56px',
          borderRadius: 999,
          background: K.amber,
          color: K.paper,
          fontSize: 36,
          fontWeight: 700,
          opacity: b,
          transform: `translateY(${(1 - b) * 22}px) scale(${0.96 + b * 0.04})`,
          boxShadow: '0 24px 60px rgba(233,118,27,0.36)',
        }}
      >
        <span>↓</span> Download for macOS
      </div>
      <div
        style={{
          marginTop: 22,
          fontFamily: font.mono,
          fontSize: 22,
          letterSpacing: '0.1em',
          color: K.grey,
          opacity: b,
        }}
      >
        macOS 11+ · Apple Silicon · signed &amp; notarized · MIT
      </div>
    </AbsoluteFill>
  );
};

/* ================================================================== */

export const PULSE_FRAMES = 900;

const BEATS = [
  {at: 0, C: Deal},
  {at: 140, C: Slam},
  {at: 290, C: Odometer},
  {at: 440, C: Paparazzi},
  {at: 580, C: Statement},
  {at: 720, C: Cta},
];

export const Pulse: React.FC = () => {
  const f = useCurrentFrame();
  let i = 0;
  for (let k = 0; k < BEATS.length; k++) if (f >= BEATS[k].at) i = k;
  const {at, C} = BEATS[i];
  return (
    <AbsoluteFill style={{background: K.paper}}>
      <C f={f - at} />
    </AbsoluteFill>
  );
};
