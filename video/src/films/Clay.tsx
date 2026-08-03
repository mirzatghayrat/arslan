import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Freeze,
  Img,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {GATE, MASTHEAD, PRODUCT, PROMISE_GUARD, SAFETY, SPAWNS} from '../facts';
import {font} from '../theme';

/**
 * FILM 13 — "CLAY". Two 15-second H3 generations fused into a minute, with the
 * claymation world leading and the captions carrying the whole story.
 *
 * THE MATERIAL, measured before cutting:
 *
 *  - `clay/world.mp4` — a claymation build-up: flat tiles, blobs rising into
 *    labelled blocks, a working factory with conveyors, then a purple ground
 *    with a download card. The lettering pressed into the clay blocks is
 *    pseudo-text ("Deplnyment", "Cneterchill"), and the film treats it the way
 *    it reads: as sculpture texture in a metaphor world. Nothing in these shots
 *    claims to be the interface, which is what separates them from…
 *  - `clay/reveal.mp4` — the ceramic cat on the circuit wall, then a pull-back
 *    that finds the cat ON a laptop screen. Usable until 6.3s; from 6.6s the
 *    laptop shows a generated light-mode interface, which fails the same test
 *    every hallucinated screen fails here — it looks like Arslan and reads as
 *    nonsense — so the film never reaches it.
 *  - The baked end card spells it "macOs", so it is excluded too. The frame at
 *    12.42s, where the button is still an unformed blob, is frozen instead
 *    (`clay/end-bg.jpg`) and the real call to action is typeset over it —
 *    generated clay, true text, which is this film's whole method in one shot.
 *
 * THE NARRATIVE is complete in the facts.ts sense — every claim the product
 * makes on screen, in order: what it is → one host agent → spawns you raised →
 * as many as you raise, equipped with tools/skills/MCP → the held-out exam and
 * Promote → the promise guard → local-first → off by default → download. The
 * two chapters footage cannot honestly carry (the exam, the guard) are drawn
 * as clay-styled cards in the footage's own palette rather than faked as film.
 */

export const CLAY_FRAMES = 1800; // 60s at 30fps
export const CLAY_W = 2560;
export const CLAY_H = 1440;

/** Sampled from the footage, not invented. */
const C = {
  purple: '#6C5FC7',
  purpleDeep: '#4E4494',
  yellow: '#EFC153',
  blue: '#4A72C4',
  terra: '#B65138',
  cream: '#F2E7D5',
  brown: '#4A2E0E',
  ink: '#F5EFE4',
};

const EASE = Easing.bezier(0.33, 0, 0.16, 1);
const ramp = (f: number, s: number, l: number, e = EASE) =>
  interpolate(f, [s, s + l], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: e,
  });

/* ================================================================== */
/* Footage                                                             */

/**
 * Play a source range, then hold its last frame, with a slow drift over the
 * whole segment so the hold never reads as a freeze. `from`/`play` in seconds
 * of source time; the Freeze clamp is what turns overrun into a hold.
 */
const Clip: React.FC<{
  src: string;
  f: number;
  from: number;
  play: number;
  drift?: number;
  scale?: number;
  origin?: string;
}> = ({src, f, from, play, drift = 0.04, scale = 1, origin = '50% 50%'}) => {
  const playF = Math.round(play * 30);
  const k = scale * (1 + drift * Math.min(1, f / 170));
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: '#191233'}}>
      <AbsoluteFill style={{transform: `scale(${k})`, transformOrigin: origin}}>
        <Freeze frame={Math.min(f, playF - 1)}>
          <OffthreadVideo
            src={staticFile(src)}
            muted
            startFrom={Math.round(from * 30)}
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        </Freeze>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** One caption pill, bottom centre — soft and rounded like everything else. */
const Cap: React.FC<{f: number; at: number; lines: string[]}> = ({f, at, lines}) => {
  const o = ramp(f, at, 30);
  if (o <= 0.01) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: 110,
        display: 'flex',
        justifyContent: 'center',
        opacity: o,
        transform: `translateY(${(1 - o) * 20}px)`,
      }}
    >
      <div
        style={{
          background: 'rgba(24,17,48,0.66)',
          borderRadius: 999,
          padding: '26px 58px',
          textAlign: 'center',
          fontFamily: font.sans,
          fontSize: 44,
          lineHeight: 1.4,
          color: C.ink,
          boxShadow: '0 18px 60px rgba(0,0,0,0.35)',
        }}
      >
        {lines.map((l) => (
          <div key={l}>{l}</div>
        ))}
      </div>
    </div>
  );
};

