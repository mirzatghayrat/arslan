import React from 'react';
import {
  AbsoluteFill,
  Freeze,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {ScreenBrain, ScreenPromotion, ScreenThread} from './components/AppScreen';
import {MacBook, SCREEN} from './components/MacBook';
import {Stage} from './components/Stage';
import {arrive, glide, type CamKey} from './lib/camera3d';
import {CHARACTER, light} from './lightTheme';
import {font} from './theme';

/**
 * WORK IN PROGRESS — the framing is being signed off from `ShotMock` stills
 * before this is rendered again. Superseded in one respect already: an earlier
 * pass laid captions over the machine, which made the shots read as hardware
 * promos rather than as the app. All product copy now lives on the screen; the
 * only type in world space is the closing CTA, and it sits in clear frame
 * beside the machine, never across it.
 *
 * The 30-second cut. One continuous camera move from the character filling the
 * frame out to the machine on a desk and finally to the download.
 *
 * Deliberately NOT a sequence of scenes. The previous version cross-faded
 * between flat compositions, which is why it read as slides: nothing persisted
 * across a cut, so there was no space for the viewer to stay oriented in. Here
 * there is one room, one camera, and one machine; the "cuts" are the app
 * changing view on a screen that never leaves frame.
 */

export const SHORT_FRAMES = 900;

/** Where the hero laptop's display sits in the world. Derived from its lean. */
const HERO_SCREEN: [number, number, number] = [0, -653, -139];

/**
 * The camera track. `dist` is a real distance, so 1560 is "closer than the
 * screen is wide" — i.e. inside it — and the opening frame is full bleed
 * without a hand-tuned scale.
 */
const CAM: CamKey[] = [
  {frame: 0, target: HERO_SCREEN, dist: 1560, yaw: 0, pitch: 0},
  // Barely creeping in. Enough that the opening is not a freeze frame.
  {frame: 96, target: HERO_SCREEN, dist: 1508, yaw: 0, pitch: 0},
  // The reveal: bezel, lid, deck, desk. The longest move in the film.
  {frame: 268, target: [0, -560, 40], dist: 5400, yaw: -9, pitch: 10},
  {frame: 340, target: [0, -560, 60], dist: 5240, yaw: -6, pitch: 10},
  // Orbit around to the other cheek while the app changes view.
  {frame: 486, target: [40, -545, 90], dist: 4680, yaw: 21, pitch: 13},
  {frame: 574, target: [40, -545, 90], dist: 4640, yaw: 23, pitch: 13},
  // Back off; the second machine is already standing there when we arrive.
  {frame: 712, target: [640, -520, 240], dist: 8700, yaw: 8, pitch: 15},
  // Final pull back, drifting right so the left of frame opens up for the CTA.
  {frame: 856, target: [1560, -470, 300], dist: 11400, yaw: 4, pitch: 12},
  {frame: 900, target: [1560, -470, 300], dist: 11400, yaw: 4, pitch: 12},
];

/** Cross-dissolve helper for the screen's own view changes. */
const view = (frame: number, inAt: number, outAt: number, fade = 26) =>
  interpolate(
    frame,
    [inAt, inAt + fade, outAt, outAt + fade],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: glide},
  );

const HeroScreen: React.FC<{frame: number}> = ({frame}) => (
  <AbsoluteFill style={{background: light.background}}>
    {/* The character clip, filling the display. */}
    <AbsoluteFill style={{opacity: view(frame, -40, 296)}}>
      <Freeze frame={Math.min(frame, CHARACTER.frames - 1)}>
        <OffthreadVideo
          src={staticFile(CHARACTER.src)}
          muted
          style={{width: SCREEN.w, height: SCREEN.h, objectFit: 'cover'}}
        />
      </Freeze>
    </AbsoluteFill>

    <AbsoluteFill style={{opacity: view(frame, 300, 474)}}>
      <ScreenThread frame={frame - 300} />
    </AbsoluteFill>

    <AbsoluteFill style={{opacity: view(frame, 478, 664)}}>
      <ScreenPromotion frame={frame - 478} />
    </AbsoluteFill>

    <AbsoluteFill style={{opacity: view(frame, 668, 1200)}}>
      <ScreenBrain frame={frame - 668} />
    </AbsoluteFill>
  </AbsoluteFill>
);

const CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [790, 826], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: arrive,
  });
  const rise = interpolate(frame, [790, 840], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: arrive,
  });
  const btn = interpolate(frame, [816, 852], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: arrive,
  });

  return (
    <div
      style={{
        position: 'absolute',
        left: 132,
        top: 300,
        width: 640,
        fontFamily: font.sans,
        opacity: o,
        transform: `translateY(${rise * 26}px)`,
      }}
    >
      <div
        style={{
          fontSize: 86,
          fontWeight: 650,
          letterSpacing: '-0.04em',
          color: light.ink,
          lineHeight: 1.04,
        }}
      >
        Arslan
      </div>
      <div
        style={{
          marginTop: 18,
          fontSize: 27,
          color: light.muted,
          lineHeight: 1.42,
          maxWidth: 520,
        }}
      >
        One host agent. Spawns you raised. Nothing ships until you press
        Promote.
      </div>

      <div
        style={{
          marginTop: 40,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 16,
          background: light.ink,
          color: '#fff',
          borderRadius: 999,
          padding: '20px 38px',
          fontSize: 25,
          fontWeight: 600,
          letterSpacing: '-0.01em',
          opacity: btn,
          transform: `translateY(${(1 - btn) * 14}px) scale(${0.96 + btn * 0.04})`,
          boxShadow: '0 18px 44px rgba(15,23,42,0.24)',
        }}
      >
        <span style={{fontSize: 23}}>↓</span>
        Download for macOS
      </div>

      <div
        style={{
          marginTop: 18,
          fontFamily: font.mono,
          fontSize: 15,
          color: light.subtle,
          letterSpacing: '0.06em',
          opacity: btn,
        }}
      >
        macOS 11+ · Apple Silicon · signed &amp; notarized
      </div>
    </div>
  );
};

export const ArslanShort: React.FC = () => {
  const frame = useCurrentFrame();

  // The second machine is already on the desk; it just has not been in shot.
  // Fading it in as the camera arrives keeps it from popping into an empty
  // patch of desk.
  const second = interpolate(frame, [612, 690], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

  return (
    <Stage
      frame={frame}
      keys={CAM}
      easing={arrive}
      overlay={<CTA />}
    >
      <MacBook position={[0, 0, 0]} yaw={0}>
        <HeroScreen frame={frame} />
      </MacBook>

      <MacBook
        position={[2760, 0, 620]}
        yaw={-26}
        scale={0.92}
        opacity={second}
        shadow={0.45 * second}
      >
        <ScreenBrain frame={frame - 640} />
      </MacBook>
    </Stage>
  );
};
