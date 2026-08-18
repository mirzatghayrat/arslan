import React from 'react';
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {MOCKUPS, Mockup, type View} from './components/Mockup';

/**
 * Poll — "which outro ships?" social cut.
 *
 * The three first-run outro clips sit as numbered tiles on the photographed
 * MacBook's screen. One at a time, in order, a tile grows OUT of the laptop
 * to the centre of the frame, plays its full clip, and settles back into its
 * spot; after all three, a closing card asks for a vote in the comments.
 *
 * The grow/shrink is honest geometry: the tile's on-screen rectangle is
 * mapped through the same front-mockup projection the Mockup component uses,
 * so the card really does leave from — and return to — the pixels the tile
 * occupies on the glass. While a clip plays, the room dims underneath it.
 */

const FPS = 30;

/** The three candidates. Frame counts stay a hair under each file's true
 * length so the last OffthreadVideo seek never lands past the end. Stills:
 * `first` matches the clip's opening pixels (shown while the card grows),
 * `last` its closing pixels (shown while it shrinks back — no content jump),
 * `mid` its most recognisable moment (tiles + the vote card, because all
 * three OPEN on the same wizard page and would be indistinguishable). */
const CLIPS = [
  {n: 1, src: 'poll/v1.mp4', first: 'poll/v1-first.jpg', mid: 'poll/v1-mid.jpg', last: 'poll/v1-last.jpg', play: 284, aspect: 16 / 9},
  {n: 2, src: 'poll/v2.mp4', first: 'poll/v2-first.jpg', mid: 'poll/v2-mid.jpg', last: 'poll/v2-last.jpg', play: 238, aspect: 2944 / 1248},
  {n: 3, src: 'poll/v3.mp4', first: 'poll/v3-first.jpg', mid: 'poll/v3-mid.jpg', last: 'poll/v3-last.jpg', play: 238, aspect: 16 / 9},
] as const;

const INTRO = 66;
const GROW = 16;
const SHRINK = 16;
const REST = 8;
const END = 140;

const segLen = (i: number) => GROW + CLIPS[i].play + SHRINK + REST;
const segStart = (i: number) => INTRO + CLIPS.slice(0, i).reduce((a, _c, j) => a + segLen(j), 0);
export const POLL_FRAMES = segStart(3) + END;

/** ── palette: the wizard's, pinned to the clay footage ── */
const PAPER = '#efe9e2';
const INK = '#1d1d1f';
const MUTED = '#6e6a64';
const ACCENT = '#d9741a';

/** ── the fixed camera and the screen→frame projection under it ── */
const VIEW: View = {cx: 0.5, cy: 0.55, w: 1.0};
const SCREEN_W = 1600;
const SCREEN_H = 1106;

const q = MOCKUPS.front.quad;
const GX0 = (q.tl[0] + q.bl[0]) / 2;
const GX1 = (q.tr[0] + q.br[0]) / 2;
const GY0 = (q.tl[1] + q.tr[1]) / 2;
const GY1 = (q.bl[1] + q.br[1]) / 2;
const S = 1920 / (VIEW.w * 2048);
const TX = 960 - S * VIEW.cx * 2048;
const TY = 540 - S * VIEW.cy * 2048;

const screenToFrame = (u: number, v: number): [number, number] => [
  TX + S * (GX0 + (u / SCREEN_W) * (GX1 - GX0)),
  TY + S * (GY0 + (v / SCREEN_H) * (GY1 - GY0)),
];

/** ── tile geometry, in screen space ── */
const TILE_W = 448;
const TILE_H = 252;
const TILE_GAP = 44;
const TILES_X0 = (SCREEN_W - (3 * TILE_W + 2 * TILE_GAP)) / 2;
const TILE_Y = 470;

type Rect = {x: number; y: number; w: number; h: number};

const tileScreenRect = (i: number): Rect => ({
  x: TILES_X0 + i * (TILE_W + TILE_GAP),
  y: TILE_Y,
  w: TILE_W,
  h: TILE_H,
});

const tileFrameRect = (i: number): Rect => {
  const t = tileScreenRect(i);
  const [x0, y0] = screenToFrame(t.x, t.y);
  const [x1, y1] = screenToFrame(t.x + t.w, t.y + t.h);
  return {x: x0, y: y0, w: x1 - x0, h: y1 - y0};
};

/** Centre-stage rectangle for a clip, sized to its own aspect. */
const stageRect = (aspect: number): Rect => {
  const w = 1560;
  const h = w / aspect;
  return {x: (1920 - w) / 2, y: (1080 - h) / 2, w, h};
};

