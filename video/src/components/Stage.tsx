import React from 'react';
import {AbsoluteFill} from 'remotion';
import {PERSPECTIVE, sampleCam, worldTransform, type CamKey} from '../lib/camera3d';
import {ALU_SILVER, type Alu} from './MacBook';
import {light} from '../lightTheme';

/**
 * The room the film is shot in: a backdrop, a floor plane the machines really
 * stand on, and the camera rig everything is seen through.
 *
 * The floor is geometry rather than a painted gradient, so when the camera
 * drops toward the desk its perspective changes along with everything else.
 * That one plane is most of what separates this from a flat composition.
 */

export const DESK_Y = 20;

export type EnvName = 'studio' | 'amber' | 'slate';

type Env = {
  /** Behind everything. */
  backdrop: string;
  /** The floor plane's own fill. */
  floor: string;
  /** Key light bloom over the backdrop. */
  key: string;
  /** Corner falloff. */
  vignette: string;
  /** How hard the machine's edges catch light. */
  rim: number;
  shadow: number;
  /** Metal for machines standing in this room. */
  alu: Alu;
  /** Ink colour for any copy placed in this environment. */
  ink: string;
  sub: string;
};

export const ENVIRONMENTS: Record<EnvName, Env> = {
  /** Bright seamless sweep. Reads as a product page. */
  studio: {
    backdrop: light.background,
    floor: `linear-gradient(180deg, #f2f4f7 0%, #e8ecf1 40%, #dfe4ea 100%)`,
    key: 'radial-gradient(120% 90% at 28% 6%, rgba(255,255,255,0.95) 0%, rgba(255,255,255,0) 56%)',
    vignette:
      'radial-gradient(80% 80% at 50% 46%, rgba(0,0,0,0) 54%, rgba(15,23,42,0.10) 100%)',
    rim: 0,
    shadow: 0.55,
    alu: ALU_SILVER,
    ink: light.ink,
    sub: light.muted,
  },
  /**
   * Warm, low-key, the machine lit against a glow. Arslan's accent is amber,
   * so this is the product's own colour turned into a lighting setup rather
   * than a look borrowed from somewhere else.
   */
  amber: {
    backdrop: '#140d06',
    floor: 'linear-gradient(180deg, #241705 0%, #17100a 46%, #0d0906 100%)',
    key: 'radial-gradient(78% 62% at 50% 34%, rgba(214,124,32,0.92) 0%, rgba(146,79,17,0.42) 34%, rgba(30,18,8,0) 72%)',
    vignette:
      'radial-gradient(88% 84% at 50% 44%, rgba(0,0,0,0) 34%, rgba(6,4,2,0.72) 100%)',
    rim: 0.85,
    shadow: 0.9,
    alu: {
      light: '#8a7256',
      mid: '#5f4c39',
      dark: '#3d3125',
      deep: '#2a2118',
      edge: '#c9a273',
      well: '#120d08',
    },
    ink: '#F7F3EC',
    sub: 'rgba(247,243,236,0.62)',
  },
  /** Cool near-black. The dark film's world, with the machine in it. */
  slate: {
    backdrop: '#0a0b0e',
    floor: 'linear-gradient(180deg, #16181d 0%, #101216 50%, #0a0b0e 100%)',
    key: 'radial-gradient(90% 70% at 50% 18%, rgba(230,134,60,0.20) 0%, rgba(10,11,14,0) 62%)',
    vignette:
      'radial-gradient(84% 82% at 50% 46%, rgba(0,0,0,0) 40%, rgba(0,0,0,0.78) 100%)',
    rim: 0.7,
    shadow: 0.85,
    alu: {
      light: '#5a5f69',
      mid: '#42464e',
      dark: '#2e3138',
      deep: '#212429',
      edge: '#7d838f',
      well: '#0a0b0e',
    },
    ink: '#ededf0',
    sub: '#93959e',
  },
};

export const Stage: React.FC<{
  keys: CamKey[];
  easing?: (t: number) => number;
  frame: number;
  env?: EnvName;
  children: React.ReactNode;
  /** Screen-space layer. Keep it clear of the machine — copy laid over the
      hardware makes the shot read as a laptop ad rather than an app. */
  overlay?: React.ReactNode;
}> = ({keys, easing, frame, env = 'studio', children, overlay}) => {
  const cam = sampleCam(frame, keys, easing);
  const e = ENVIRONMENTS[env];

  return (
    <AbsoluteFill style={{overflow: 'hidden', background: e.backdrop}}>
      <AbsoluteFill style={{background: e.key}} />

      <AbsoluteFill
        style={{
          perspective: `${PERSPECTIVE}px`,
          perspectiveOrigin: '960px 540px',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 960,
            top: 540,
            width: 0,
            height: 0,
            transformStyle: 'preserve-3d',
            transform: worldTransform(cam),
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: -11000,
              top: -9000,
              width: 22000,
              height: 18000,
              transform: `rotateX(90deg) translateZ(${-DESK_Y}px)`,
              background: e.floor,
            }}
          />
          {children}
        </div>
      </AbsoluteFill>

      <AbsoluteFill style={{background: e.vignette, pointerEvents: 'none'}} />

      {overlay}
    </AbsoluteFill>
  );
};
