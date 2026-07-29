import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {GATE, HOOKS, PRODUCT, SAFETY, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 2 of 4 — "PRESS".
 *
 * Carries the hook `HOOKS.machine` — "a machine, not a chat box", the sharpest
 * line in docs/marketing/copy.md and the one an earlier pass left out of all
 * four films. This cut is built entirely around it: the claim only works if the
 * film itself looks drawn rather than chatted at, so it is set on a real
 * 12-column grid with drawn hairlines and no interface at all.
 *
 * Paper, grid, and very large type. The opposite pole from the CLI cut: light
 * instead of dark, proportional instead of monospace, and typography rather
 * than interface carrying every beat.
 *
 * Shot vocabulary, from the shotcraft library:
 *   - `type-assembly-moves` A (split-text-stagger) — each word rises out of an
 *     invisible clip line with a 10% overshoot, 2f apart. The overshoot has to
 *     be visible at normal speed; the card is explicit that 6% tested as
 *     imperceptible, which is why this uses 10.
 *   - `type-assembly-moves` C (tracking-expand) — letters breathe out from
 *     -0.42em to their set tracking. Implemented as per-character translateX
 *     against a fixed letter-spacing, never by animating letter-spacing
 *     itself, which re-lays-out and judders every frame.
 *   - `color-block-step-wipe` — a solid block crosses the frame and the page
 *     has changed behind it.
 *   - `title-demote-to-label` — the headline that has been carrying the film
 *     shrinks into a caption and hands the frame to the wordmark.
 *
 * The grid is real. Every element sits on a 12-column measure with a 96px
 * margin, and the hairlines are drawn rather than implied, because a film about
 * a tool with strong opinions should look like it was set rather than laid out.
 */

const P = {
  paper: '#F2EFE8',
  paperDeep: '#E8E4DA',
  ink: '#15120D',
  inkSoft: '#4A443A',
  faint: '#9C9484',
  rule: '#CFC8BA',
  red: '#D8462B',
  amber: '#C9761C',
};

const MARGIN = 108;
const COLW = (1920 - MARGIN * 2) / 12;

const ramp = (f: number, s: number, l: number, e = Easing.out(Easing.cubic)) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/** `type-assembly-moves` A. Each word is a clip box; the word rises through it. */
const SplitRise: React.FC<{
  text: string;
  start: number;
  frame: number;
  size: number;
  color?: string;
  step?: number;
  weight?: number;
}> = ({text, start, frame, size, color = P.ink, step = 3, weight = 680}) => (
  <div style={{display: 'flex', flexWrap: 'wrap', gap: `0 ${size * 0.26}px`}}>
    {text.split(' ').map((word, i) => {
      const p = ramp(frame, start + i * step, 20, Easing.bezier(0.16, 1.2, 0.3, 1));
      return (
        <span
          key={i}
          style={{
            display: 'inline-block',
            overflow: 'hidden',
            lineHeight: 0.94,
            paddingBottom: size * 0.06,
          }}
        >
          <span
            style={{
              display: 'inline-block',
              // 115% down, overshooting 10% past the mark on the way back.
              transform: `translateY(${(1 - p) * 115}%)`,
              fontSize: size,
              fontWeight: weight,
              letterSpacing: '-0.045em',
              color,
            }}
          >
            {word}
          </span>
        </span>
      );
    })}
  </div>
);

/**
 * `type-assembly-moves` C. Letter-spacing stays at its final value throughout;
 * only per-character translateX moves. Animating letter-spacing itself would
 * re-lay-out the line every frame and judder.
 */
const TrackingExpand: React.FC<{
  text: string;
  start: number;
  frame: number;
  size: number;
  color?: string;
}> = ({text, start, frame, size, color = P.inkSoft}) => {
  const p = ramp(frame, start, 34);
  const mid = (text.length - 1) / 2;
  return (
    <div style={{fontSize: size, letterSpacing: '0.16em', color, whiteSpace: 'pre'}}>
      {text.split('').map((ch, i) => (
        <span
          key={i}
          style={{
            display: 'inline-block',
            transform: `translateX(${(1 - p) * (i - mid) * -0.56}em)`,
            opacity: p,
            filter: p < 1 ? `blur(${(1 - p) * 8}px)` : undefined,
          }}
        >
          {ch === ' ' ? ' ' : ch}
        </span>
      ))}
    </div>
  );
};

/** The hairline grid. Drawn, not implied. */
const Grid: React.FC<{frame: number; start: number}> = ({frame, start}) => {
  const p = ramp(frame, start, 40);
  return (
    <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
      {Array.from({length: 13}).map((_, i) => (
        <line
          key={i}
          x1={MARGIN + i * COLW}
          y1={0}
          x2={MARGIN + i * COLW}
          y2={1080 * p}
          stroke={P.rule}
          strokeWidth={1}
          opacity={0.5}
        />
      ))}
    </svg>
  );
};

/** `color-block-step-wipe`. The page has changed behind it. */
const BlockWipe: React.FC<{frame: number; start: number; color: string}> = ({
  frame,
  start,
  color,
}) => {
  const enter = ramp(frame, start, 12, Easing.bezier(0.7, 0, 0.3, 1));
  const exit = ramp(frame, start + 12, 12, Easing.bezier(0.7, 0, 0.3, 1));
  if (frame < start || frame > start + 26) return null;
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: color,
        clipPath: `inset(0 ${(1 - enter) * 100}% 0 ${exit * 100}%)`,
      }}
    />
  );
};