const lerpRect = (a: Rect, b: Rect, t: number): Rect => ({
  x: a.x + (b.x - a.x) * t,
  y: a.y + (b.y - a.y) * t,
  w: a.w + (b.w - a.w) * t,
  h: a.h + (b.h - a.h) * t,
});

/** ── the app shown on the glass ── */
const ScreenContent: React.FC<{frame: number; active: number | null; done: number}> = ({frame, active, done}) => (
  <AbsoluteFill style={{background: PAPER, fontFamily: 'Inter, sans-serif'}}>
    <div
      style={{
        position: 'absolute',
        top: 168,
        width: '100%',
        textAlign: 'center',
        color: INK,
        fontSize: 74,
        fontWeight: 650,
        letterSpacing: '-0.015em',
        opacity: interpolate(frame, [6, 26], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
      }}
    >
      Three outros. You pick.
    </div>
    <div
      style={{
        position: 'absolute',
        top: 278,
        width: '100%',
        textAlign: 'center',
        color: MUTED,
        fontSize: 38,
        opacity: interpolate(frame, [14, 34], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
      }}
    >
      watch all three, then vote in the comments
    </div>

    {CLIPS.map((c, i) => {
      const t = tileScreenRect(i);
      const pop = spring({frame: frame - (22 + i * 7), fps: FPS, config: {damping: 16, mass: 0.7}});
      const away = active === i; // the clip is out on stage — leave a dim well
      return (
        <React.Fragment key={c.n}>
          <div
            style={{
              position: 'absolute',
              left: t.x,
              top: t.y,
              width: t.w,
              height: t.h,
              borderRadius: 18,
              overflow: 'hidden',
              background: away ? 'rgba(29,29,31,0.08)' : '#fff',
              boxShadow: away ? 'inset 0 2px 10px rgba(29,29,31,0.18)' : '0 10px 30px rgba(35,28,20,0.18)',
              opacity: pop,
              transform: `scale(${0.92 + 0.08 * pop})`,
            }}
          >
            {/* a watched tile keeps its ENDING frame — a quiet "seen" marker */}
            {!away && (
              <Img
                src={staticFile(i < done ? c.last : c.first)}
                style={{width: '100%', height: '100%', objectFit: 'cover'}}
              />
            )}
          </div>
          <div
            style={{
              position: 'absolute',
              left: t.x,
              top: t.y + t.h + 22,
              width: t.w,
              textAlign: 'center',
              fontFamily: 'IBM Plex Mono, monospace',
              fontSize: 52,
              fontWeight: 600,
              color: active === i ? ACCENT : INK,
              opacity: pop,
            }}
          >
            {c.n}
          </div>
        </React.Fragment>
      );
    })}
  </AbsoluteFill>
);

/** One clip's grow → play → shrink pass, all in frame space. */
const StagePass: React.FC<{i: number}> = ({i}) => {
  const frame = useCurrentFrame();
  const c = CLIPS[i];
  const from = tileFrameRect(i);
  const to = stageRect(c.aspect);
  const playEnd = GROW + c.play;

  const growT = spring({frame, fps: FPS, config: {damping: 17, mass: 0.8}, durationInFrames: GROW});
  const shrinkT = spring({frame: frame - playEnd, fps: FPS, config: {damping: 17, mass: 0.8}, durationInFrames: SHRINK});
  const t = frame < playEnd ? growT : 1 - shrinkT;
  const r = lerpRect(from, to, t);

  const dim = interpolate(
    frame,
    [0, GROW, playEnd, playEnd + SHRINK],
    [0, 0.72, 0.72, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  const progress = interpolate(frame, [GROW, playEnd], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <>
      <AbsoluteFill style={{background: `rgba(16,9,3,${dim})`}} />
      <div
        style={{
          position: 'absolute',
          left: r.x,
          top: r.y,
          width: r.w,
          height: r.h,
          borderRadius: 14 + 8 * t,
          overflow: 'hidden',
          background: '#000',
          boxShadow: `0 ${18 + 30 * t}px ${50 + 60 * t}px rgba(10,5,1,${0.25 + 0.3 * t})`,
        }}
      >
        {/* stills during the moves — OPENING pixels on the way out, CLOSING
            pixels on the way back, so neither hand-off jumps content — and the
            real clip in between, premounted through the grow so its first
            frame is decoded before it has to move */}
        {frame < GROW && (
          <Img src={staticFile(c.first)} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} />
        )}
        {frame >= playEnd && (
          <Img src={staticFile(c.last)} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} />
        )}
        {frame < playEnd && (
          <Sequence from={GROW} durationInFrames={c.play} premountFor={GROW} layout="none">
            <OffthreadVideo
              src={staticFile(c.src)}
              muted
              style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
            />
          </Sequence>
        )}
        {/* played fraction, so a viewer feels the clip's length */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            bottom: 0,
            height: 6,
            width: `${progress * 100}%`,
            background: ACCENT,
            opacity: t,
          }}
        />
      </div>
      {/* the candidate's number rides the card */}
      <div
        style={{
          position: 'absolute',
          left: r.x + 24,
          top: r.y + 20,
          minWidth: 64,
          padding: '6px 18px',
          borderRadius: 999,
          background: ACCENT,
          color: '#fff',
          fontFamily: 'IBM Plex Mono, monospace',
          fontSize: 40,
          fontWeight: 600,
          textAlign: 'center',
          opacity: t,
        }}
      >
        {c.n}
      </div>
    </>
  );
};

/** Closing card: the ask. */
const EndCard: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: 'clamp'});
  const up = (d: number) =>
    spring({frame: frame - d, fps: FPS, config: {damping: 15, mass: 0.7}});

  return (
    <AbsoluteFill style={{background: PAPER, opacity: fadeIn, fontFamily: 'Inter, sans-serif'}}>
      <div
        style={{
          position: 'absolute',
          top: 150,
          width: '100%',
          textAlign: 'center',
          color: INK,
          fontSize: 96,
          fontWeight: 650,
          letterSpacing: '-0.015em',
          opacity: up(4),
          transform: `translateY(${(1 - up(4)) * 30}px)`,
        }}
      >
        Which one?
      </div>
      <div
        style={{
          position: 'absolute',
          top: 292,
          width: '100%',
          textAlign: 'center',
          color: MUTED,
          fontSize: 44,
          opacity: up(10),
          transform: `translateY(${(1 - up(10)) * 30}px)`,
        }}
      >
        评论区告诉我：你喜欢哪一个？
      </div>

      {CLIPS.map((c, i) => {
        const w = 460;
        const h = 259;
        const gap = 60;
        const x0 = (1920 - (3 * w + 2 * gap)) / 2 + i * (w + gap);
        const s = up(16 + i * 6);
        return (
          <React.Fragment key={c.n}>
            <div
              style={{
                position: 'absolute',
                left: x0,
                top: 430,
                width: w,
                height: h,
                borderRadius: 20,
                overflow: 'hidden',
                boxShadow: '0 16px 44px rgba(35,28,20,0.2)',
                opacity: s,
                transform: `scale(${0.9 + 0.1 * s})`,
              }}
            >
              <Img src={staticFile(c.mid)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
            </div>
            <div
              style={{
                position: 'absolute',
                left: x0,
                top: 430 + h + 28,
                width: w,
                textAlign: 'center',
                fontFamily: 'IBM Plex Mono, monospace',
                fontSize: 72,
                fontWeight: 600,
                color: ACCENT,
                opacity: s,
              }}
            >
              {c.n}
            </div>
          </React.Fragment>
        );
      })}

      <div
        style={{
          position: 'absolute',
          bottom: 96,
          width: '100%',
          textAlign: 'center',
          color: INK,
          fontSize: 46,
          fontWeight: 600,
          opacity: up(30),
        }}
      >
        Comment below — 1 · 2 · 3
      </div>
    </AbsoluteFill>
  );
};

export const Poll: React.FC = () => {
  const frame = useCurrentFrame();
  useVideoConfig(); // assert we're inside a composition

  const active = CLIPS.findIndex(
    (_c, i) => frame >= segStart(i) && frame < segStart(i) + GROW + CLIPS[i].play + SHRINK,
  );
  const done = CLIPS.filter((_c, i) => frame >= segStart(i) + segLen(i) - REST).length;

  return (
    <AbsoluteFill style={{background: '#0d0501'}}>
      <Mockup mockup="front" view={VIEW}>
        <ScreenContent frame={frame} active={active === -1 ? null : active} done={done} />
      </Mockup>

      {CLIPS.map((_c, i) => (
        <Sequence key={i} from={segStart(i)} durationInFrames={segLen(i)} layout="none">
          <StagePass i={i} />
        </Sequence>
      ))}

      <Sequence from={segStart(3)} durationInFrames={END} layout="none">
        <EndCard />
      </Sequence>
    </AbsoluteFill>
  );
};
