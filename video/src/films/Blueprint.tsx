import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {GATE, PRODUCT, SAFETY, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 5 — "BLUEPRINT". Built for one specific place: a LinkedIn feed.
 *
 * Square, 1080 x 1080. That is not a stylistic choice — a square post occupies
 * roughly half again the vertical space of 16:9 in the feed, and this is the
 * only one of the films with a named destination. It also suits the content:
 * a block diagram reads top-to-bottom, which is the axis a square gives you.
 *
 * The register is an engineering drawing rather than a product film: sheet
 * border, title block, revision box, dimension leaders, mono annotation, one
 * accent. Nothing moves that a pen could not have drawn. The reason is the
 * audience — it is going out under the byline of someone who is not an engineer,
 * so the film should not pretend to be a screen recording of software it is
 * explaining. A drawing is honest about being an explanation.
 *
 * Shot vocabulary, from the shotcraft library:
 *   - `draw-svg-trace` throughout, done properly: `pathLength={1}` with
 *     `strokeDasharray="1"` and the offset run 1 → 0, so no path length ever
 *     needs measuring. Every stroke carries a pen head — a second, thicker,
 *     short-dash copy of the same path riding at the front. Without the head
 *     it is a border getting longer; with it, someone is drawing.
 *   - The closing flash on each shape: the stroke darkens and thickens for two
 *     frames and eases back over six, then hands off to the shape's own border
 *     while its contents fade up. That flash is the full stop — the card is
 *     explicit that without it "finished drawing" has no punctuation.
 */

const B = {
  paper: '#F6F4EF',
  grid: '#DCD8CE',
  ink: '#171E27',
  line: '#5C6B7C',
  soft: '#8A93A0',
  accent: '#C2650F',
  red: '#B5442B',
  green: '#2F7D5C',
};

export const BLUEPRINT_SIZE = 1080;
export const BLUEPRINT_FRAMES = 900;

const ramp = (f: number, s: number, l: number, e = Easing.out(Easing.cubic)) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/**
 * A stroke being drawn, with a pen head at the front.
 *
 * `pathLength={1}` normalises every path to unit length, which is what makes
 * this work on rects, lines and curves without measuring any of them.
 */
const Draw: React.FC<{
  d?: string;
  rect?: {x: number; y: number; w: number; h: number; r?: number};
  f: number;
  start: number;
  dur?: number;
  colour?: string;
  width?: number;
  dashed?: boolean;
}> = ({d, rect, f, start, dur = 34, colour = B.line, width = 2.5, dashed}) => {
  const p = ramp(f, start, dur, Easing.inOut(Easing.cubic));
  if (p <= 0) return null;

  // The full stop: two frames darker and thicker, six easing back.
  const flash = ramp(f, start + dur, 2) * (1 - ramp(f, start + dur + 2, 6));
  const w = width + flash * 3;
  const c = flash > 0.02 ? B.ink : colour;

  const common = {
    fill: 'none' as const,
    stroke: c,
    strokeWidth: w,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  };
  const shape = (extra: object) =>
    rect ? (
      <rect
        x={rect.x}
        y={rect.y}
        width={rect.w}
        height={rect.h}
        rx={rect.r ?? 4}
        pathLength={1}
        {...common}
        {...extra}
      />
    ) : (
      <path d={d} pathLength={1} {...common} {...extra} />
    );

  return (
    <>
      {shape({
        strokeDasharray: dashed && p >= 1 ? '9 7' : 1,
        strokeDashoffset: p >= 1 ? 0 : 1 - p,
      })}
      {/* the pen head, only while the line is still being drawn */}
      {p < 1 ? shape({strokeWidth: w + 4, strokeDasharray: '0.045 0.955', strokeDashoffset: 0.045 - p}) : null}
    </>
  );
};

const Mono: React.FC<{
  x: number;
  y: number;
  f: number;
  start: number;
  size?: number;
  colour?: string;
  anchor?: 'start' | 'middle' | 'end';
  weight?: number;
  track?: string;
  children: React.ReactNode;
}> = ({x, y, f, start, size = 17, colour = B.ink, anchor = 'start', weight = 400, track = '0.06em', children}) => (
  <text
    x={x}
    y={y}
    fontFamily={font.mono}
    fontSize={size}
    fill={colour}
    textAnchor={anchor}
    fontWeight={weight}
    letterSpacing={track}
    opacity={ramp(f, start, 14)}
  >
    {children}
  </text>
);

/** A labelled block. Drawn, then filled. */
const Block: React.FC<{
  x: number;
  y: number;
  w: number;
  h: number;
  f: number;
  start: number;
  tag?: string;
  title: string;
  sub?: string;
  accent?: boolean;
  dashed?: boolean;
}> = ({x, y, w, h, f, start, tag, title, sub, accent, dashed}) => (
  <>
    <Draw rect={{x, y, w, h}} f={f} start={start} dur={30} colour={accent ? B.accent : B.line} width={accent ? 3 : 2.5} dashed={dashed} />
    {tag ? (
      <Mono x={x + 14} y={y + 24} f={f} start={start + 26} size={13} colour={B.soft} track="0.16em">
        {tag}
      </Mono>
    ) : null}
    <text
      x={x + 14}
      y={y + (tag ? 56 : 38)}
      fontFamily={font.sans}
      fontSize={26}
      fontWeight={640}
      fill={B.ink}
      letterSpacing="-0.015em"
      opacity={ramp(f, start + 28, 14)}
    >
      {title}
    </text>
    {sub ? (
      <Mono x={x + 14} y={y + (tag ? 84 : 66)} f={f} start={start + 32} size={15} colour={B.line}>
        {sub}
      </Mono>
    ) : null}
  </>
);

/** The sheet: border, grid, title block. Present the whole film. */
const Sheet: React.FC<{f: number; sheet: string; label: string}> = ({f, sheet, label}) => {
  const S = BLUEPRINT_SIZE;
  return (
    <>
      <defs>
        <pattern id="bpgrid" width="30" height="30" patternUnits="userSpaceOnUse">
          <circle cx="0" cy="0" r="1" fill={B.grid} />
        </pattern>
      </defs>
      <rect x={0} y={0} width={S} height={S} fill={B.paper} />
      <rect x={0} y={0} width={S} height={S} fill="url(#bpgrid)" opacity={ramp(f, 0, 30)} />

      <Draw rect={{x: 26, y: 26, w: S - 52, h: S - 52, r: 0}} f={f} start={0} dur={40} colour={B.line} width={2} />
      <Draw rect={{x: 36, y: 36, w: S - 72, h: S - 72, r: 0}} f={f} start={6} dur={40} colour={B.grid} width={1.5} />

      {/* title block, bottom right, like a real sheet */}
      <Draw
        d={`M ${S - 400} ${S - 118} H ${S - 36} M ${S - 400} ${S - 118} V ${S - 36}`}
        f={f}
        start={26}
        dur={22}
        colour={B.line}
        width={2}
      />
      <Mono x={S - 384} y={S - 92} f={f} start={44} size={22} weight={600} track="0.02em">
        {PRODUCT.name.toUpperCase()}
      </Mono>
      <Mono x={S - 384} y={S - 68} f={f} start={48} size={12} colour={B.soft} track="0.1em">
        LOCAL-FIRST AI ORCHESTRATOR
      </Mono>
      <Mono x={S - 384} y={S - 48} f={f} start={52} size={13} colour={B.soft} track="0.12em">
        {`SHEET ${sheet} · ${label}`}
      </Mono>

      {/* revision box, bottom left — the honest bit, on every frame */}
      <Mono x={44} y={S - 48} f={f} start={56} size={13} colour={B.soft} track="0.12em">
        {PRODUCT.status.toUpperCase()} · {PRODUCT.license}
      </Mono>
    </>
  );
};

/* ================================================================== */

/** 01 — the request path. A router that prefers not to route. */
const One: React.FC<{f: number}> = ({f}) => (
  <>
    <Sheet f={f} sheet="1/4" label="REQUEST PATH" />
    <Mono x={44} y={96} f={f} start={20} size={15} colour={B.accent} track="0.18em">
      FIG. 01
    </Mono>
    <text
      x={44}
      y={148}
      fontFamily={font.sans}
      fontSize={46}
      fontWeight={700}
      fill={B.ink}
      letterSpacing="-0.03em"
      opacity={ramp(f, 24, 18)}
    >
      One thread in. One thread back.
    </text>

    <Block x={44} y={214} w={250} h={80} f={f} start={40} title="You" sub="one question" />
    <Draw d="M 294 254 H 396" f={f} start={70} dur={12} />
    <Draw d="M 386 248 L 396 254 L 386 260" f={f} start={80} dur={6} />

    <Block x={396} y={200} w={300} h={108} f={f} start={78} tag="ENTRY POINT" title="Host agent" sub="the only thing you talk to" accent />

    {/* the decision — a real diamond, because this is a drawing */}
    <Draw d="M 546 340 L 646 400 L 546 460 L 446 400 Z" f={f} start={112} dur={26} />
    <Mono x={546} y={396} f={f} start={140} size={14} anchor="middle" colour={B.soft} track="0.1em">
      CAN IT DO
    </Mono>
    <Mono x={546} y={414} f={f} start={142} size={14} anchor="middle" colour={B.soft} track="0.1em">
      THIS ITSELF?
    </Mono>
    <Draw d="M 546 308 V 340" f={f} start={106} dur={8} />

    <Draw d="M 446 400 H 300 V 500" f={f} start={150} dur={16} />
    <Mono x={372} y={390} f={f} start={166} size={14} colour={B.green} track="0.12em">
      YES
    </Mono>
    <Block x={150} y={500} w={300} h={92} f={f} start={166} title="It answers" sub="routing is not the default" />

    <Draw d="M 646 400 H 792 V 500" f={f} start={176} dur={16} />
    <Mono x={700} y={390} f={f} start={192} size={14} colour={B.accent} track="0.12em">
      NO
    </Mono>
    <Block x={642} y={500} w={330} h={92} f={f} start={192} title="A spawn you raised" sub={SPAWNS.howMany} accent />

    <Draw d="M 300 592 V 660 H 806 V 592" f={f} start={198} dur={22} />
    <Draw d="M 546 660 V 700" f={f} start={216} dur={8} />
    <Block x={396} y={700} w={300} h={80} f={f} start={220} title="Back to you" sub="in the same thread" />

    <Mono x={44} y={820} f={f} start={214} size={16} colour={B.line}>
      {`— equip each one with ${SPAWNS.equip}`}
    </Mono>
  </>
);

/** 02 — the sandbox. The one diagram where a crossed-out arrow is the point. */
const Two: React.FC<{f: number}> = ({f}) => (
  <>
    <Sheet f={f} sheet="2/4" label="SANDBOX" />
    <Mono x={44} y={96} f={f} start={4} size={15} colour={B.accent} track="0.18em">
      FIG. 02
    </Mono>
    <text
      x={44}
      y={148}
      fontFamily={font.sans}
      fontSize={46}
      fontWeight={700}
      fill={B.ink}
      letterSpacing="-0.03em"
      opacity={ramp(f, 8, 18)}
    >
      Generated code gets no network.
    </text>

    {/* the boundary — dashed, because a boundary is a convention */}
    <Draw rect={{x: 44, y: 210, w: 560, h: 400}} f={f} start={22} dur={40} colour={B.line} width={2.5} dashed />
    <Mono x={60} y={240} f={f} start={62} size={14} colour={B.soft} track="0.16em">
      KERNEL SANDBOX · macOS SEATBELT
    </Mono>

    <Block x={90} y={276} w={330} h={104} f={f} start={66} tag="RUNS HERE" title="Generated code" sub="filesystem: scratch only" />

    {/* the denied route */}
    <Draw d="M 420 328 H 700" f={f} start={104} dur={16} colour={B.red} />
    <Draw d="M 546 306 L 588 350 M 588 306 L 546 350" f={f} start={122} dur={12} colour={B.red} width={4} />
    <Mono x={618} y={300} f={f} start={136} size={15} colour={B.red} track="0.1em">
      DENIED
    </Mono>

    <Block x={700} y={276} w={300} h={104} f={f} start={140} title="The internet" sub="not from in there" />

    {/* the only route out */}
    <Draw d="M 255 380 V 470 H 700 V 400" f={f} start={158} dur={26} colour={B.green} />
    <Draw d="M 694 410 L 700 400 L 706 410" f={f} start={182} dur={6} colour={B.green} />
    <Block x={150} y={470} w={420} h={104} f={f} start={186} tag="THE ONLY WAY OUT" title="Credential proxy" sub="raw tokens never enter" accent />

    <Draw d="M 44 660 H 1036" f={f} start={172} dur={26} colour={B.grid} width={1.5} />
    <Mono x={44} y={706} f={f} start={192} size={19} colour={B.ink}>
      {SAFETY.failsClosed}
    </Mono>
    <Mono x={44} y={742} f={f} start={204} size={16} colour={B.line}>
      — where the kernel sandbox is unavailable, execution stops
    </Mono>
    <Mono x={44} y={800} f={f} start={216} size={19} colour={B.ink}>
      {SAFETY.local}
    </Mono>
  </>
);

/** 03 — the gate, as a process flow with a branch that goes nowhere. */
const Three: React.FC<{f: number}> = ({f}) => (
  <>
    <Sheet f={f} sheet="3/4" label="PROMOTION GATE" />
    <Mono x={44} y={96} f={f} start={4} size={15} colour={B.accent} track="0.18em">
      FIG. 03
    </Mono>
    <text
      x={44}
      y={148}
      fontFamily={font.sans}
      fontSize={44}
      fontWeight={700}
      fill={B.ink}
      letterSpacing="-0.03em"
      opacity={ramp(f, 8, 18)}
    >
      It rewrites itself. Then it has to prove it.
    </text>

    <Block x={44} y={206} w={272} h={86} f={f} start={14} title="Run history" sub="what it actually did" />
    <Draw d="M 316 249 H 392" f={f} start={42} dur={10} />
    <Block x={392} y={206} w={272} h={86} f={f} start={48} title="A new prompt" sub="written by itself" />
    <Draw d="M 664 249 H 740" f={f} start={74} dur={10} />
    <Block
      x={740}
      y={192}
      w={296}
      h={114}
      f={f}
      start={80}
      tag="BOTH ARMS, SAME TASKS"
      title="Replay"
      sub="positions swapped"
      accent
    />

    <Draw d="M 888 306 V 356 H 600" f={f} start={110} dur={22} />
    <Draw d="M 610 350 L 600 356 L 610 362" f={f} start={130} dur={6} />

    {/* the threshold */}
    <Draw rect={{x: 70, y: 306, w: 530, h: 130}} f={f} start={134} dur={30} colour={B.accent} width={3} />
    <Mono x={86} y={336} f={f} start={162} size={14} colour={B.soft} track="0.16em">
      THRESHOLD
    </Mono>
    <text
      x={86}
      y={382}
      fontFamily={font.sans}
      fontSize={34}
      fontWeight={720}
      fill={B.ink}
      letterSpacing="-0.02em"
      opacity={ramp(f, 166, 14)}
    >
      {`≥ ${Math.round(GATE.winRate * 100)}% of ≥ ${GATE.minHoldout} held-out pairs`}
    </text>
    <Mono x={86} y={410} f={f} start={172} size={14} colour={B.line}>
      {GATE.dimensions.join(' · ')}
    </Mono>
    <Mono x={86} y={428} f={f} start={176} size={14} colour={B.line}>
      none of them may go backwards
    </Mono>

    {/* fail: a branch drawn to a stub, going nowhere */}
    <Draw d="M 190 436 V 504" f={f} start={182} dur={12} colour={B.red} />
    <Mono x={206} y={478} f={f} start={194} size={14} colour={B.red} track="0.12em">
      FAIL
    </Mono>
    <Draw d="M 110 504 H 270" f={f} start={192} dur={10} colour={B.red} width={3} />
    <Mono x={190} y={540} f={f} start={202} size={16} anchor="middle" colour={B.red}>
      discarded — you never see it
    </Mono>

    {/* pass */}
    <Draw d="M 470 436 V 604 H 596" f={f} start={198} dur={22} colour={B.green} />
    <Mono x={492} y={500} f={f} start={216} size={14} colour={B.green} track="0.12em">
      PASS
    </Mono>
    <Block x={596} y={560} w={440} h={88} f={f} start={216} title="Your inbox" sub="a readable diff, waiting" />

    <Draw d="M 816 648 V 694" f={f} start={244} dur={10} />
    <Draw rect={{x: 596, y: 694, w: 440, h: 88, r: 6}} f={f} start={250} dur={26} colour={B.accent} width={3} />
    <text
      x={816}
      y={748}
      fontFamily={font.sans}
      fontSize={33}
      fontWeight={720}
      fill={B.accent}
      textAnchor="middle"
      letterSpacing="-0.01em"
      opacity={ramp(f, 274, 14)}
    >
      You press Promote
    </text>

    {/* The two properties that make the number above mean anything. */}
    <Draw d="M 44 660 H 520" f={f} start={226} dur={20} colour={B.grid} width={1.5} />
    <Mono x={44} y={700} f={f} start={236} size={15} colour={B.line}>
      {GATE.holdoutEnforced}
    </Mono>
    <Mono x={44} y={726} f={f} start={243} size={15} colour={B.line}>
      {GATE.neverMerged}
    </Mono>
    <Mono x={44} y={752} f={f} start={250} size={15} colour={B.line}>
      {GATE.lengthGuard}
    </Mono>
  </>
);

/** 04 — the close. The sheet signs itself off. */
const Four: React.FC<{f: number}> = ({f}) => {
  const btn = ramp(f, 52, 24, Easing.bezier(0.16, 1.2, 0.3, 1));
  return (
    <>
      <Sheet f={f} sheet="4/4" label="GENERAL ARRANGEMENT" />
      <Mono x={44} y={96} f={f} start={4} size={15} colour={B.accent} track="0.18em">
        FIG. 04 — ASSEMBLED
      </Mono>

      <text
        x={44}
        y={250}
        fontFamily={font.sans}
        fontSize={92}
        fontWeight={760}
        fill={B.ink}
        letterSpacing="-0.05em"
        opacity={ramp(f, 10, 20)}
      >
        {PRODUCT.name}
      </text>
      <text
        x={44}
        y={306}
        fontFamily={font.sans}
        fontSize={30}
        fontWeight={500}
        fill={B.line}
        opacity={ramp(f, 18, 20)}
      >
        {PRODUCT.tagline}
      </text>

      <Draw d="M 44 348 H 1036" f={f} start={26} dur={26} colour={B.line} width={2} />

      {([
        ['01', 'One host agent', 'the only thing you talk to'],
        ['02', 'Spawns you raise', SPAWNS.howMany],
        ['03', 'Kernel sandbox', 'generated code, network denied'],
        ['04', 'Promotion gate', 'a held-out exam you sign off'],
        ['05', 'Second brain', 'every belief carries time'],
      ] as [string, string, string][]).map(([n, t, s], i) => {
        const y = 404 + i * 62;
        return (
          <React.Fragment key={n}>
            <Mono x={44} y={y} f={f} start={26 + i * 6} size={15} colour={B.accent} track="0.16em">
              {n}
            </Mono>
            <text
              x={100}
              y={y}
              fontFamily={font.sans}
              fontSize={28}
              fontWeight={640}
              fill={B.ink}
              letterSpacing="-0.015em"
              opacity={ramp(f, 28 + i * 6, 14)}
            >
              {t}
            </text>
            <Mono x={470} y={y} f={f} start={30 + i * 6} size={16} colour={B.line}>
              {s}
            </Mono>
          </React.Fragment>
        );
      })}

      <Draw d="M 44 740 H 1036" f={f} start={58} dur={22} colour={B.grid} width={1.5} />

      {/* the call to action, drawn like everything else */}
      <Draw rect={{x: 44, y: 782, w: 470, h: 84, r: 6}} f={f} start={52} dur={24} colour={B.ink} width={3} />
      <rect x={44} y={782} width={470} height={84} rx={6} fill={B.ink} opacity={btn} />
      <text
        x={279}
        y={834}
        fontFamily={font.sans}
        fontSize={31}
        fontWeight={680}
        fill={B.paper}
        textAnchor="middle"
        opacity={btn}
      >
        ↓ Download for macOS
      </text>
      <Mono x={540} y={818} f={f} start={76} size={16} colour={B.line}>
        {PRODUCT.platform}
      </Mono>
      <Mono x={540} y={844} f={f} start={80} size={16} colour={B.line}>
        {PRODUCT.repo}
      </Mono>
    </>
  );
};

/* ================================================================== */

/* Sheet 3 carries the argument the product stands on, so it gets the most
   frames. An earlier split gave it 230 for 370 frames of schedule and its flow
   simply never reached Promote. */
/* Each slot has to outlast its sheet's final cue plus a hold, or the last thing
   drawn never appears at all. Sheets 2 and 4 overran a previous split by 18 and
   8 frames — exactly the sort of fault that survives a still review and only
   shows up when you watch the file. */
const SHEETS = [
  {at: 0, C: One},     // last cue 214
  {at: 250, C: Two},   // last cue 216
  {at: 500, C: Three}, // last cue 250
  {at: 790, C: Four},  // last cue 80
];

export const Blueprint: React.FC = () => {
  const f = useCurrentFrame();
  let i = 0;
  for (let k = 0; k < SHEETS.length; k++) if (f >= SHEETS[k].at) i = k;
  const {at, C} = SHEETS[i];

  /**
   * Sheets change by being turned, not dissolved: the outgoing one slides off
   * left as the new one arrives. A cross-fade would put two drawings on top of
   * each other, and two overlaid technical drawings read as a printing error.
   */
  const turn = ramp(f, at - 10, 18, Easing.bezier(0.5, 0, 0.2, 1));

  return (
    <AbsoluteFill style={{background: B.paper, overflow: 'hidden'}}>
      <svg
        width={BLUEPRINT_SIZE}
        height={BLUEPRINT_SIZE}
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          transform: i === 0 ? undefined : `translateX(${(1 - turn) * 70}px)`,
          opacity: i === 0 ? 1 : turn,
        }}
      >
        <C f={f - at} />
      </svg>
    </AbsoluteFill>
  );
};