const Rule: React.FC<{y: number; frame: number; start: number; color?: string}> = ({
  y,
  frame,
  start,
  color = P.ink,
}) => (
  <div
    style={{
      position: 'absolute',
      left: MARGIN,
      top: y,
      height: 2,
      width: (1920 - MARGIN * 2) * ramp(frame, start, 26),
      background: color,
    }}
  />
);

const Folio: React.FC<{n: string; label: string; frame: number; start: number}> = ({
  n,
  label,
  frame,
  start,
}) => (
  <div
    style={{
      position: 'absolute',
      left: MARGIN,
      bottom: 62,
      display: 'flex',
      gap: 22,
      alignItems: 'baseline',
      fontFamily: font.mono,
      fontSize: 20,
      letterSpacing: '0.16em',
      color: P.faint,
      opacity: ramp(frame, start, 20),
    }}
  >
    <span style={{color: P.red}}>{n}</span>
    <span>{label}</span>
  </div>
);

/* ------------------------------------------------------------------ */

const Page: React.FC<{children: React.ReactNode}> = ({children}) => (
  <AbsoluteFill style={{background: P.paper, fontFamily: font.sans, overflow: 'hidden'}}>
    {children}
  </AbsoluteFill>
);

/** 01 — the thesis. */
const One: React.FC<{frame: number}> = ({frame}) => (
  <Page>
    <Grid frame={frame} start={0} />
    <div style={{position: 'absolute', left: MARGIN, top: 250, width: COLW * 10}}>
      <TrackingExpand text="LOCAL-FIRST AI ORCHESTRATOR" start={6} frame={frame} size={26} />
      <div style={{height: 46}} />
      <SplitRise text="Most AI apps" start={22} frame={frame} size={150} />
      <div style={{height: 10}} />
      <SplitRise text="are a chat box." start={34} frame={frame} size={150} />
      <div style={{height: 26}} />
      <SplitRise
        text="This one is a machine."
        start={54}
        frame={frame}
        size={150}
        color={P.red}
      />
    </div>
    <Rule y={880} frame={frame} start={70} />
    <Folio n="01" label="THE THESIS" frame={frame} start={78} />
  </Page>
);

/**
 * 02 — the parts, as an engineering legend.
 *
 * Replaces a page that read "Six specialists." over a grid of six named
 * agents. The product has no such roster: you raise spawns yourself, drafting
 * them from a persona seed library, and the router can propose creating one for
 * work nothing covers. Six was a number invented for the layout — the only six
 * in the README is six languages and six theme palettes.
 */
