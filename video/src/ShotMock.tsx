import React from 'react';
import {AbsoluteFill, Freeze, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {ScreenBrain, ScreenPromotion, ScreenThread} from './components/AppScreen';
import {MacBook, SCREEN} from './components/MacBook';
import {ENVIRONMENTS, Stage, type EnvName} from './components/Stage';
import type {CamKey} from './lib/camera3d';
import {CHARACTER} from './lightTheme';
import {font} from './theme';

/**
 * One frame per shot. Lets a framing be rendered with `remotion still` and
 * looked at before any of it is committed to a 900-frame render.
 *
 * Screen centre for the current geometry: the lid is 1336 tall and leans back
 * 12 degrees, so its midpoint sits at y = -1336/2 * cos12 and z = -1336/2 *
 * sin12.
 */
const HERO: [number, number, number] = [0, -653, -139];

type Content = 'cat' | 'thread' | 'promotion' | 'brain';

type Shot = {
  id: string;
  note: string;
  env: EnvName;
  cam: CamKey;
  content: Content;
  /** Frame fed to the screen's own animation. */
  at: number;
  cta?: boolean;
  second?: boolean;
};

const SHOTS: Shot[] = [
  {
    id: 'A',
    note: 'Open — the character fills the frame. No laptop yet, no type.',
    env: 'studio',
    cam: {frame: 0, target: HERO, dist: 1500, yaw: 0, pitch: 0},
    content: 'cat',
    at: 60,
  },
  {
    id: 'B',
    note: 'Mid pull-back — the bezel arrives and it turns out to be a screen.',
    env: 'studio',
    cam: {frame: 0, target: [0, -624, -60], dist: 2620, yaw: -3, pitch: 4},
    content: 'cat',
    at: 92,
  },
  {
    id: 'C',
    note: 'Reveal settles — machine on the desk, character still playing.',
    env: 'studio',
    cam: {frame: 0, target: [0, -566, 120], dist: 4700, yaw: -7, pitch: 8},
    content: 'cat',
    at: 106,
  },
  {
    id: 'D',
    note: 'Same framing, warm environment. Arslan amber used as the key light.',
    env: 'amber',
    cam: {frame: 0, target: [0, -566, 120], dist: 4700, yaw: -7, pitch: 8},
    content: 'cat',
    at: 106,
  },
  {
    id: 'E',
    note: 'Three-quarter — the app is on the screen. Nothing written on the machine.',
    env: 'studio',
    cam: {frame: 0, target: [0, -570, 110], dist: 4300, yaw: 19, pitch: 9},
    content: 'thread',
    at: 150,
  },
  {
    id: 'F',
    note: 'Same shot, warm environment.',
    env: 'amber',
    cam: {frame: 0, target: [0, -570, 110], dist: 4300, yaw: 19, pitch: 9},
    content: 'thread',
    at: 150,
  },
  {
    id: 'G',
    note: 'Promotion gate, pushed a little closer so the exam is readable.',
    env: 'studio',
    cam: {frame: 0, target: [0, -600, 40], dist: 3500, yaw: -12, pitch: 8},
    content: 'promotion',
    at: 150,
  },
  {
    id: 'H',
    note: 'Two machines. The camera has backed off; both are on the same desk.',
    env: 'studio',
    cam: {frame: 0, target: [760, -520, 300], dist: 8200, yaw: 7, pitch: 14},
    content: 'brain',
    at: 150,
    second: true,
  },
  {
    id: 'I',
    note: 'Close — machine right, CTA in clear space at left. Copy never on the hardware.',
    env: 'studio',
    cam: {frame: 0, target: [-1180, -520, 300], dist: 9200, yaw: 5, pitch: 12},
    content: 'brain',
    at: 170,
    cta: true,
    second: true,
  },
  {
    id: 'J',
    note: 'Same close, warm environment.',
    env: 'amber',
    cam: {frame: 0, target: [-1180, -520, 300], dist: 9200, yaw: 5, pitch: 12},
    content: 'brain',
    at: 170,
    cta: true,
    second: true,
  },
];

export const SHOT_COUNT = SHOTS.length;

const Screen: React.FC<{kind: Content; at: number}> = ({kind, at}) => {
  if (kind === 'cat') {
    return (
      <AbsoluteFill>
        <Freeze frame={Math.min(at, CHARACTER.frames - 1)}>
          <OffthreadVideo
            src={staticFile(CHARACTER.src)}
            muted
            style={{width: SCREEN.w, height: SCREEN.h, objectFit: 'cover'}}
          />
        </Freeze>
      </AbsoluteFill>
    );
  }
  if (kind === 'thread') return <ScreenThread frame={at} />;
  if (kind === 'promotion') return <ScreenPromotion frame={at} />;
  return <ScreenBrain frame={at} />;
};

const Cta: React.FC<{env: EnvName}> = ({env}) => {
  const e = ENVIRONMENTS[env];
  const dark = env !== 'studio';
  return (
    <div style={{position: 'absolute', left: 132, top: 322, width: 610, fontFamily: font.sans}}>
      <div
        style={{
          fontSize: 88,
          fontWeight: 650,
          letterSpacing: '-0.04em',
          color: e.ink,
          lineHeight: 1.02,
        }}
      >
        Arslan
      </div>
      <div style={{marginTop: 20, fontSize: 26, color: e.sub, lineHeight: 1.44, maxWidth: 500}}>
        One host agent. Spawns you raised. Nothing ships until you press
        Promote.
      </div>
      <div
        style={{
          marginTop: 42,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 15,
          background: dark ? '#F7F3EC' : e.ink,
          color: dark ? '#140d06' : '#fff',
          borderRadius: 999,
          padding: '20px 38px',
          fontSize: 25,
          fontWeight: 600,
          boxShadow: dark
            ? '0 18px 50px rgba(0,0,0,0.5)'
            : '0 18px 44px rgba(15,23,42,0.22)',
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
          color: e.sub,
          letterSpacing: '0.06em',
        }}
      >
        macOS 11+ · Apple Silicon · signed &amp; notarized
      </div>
    </div>
  );
};

export const ShotMock: React.FC = () => {
  const frame = useCurrentFrame();
  const shot = SHOTS[Math.min(frame, SHOTS.length - 1)];
  const e = ENVIRONMENTS[shot.env];

  return (
    <Stage
      frame={0}
      env={shot.env}
      keys={[{...shot.cam, frame: 0}]}
      overlay={shot.cta ? <Cta env={shot.env} /> : null}
    >
      <MacBook position={[0, 0, 0]} yaw={0} rim={e.rim} shadow={e.shadow} alu={e.alu}>
        <Screen kind={shot.content} at={shot.at} />
      </MacBook>

      {shot.second ? (
        <MacBook
          position={[2980, 0, 700]}
          yaw={-27}
          scale={0.94}
          rim={e.rim}
          shadow={e.shadow}
          alu={e.alu}
        >
          <ScreenThread frame={200} />
        </MacBook>
      ) : null}
    </Stage>
  );
};
