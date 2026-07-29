import {Easing, interpolate} from 'remotion';

/**
 * A real orbiting camera over a CSS-3D world.
 *
 * The previous cut had no camera at all — every scene was flat elements fading
 * in and out, which is why it read as slides rather than shots. Here the world
 * holds actual geometry (a laptop with a hinged lid, standing on a desk) and
 * the camera moves through it, so depth comes from parallax and perspective
 * rather than from drop shadows.
 *
 * CSS-3D rather than WebGL on purpose: a laptop is two hinged planes, which
 * CSS models exactly, and the screen content stays live DOM — real text, real
 * `<OffthreadVideo>` — instead of being baked into a texture at some fixed
 * resolution. It also keeps the render off software GL, which this project's
 * headless pipeline has already shown to be the fragile part.
 */

/** Focal length. Larger = longer lens = flatter perspective. */
export const PERSPECTIVE = 1800;

export type CamKey = {
  frame: number;
  /** World point the camera is aimed at. */
  target: [number, number, number];
  /** Distance from that point. At `dist === PERSPECTIVE` the world is 1:1. */
  dist: number;
  /** Degrees. Orbit around the target: yaw horizontally, pitch vertically. */
  yaw: number;
  pitch: number;
  /** Degrees of camera roll. Use sparingly — a tilted horizon reads as a mistake. */
  roll?: number;
};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** The house curve. Every camera move in the film rides this one. */
export const glide = Easing.bezier(0.4, 0, 0.2, 1);
/** For moves that should arrive rather than settle — reveals, pull-backs. */
export const arrive = Easing.bezier(0.22, 1, 0.36, 1);

export const sampleCam = (
  frame: number,
  keys: CamKey[],
  easing: (t: number) => number = glide,
): Required<CamKey> => {
  let a = keys[0];
  let b = keys[keys.length - 1];
  for (let i = 0; i < keys.length - 1; i++) {
    if (frame >= keys[i].frame && frame <= keys[i + 1].frame) {
      a = keys[i];
      b = keys[i + 1];
      break;
    }
  }
  const t =
    a.frame === b.frame
      ? 1
      : interpolate(frame, [a.frame, b.frame], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
          easing,
        });
  return {
    frame,
    target: [
      lerp(a.target[0], b.target[0], t),
      lerp(a.target[1], b.target[1], t),
      lerp(a.target[2], b.target[2], t),
    ],
    dist: lerp(a.dist, b.dist, t),
    yaw: lerp(a.yaw, b.yaw, t),
    pitch: lerp(a.pitch, b.pitch, t),
    roll: lerp(a.roll ?? 0, b.roll ?? 0, t),
  };
};

/**
 * Inverse camera transform, applied to the world.
 *
 * Read right to left — the world is first shifted so the target sits at the
 * origin, then counter-rotated by the camera's orientation, then pushed to
 * `PERSPECTIVE - dist` on z. That last step is what makes `dist` mean what it
 * says: CSS scales a plane at depth z by `P / (P - z)`, so a target parked at
 * `P - dist` renders at exactly `P / dist`. Framing is therefore a physical
 * distance, not a magic scale factor, and the same number can be reused
 * between shots and reasoned about.
 */
export const worldTransform = (cam: Required<CamKey>): string =>
  [
    `translateZ(${PERSPECTIVE - cam.dist}px)`,
    `rotateZ(${cam.roll}deg)`,
    // Negated: this is the INVERSE camera rotation applied to the world, so a
    // camera that looks down by `pitch` needs the world tipped the other way.
    // Getting this backwards puts the lens under the floor plane, which then
    // fills frame with its own underside — the laptop renders correctly the
    // whole time and is simply occluded by the room.
    `rotateX(${-cam.pitch}deg)`,
    `rotateY(${-cam.yaw}deg)`,
    `translate3d(${-cam.target[0]}px, ${-cam.target[1]}px, ${-cam.target[2]}px)`,
  ].join(' ');

/**
 * Distance at which a plane of `width` world units exactly spans the 1920px
 * frame. Used to open on a screen filling the frame edge to edge without
 * hand-tuning a number that would silently break if the geometry changed.
 */
export const distanceToFit = (width: number, viewport = 1920) =>
  (PERSPECTIVE * width) / viewport;