const Two: React.FC<{frame: number}> = ({frame}) => {
  const parts: [string, string][] = [
    ['Host agent', 'the only thing you talk to'],
    ['Spawns', SPAWNS.howMany],
    ['Kernel sandbox', 'network-denied, fails closed'],
    ['Credential proxy', 'tokens stay outside'],
    ['Promotion gate', 'a held-out exam'],
    ['Second brain', 'beliefs carry time'],
  ];
  return (
    <Page>
      <Grid frame={frame} start={0} />
      <div style={{position: 'absolute', left: MARGIN, top: 150, width: COLW * 9}}>
        <SplitRise text="Drawn like a machine." start={4} frame={frame} size={126} />
        <div
          style={{
            marginTop: 26,
            fontSize: 34,
            color: P.inkSoft,
            maxWidth: COLW * 7,
            opacity: ramp(frame, 26, 20),
          }}
        >
          Named parts, in fixed places, each doing one job you can point at.
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          right: MARGIN,
          top: 500,
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 2,
          background: P.rule,
          border: `2px solid ${P.ink}`,
        }}
      >
        {parts.map(([n, t], i) => {
          const p = ramp(frame, 40 + i * 6, 22, Easing.bezier(0.16, 1.15, 0.3, 1));
          return (
            <div
              key={n}
              style={{
                background: P.paper,
                padding: '30px 30px 34px',
                opacity: p,
                transform: `translateY(${(1 - p) * 26}px)`,
              }}
            >
              <div
                style={{
                  fontFamily: font.mono,
                  fontSize: 19,
                  color: P.red,
                  letterSpacing: '0.14em',
                }}
              >
                {String(i + 1).padStart(2, '0')}
              </div>
              <div style={{marginTop: 16, fontSize: 34, fontWeight: 640, letterSpacing: '-0.02em'}}>
                {n}
              </div>
              <div style={{marginTop: 10, fontFamily: font.mono, fontSize: 19, color: P.faint}}>
                {t}
              </div>
            </div>
          );
        })}
      </div>
      <Folio n="02" label="THE PARTS" frame={frame} start={16} />
    </Page>
  );
};

/** 03 — the gate. The line the whole film exists to deliver. */
const Three: React.FC<{frame: number}> = ({frame}) => {
  const underline = ramp(frame, 58, 26, Easing.bezier(0.5, 0, 0.2, 1));
  return (
    <Page>
      <Grid frame={frame} start={0} />
      <div style={{position: 'absolute', left: MARGIN, top: 210, width: COLW * 10}}>
        <TrackingExpand text="THE PROMOTION GATE" start={2} frame={frame} size={26} />
        <div style={{height: 52}} />
        <SplitRise text="Nothing ships" start={16} frame={frame} size={150} />
        <div style={{height: 12}} />
        <div style={{position: 'relative', display: 'inline-block'}}>
          <SplitRise text="until you press" start={28} frame={frame} size={150} />
        </div>
        <div style={{height: 12}} />
        <div style={{position: 'relative', display: 'inline-block'}}>
          <SplitRise text="Promote." start={40} frame={frame} size={150} color={P.red} />
          {/* `marker-underline-title`: one confident stroke, drawn left to right. */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              bottom: -6,
              height: 12,
              width: `${underline * 100}%`,
              background: P.red,
              opacity: 0.32,
            }}
          />
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          right: MARGIN,
          top: 260,
          width: COLW * 3.2,
          fontFamily: font.mono,
          fontSize: 22,
          lineHeight: 2.1,
          color: P.inkSoft,
          opacity: ramp(frame, 74, 22),
        }}
      >
        <div style={{color: P.faint, letterSpacing: '0.14em', fontSize: 18}}>
          THE REPLAY GATE
        </div>
        {[
          ['method', 'paired replay'],
          ['judged', 'positions swapped'],
          ['win floor', `${Math.round(GATE.winRate * 100)}%`],
          ['holdout min', `${GATE.minHoldout} pairs`],
          ...GATE.dimensions.map((d) => [d, 'not worse']),
        ].map(([k, v]) => (
          <div key={k} style={{display: 'flex', borderBottom: `1px solid ${P.rule}`}}>
            <span style={{flex: 1}}>{k}</span>
            <span style={{color: P.ink}}>{v}</span>
          </div>
        ))}
        <div style={{marginTop: 14, fontSize: 17, color: P.faint, lineHeight: 1.5}}>
          {GATE.holdoutEnforced}
        </div>
      </div>
      <Folio n="03" label="THE GATE" frame={frame} start={20} />
    </Page>
  );
};