/** The repo's standing rule: generated imagery says so while it is on screen. */
const Prov: React.FC = () => (
  <div
    style={{
      position: 'absolute',
      right: 84,
      bottom: 52,
      fontFamily: font.mono,
      fontSize: 24,
      letterSpacing: '0.1em',
      color: 'rgba(245,239,228,0.32)',
    }}
  >
    GENERATED IMAGERY
  </div>
);

/* ================================================================== */
/* Chapter cards — the clay look, rebuilt in CSS                       */

/**
 * A slab reads as clay through three shadows: a top-left inner highlight (the
 * sheen), a bottom-right inner shade (the thumb-pressed edge), and a long soft
 * outer drop. Flat colour with rounded corners alone reads as UI, which is the
 * one thing this film must not accidentally resemble.
 */
const Slab: React.FC<{
  f: number;
  bg: string;
  slab: string;
  children: React.ReactNode;
}> = ({f, bg, slab, children}) => {
  const on = ramp(f, 4, 34);
  return (
    <AbsoluteFill style={{background: bg, overflow: 'hidden'}}>
      <AbsoluteFill
        style={{
          background: `radial-gradient(70% 90% at 38% 30%, rgba(255,255,255,0.12) 0%, rgba(0,0,0,0) 60%), radial-gradient(120% 120% at 80% 100%, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0) 55%)`,
        }}
      />
      {/* clay pebbles, so the set is not empty around the slab */}
      {[
        {x: 260, y: 1120, r: 74, c: 'rgba(255,255,255,0.16)'},
        {x: 2260, y: 260, r: 54, c: 'rgba(0,0,0,0.14)'},
        {x: 2380, y: 1180, r: 96, c: 'rgba(255,255,255,0.10)'},
      ].map((p, i) => (
        <div
          key={i}
          style={{
            position: 'absolute',
            left: p.x - p.r,
            top: p.y - p.r,
            width: p.r * 2,
            height: p.r * 2,
            borderRadius: '50%',
            background: p.c,
            boxShadow: 'inset 6px 8px 16px rgba(255,255,255,0.25), inset -8px -10px 18px rgba(0,0,0,0.18)',
            opacity: on,
          }}
        />
      ))}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div
          style={{
            width: 1860,
            borderRadius: 64,
            padding: '96px 110px',
            background: slab,
            transform: `rotate(-1.2deg) scale(${1.1 - 0.1 * on})`,
            opacity: Math.min(1, on * 2),
            filter: `blur(${(1 - on) * 16}px)`,
            boxShadow:
              'inset 10px 12px 28px rgba(255,255,255,0.38), inset -12px -16px 34px rgba(0,0,0,0.16), 34px 48px 90px rgba(0,0,0,0.32)',
          }}
        >
          {children}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

const Line: React.FC<{f: number; at: number; children: React.ReactNode; style?: React.CSSProperties}> = ({
  f,
  at,
  children,
  style,
}) => {
  const o = ramp(f, at, 28);
  return (
    <div style={{opacity: o, transform: `translateY(${(1 - o) * 16}px)`, ...style}}>
      {children}
    </div>
  );
};

/* ================================================================== */
/* Beats                                                               */

const Open: React.FC<{f: number}> = ({f}) => {
  const t = ramp(f, 58, 34);
  return (
    <AbsoluteFill>
      <Clip src="clay/world.mp4" f={f} from={0} play={5.6} drift={0} />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 400,
          textAlign: 'center',
          opacity: t,
          transform: `scale(${1.08 - 0.08 * t})`,
          filter: `blur(${(1 - t) * 14}px)`,
        }}
      >
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 170,
            fontWeight: 730,
            letterSpacing: '-0.045em',
            color: C.ink,
            textShadow: '0 14px 70px rgba(20,10,50,0.75)',
          }}
        >
          {PRODUCT.name}
        </div>
        <div
          style={{
            marginTop: 14,
            fontFamily: font.mono,
            fontSize: 38,
            letterSpacing: '0.22em',
            color: C.ink,
            opacity: 0.85,
            textShadow: '0 8px 40px rgba(20,10,50,0.8)',
          }}
        >
          {PRODUCT.tagline.toUpperCase()}
        </div>
      </div>
      <Prov />
    </AbsoluteFill>
  );
};

const CatWall: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    <Clip src="clay/reveal.mp4" f={f} from={0} play={3.5} />
    <Cap f={f} at={40} lines={[PRODUCT.what]} />
    <Prov />
  </AbsoluteFill>
);

const Reveal: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    <Clip src="clay/reveal.mp4" f={f} from={3.5} play={2.8} drift={0.03} />
    <Cap f={f} at={50} lines={[MASTHEAD.a]} />
    <Prov />
  </AbsoluteFill>
);

