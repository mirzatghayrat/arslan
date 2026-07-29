import React from 'react';
import {Img, staticFile} from 'remotion';

/**
 * A photographic MacBook mock-up standing in the CSS-3D world, with the app
 * composited into its screen.
 *
 * This exists because the hand-built `MacBook` reads as a diagram, not a
 * machine — flat gradients, a drawn keyboard, no real material. A supplied
 * mock-up carries all of that for free and is the right call for a film whose
 * whole point is that the product looks finished.
 *
 * THE TRADE, stated plainly: a photograph is a flat plate. It can be dollied,
 * tilted, pushed and pulled convincingly, but it cannot be orbited — past
 * roughly ±10 degrees of yaw the illusion breaks and it reads as a printed
 * card standing on the desk. The camera language for shots using this has to
 * be push/pull/tilt/drift, not the orbit the built geometry allowed. Shots
 * that genuinely need to swing around the machine either keep `MacBook` or get
 * a second mock-up shot from that angle.
 *
 * `screen` is the display rectangle inside the source image, normalised 0-1.
 * Measure it from the asset rather than guessing — the app is composited into
 * exactly that box, so a few pixels out shows as a misaligned edge against the
 * bezel.
 */

export type PlateSpec = {
  /** Path under `public/`. */
  src: string;
  /** Pixel size of the source image. */
  width: number;
  height: number;
  /** Display rectangle within the image, normalised. */
  screen: {x: number; y: number; w: number; h: number};
  /**
   * True when the asset's screen area is cut out. A transparent screen lets
   * the app sit BEHIND the plate and pick up the asset's own glass reflections;
   * an opaque (white or green) screen means the app has to be laid over it and
   * those reflections are lost.
   */
  transparentScreen?: boolean;
};

export const MacBookPlate: React.FC<{
  spec: PlateSpec;
  /** World position of the plate's centre. */
  position?: [number, number, number];
  /** World width. Height follows the asset's aspect ratio. */
  width: number;
  /** Small values only — see the note above about flat plates. */
  yaw?: number;
  pitch?: number;
  opacity?: number;
  children?: React.ReactNode;
}> = ({spec, position = [0, 0, 0], width, yaw = 0, pitch = 0, opacity = 1, children}) => {
  const height = (width * spec.height) / spec.width;
  const s = spec.screen;

  const screenBox: React.CSSProperties = {
    position: 'absolute',
    left: s.x * width,
    top: s.y * height,
    width: s.w * width,
    height: s.h * height,
    overflow: 'hidden',
  };

  const plate = (
    <Img
      src={staticFile(spec.src)}
      style={{position: 'absolute', left: 0, top: 0, width, height}}
    />
  );

  return (
    <div
      style={{
        position: 'absolute',
        left: -width / 2,
        top: -height / 2,
        width,
        height,
        transformStyle: 'preserve-3d',
        transform: `translate3d(${position[0]}px, ${position[1]}px, ${position[2]}px) rotateY(${yaw}deg) rotateX(${pitch}deg)`,
        opacity,
      }}
    >
      {spec.transparentScreen ? (
        <>
          <div style={screenBox}>{children}</div>
          {plate}
        </>
      ) : (
        <>
          {plate}
          <div style={screenBox}>{children}</div>
        </>
      )}
    </div>
  );
};

/**
 * Measure a supplied asset's screen rectangle rather than eyeballing it: decode
 * the PNG, walk in from the centre until the bezel's dark pixels start, and
 * write the result in here.
 *
 * Left unpopulated on purpose — filling it with guessed numbers would put the
 * app a few pixels off the bezel in every single shot.
 */
export const PLATES: Record<string, PlateSpec> = {};