/** 04 — the numbers, set as a statistics spread. */
const Four: React.FC<{frame: number}> = ({frame}) => {
  /* Every one of these is in `facts.ts` with a source. The page this replaces
     had "6 spawns", which the product does not have. */
  const stats: [string, string][] = [
    ['0', 'third-party servers in the middle — your machine, your keys'],
    [`${Math.round(GATE.winRate * 100)}%`, 'of held-out pairs a new prompt must win to reach your inbox'],
    ['1', 'thread — everything the spawns do comes back to it'],
  ];
  return (
    <Page>
      <Grid frame={frame} start={0} />
      <div style={{position: 'absolute', left: MARGIN, right: MARGIN, top: 190}}>
        <TrackingExpand text="WHAT IT ACTUALLY COSTS YOU" start={2} frame={frame} size={26} />
      </div>
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          right: MARGIN,
          top: 300,
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {stats.map(([n, label], i) => {
          const p = ramp(frame, 14 + i * 14, 24, Easing.bezier(0.16, 1.15, 0.3, 1));
          return (
            <div
              key={label}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 56,
                borderTop: `2px solid ${P.ink}`,
                padding: '30px 0 34px',
                opacity: p,
                transform: `translateY(${(1 - p) * 22}px)`,
              }}
            >
              <span
                style={{
                  fontSize: 150,
                  fontWeight: 700,
                  letterSpacing: '-0.06em',
                  lineHeight: 0.86,
                  color: i === 0 ? P.red : P.ink,
                  minWidth: 280,
                }}
              >
                {n}
              </span>
              <span style={{fontSize: 40, color: P.inkSoft, maxWidth: COLW * 7}}>{label}</span>
            </div>
          );
        })}
      </div>
      <Folio n="04" label="THE TERMS" frame={frame} start={10} />
    </Page>
  );
};

/**
 * 05 — the close. `title-demote-to-label`: the line that has been carrying the
 * film shrinks into a caption and hands the frame over to the wordmark.
 */
const Close: React.FC<{frame: number}> = ({frame}) => {
  const demote = ramp(frame, 0, 30, Easing.bezier(0.5, 0, 0.2, 1));
  const size = 150 - demote * 124;
  const y = 300 - demote * 180;
  const btn = ramp(frame, 62, 26, Easing.bezier(0.16, 1.2, 0.3, 1));
  return (
    <Page>
      <Grid frame={frame} start={-40} />
      <div
        style={{
          position: 'absolute',
          left: MARGIN,
          top: y,
          fontSize: size,
          maxWidth: COLW * 9,
          fontWeight: 680,
          letterSpacing: '-0.045em',
          color: P.faint,
          lineHeight: 1,
        }}
      >
        {HOOKS.machine}.
      </div>

      <div style={{position: 'absolute', left: MARGIN, top: 260, opacity: ramp(frame, 26, 24)}}>
        <div
          style={{
            fontSize: 224,
            fontWeight: 700,
            letterSpacing: '-0.055em',
            color: P.ink,
            lineHeight: 0.94,
          }}
        >
          Arslan
        </div>
        <div style={{marginTop: 20, fontSize: 34, color: P.inkSoft, maxWidth: COLW * 6}}>
          {SAFETY.local}
        </div>

        <div
          style={{
            marginTop: 54,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 18,
            background: P.ink,
            color: P.paper,
            padding: '26px 46px',
            fontSize: 32,
            fontWeight: 640,
            opacity: btn,
            transform: `translateY(${(1 - btn) * 20}px)`,
          }}
        >
          <span>↓</span> Download for macOS
        </div>
        <div
          style={{
            marginTop: 22,
            fontFamily: font.mono,
            fontSize: 21,
            letterSpacing: '0.12em',
            color: P.faint,
            opacity: btn,
          }}
        >
          {`${PRODUCT.platform} · ${PRODUCT.signing} · ${PRODUCT.license}`.toUpperCase()}
        </div>
      </div>
      <Rule y={946} frame={frame} start={40} color={P.red} />
      <Folio n="05" label="ARSLAN" frame={frame} start={48} />
    </Page>
  );
};

/* ------------------------------------------------------------------ */

export const PRESS_FRAMES = 900;

const PAGES = [
  {at: 0, C: One},
  {at: 178, C: Two},
  {at: 386, C: Three},
  {at: 570, C: Four},
  {at: 730, C: Close},
];

export const Press: React.FC = () => {
  const f = useCurrentFrame();
  let i = 0;
  for (let k = 0; k < PAGES.length; k++) if (f >= PAGES[k].at) i = k;
  const {at, C} = PAGES[i];

  return (
    <AbsoluteFill style={{background: P.paper}}>
      <C frame={f - at} />
      {/* Each page change is a block crossing the frame, not a dissolve. The
          block is the transition — you never see two pages at once. */}
      {PAGES.slice(1).map((p, k) => (
        <BlockWipe
          key={p.at}
          frame={f}
          start={p.at - 13}
          color={k % 2 === 0 ? P.ink : P.red}
        />
      ))}
    </AbsoluteFill>
  );
};