const City: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    {/* stops at 6.4s: the hold lands on the wide city rather than on the first
        frame of the Deployment macro, which beat 8 then plays in full — holding
        it here showed the same framing twice, captioned differently */}
    <Clip src="clay/world.mp4" f={f} from={4.6} play={1.8} />
    <Cap f={f} at={36} lines={[MASTHEAD.b]} />
    <Prov />
  </AbsoluteFill>
);

const Factory: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    {/* stops at 11.55s. The source leaves the factory for its own end card at
        about 11.9 — the first retime (to 13.0) froze the card, misspelling and
        all, under this caption for four seconds; the second (12.3) froze the
        blank card. 11.55 was verified sharp: mid-motion frames either side of
        it carry the whip-pan's blur. */}
    <Clip src="clay/world.mp4" f={f} from={11.0} play={0.55} />
    <Cap f={f} at={36} lines={[`Spawns: ${SPAWNS.howMany}`, SPAWNS.equip]} />
    <Prov />
  </AbsoluteFill>
);

const GateCard: React.FC<{f: number}> = ({f}) => (
  <Slab f={f} bg={C.blue} slab={C.yellow}>
    <Line
      f={f}
      at={26}
      style={{
        fontFamily: font.mono,
        fontSize: 34,
        letterSpacing: '0.2em',
        color: 'rgba(74,46,14,0.7)',
      }}
    >
      SELF-EVOLUTION, WITH AN EXAM
    </Line>
    <Line
      f={f}
      at={44}
      style={{
        marginTop: 34,
        fontFamily: font.sans,
        fontSize: 74,
        fontWeight: 700,
        lineHeight: 1.18,
        letterSpacing: '-0.02em',
        color: C.brown,
      }}
    >
      Prompts improve on their own — but every change must pass a held-out exam.
    </Line>
    <Line
      f={f}
      at={78}
      style={{marginTop: 44, fontFamily: font.mono, fontSize: 37, color: 'rgba(74,46,14,0.85)'}}
    >
      win ≥ {GATE.winRate * 100}% on {GATE.minHoldout}+ held-out tasks · judged blind, positions
      swapped
    </Line>
    <Line
      f={f}
      at={104}
      style={{marginTop: 40, fontFamily: font.sans, fontSize: 52, fontWeight: 700, color: C.brown}}
    >
      Nothing ships until you press Promote.
    </Line>
  </Slab>
);

const GuardCard: React.FC<{f: number}> = ({f}) => (
  <Slab f={f} bg={C.terra} slab={C.cream}>
    <Line
      f={f}
      at={26}
      style={{
        fontFamily: font.mono,
        fontSize: 34,
        letterSpacing: '0.2em',
        color: 'rgba(58,36,24,0.65)',
      }}
    >
      THE PROMISE GUARD
    </Line>
    <Line
      f={f}
      at={44}
      style={{
        marginTop: 40,
        fontFamily: font.sans,
        fontSize: 62,
        fontStyle: 'italic',
        lineHeight: 1.25,
        color: 'rgba(58,36,24,0.55)',
      }}
    >
      “{PROMISE_GUARD.lie}”
    </Line>
    <Line
      f={f}
      at={86}
      style={{marginTop: 40, fontFamily: font.mono, fontSize: 48, fontWeight: 700, color: C.terra}}
    >
      {PROMISE_GUARD.truth}
    </Line>
    <Line
      f={f}
      at={118}
      style={{
        marginTop: 44,
        fontFamily: font.sans,
        fontSize: 58,
        fontWeight: 720,
        color: '#3A2418',
      }}
    >
      {PROMISE_GUARD.claim}
    </Line>
  </Slab>
);

const Macro: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    <Clip src="clay/world.mp4" f={f} from={7.0} play={4.0} drift={0.02} />
    <Cap f={f} at={40} lines={[SAFETY.local]} />
    <Prov />
  </AbsoluteFill>
);

const Chest: React.FC<{f: number}> = ({f}) => (
  <AbsoluteFill>
    <Clip src="clay/reveal.mp4" f={f} from={0.6} play={2.9} scale={1.7} origin="50% 62%" drift={0.03} />
    <Cap f={f} at={40} lines={['Everything that can spend or write is off by default.']} />
    <Prov />
  </AbsoluteFill>
);

/**
 * The close: the footage's own end card, frozen at 12.42s — before the baked
 * button has formed its (misspelled) lettering — with the real call to action
 * typeset onto the clay. The pill sits exactly over the half-formed blob.
 */
const End: React.FC<{f: number}> = ({f}) => {
  const k = 1 + 0.03 * ramp(f, 0, 300, Easing.bezier(0.3, 0, 0.5, 1));
  const title = ramp(f, 20, 34);
  const pill = ramp(f, 48, 34);
  const meta = ramp(f, 76, 30);
  return (
    <AbsoluteFill style={{overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: `scale(${k})`}}>
        <Img src={staticFile('clay/end-bg.jpg')} style={{width: '100%', height: '100%'}} />
        {/* The baked button was caught mid-formation at 12.42s — a half-shaped
            purple blob reading "Down". Smoothed over with a soft-edged patch in
            the slab's own sampled colours (#c9a55b centre, lit toward #cba968),
            as if the clay had been thumbed flat before our type goes on. Inside
            the scaled layer so it rides the same slow zoom as the photograph. */}
        <div
          style={{
            position: 'absolute',
            left: 1270 - 330,
            top: 725 - 240,
            width: 660,
            height: 480,
            background:
              'radial-gradient(closest-side, #c7a254 0%, #c7a254 58%, rgba(199,162,84,0.85) 76%, rgba(199,162,84,0) 100%)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 1270 - 330,
            top: 725 - 240,
            width: 660,
            height: 480,
            borderRadius: '50%',
            background:
              'linear-gradient(135deg, rgba(255,235,190,0.10) 0%, rgba(255,235,190,0) 45%, rgba(90,60,20,0.06) 100%)',
          }}
        />
      </AbsoluteFill>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 470,
          textAlign: 'center',
          opacity: title,
          transform: `translateY(${(1 - title) * 22}px)`,
        }}
      >
        <div
          style={{
            fontFamily: font.sans,
            fontSize: 150,
            fontWeight: 730,
            letterSpacing: '-0.045em',
            color: C.brown,
          }}
        >
          {PRODUCT.name}
        </div>
        <div
          style={{
            marginTop: 6,
            fontFamily: font.mono,
            fontSize: 33,
            letterSpacing: '0.2em',
            color: 'rgba(74,46,14,0.65)',
          }}
        >
          {PRODUCT.tagline.toUpperCase()}
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 830,
          display: 'flex',
          justifyContent: 'center',
          opacity: pill,
          transform: `translateY(${(1 - pill) * 18}px)`,
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 20,
            padding: '30px 64px',
            borderRadius: 999,
            background: C.purple,
            color: C.cream,
            fontFamily: font.sans,
            fontSize: 52,
            fontWeight: 700,
            boxShadow:
              'inset 6px 8px 18px rgba(255,255,255,0.28), inset -8px -10px 20px rgba(0,0,0,0.22), 18px 26px 50px rgba(40,20,0,0.35)',
          }}
        >
          <span>↓</span> Download for macOS
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 1010,
          textAlign: 'center',
          fontFamily: font.mono,
          fontSize: 30,
          letterSpacing: '0.06em',
          color: 'rgba(74,46,14,0.62)',
          opacity: meta,
        }}
      >
        {PRODUCT.platform} · {PRODUCT.license} · {PRODUCT.status}
      </div>
      <Prov />
    </AbsoluteFill>
  );
};

/* ================================================================== */

const BEATS: {at: number; C: React.FC<{f: number}>}[] = [
  {at: 0, C: Open},
  {at: 170, C: CatWall},
  {at: 330, C: Reveal},
  {at: 490, C: City},
  {at: 660, C: Factory},
  {at: 830, C: GateCard},
  {at: 1010, C: GuardCard},
  {at: 1190, C: Macro},
  {at: 1350, C: Chest},
  {at: 1480, C: End},
];

/** The F8 grammar, kept: every seam is a bloomed defocus, never a cut. */
const OVER = 26;
const entering = (t: number): React.CSSProperties => ({
  opacity: Math.min(1, t * 2.2),
  transform: `scale(${1.035 - 0.035 * t})`,
  filter: `blur(${(1 - t) * 18}px) brightness(${1 + (1 - t) * 1.2})`,
});
const leaving = (t: number): React.CSSProperties => ({
  opacity: 1 - Math.min(1, t * 1.7),
  transform: `scale(${1 - 0.03 * t})`,
  filter: `blur(${t * 20}px) brightness(${1 + t * 1.4})`,
});

export const Clay: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: '#191233'}}>
      {BEATS.map((b, i) => {
        const next = BEATS[i + 1];
        const end = next ? next.at + OVER : CLAY_FRAMES;
        if (f < b.at || f >= end) return null;
        const inT = i === 0 ? 1 : ramp(f, b.at, OVER);
        const outT = next ? ramp(f, next.at, OVER) : 0;
        const style = outT > 0 ? leaving(outT) : inT < 1 ? entering(inT) : {};
        return (
          <AbsoluteFill key={b.at} style={style}>
            <b.C f={f - b.at} />
          </AbsoluteFill>
        );
      })}
    </AbsoluteFill>
  );
};
