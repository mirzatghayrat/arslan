import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {ramp} from '../lib/anim';
import {color, font, label} from '../theme';

const GRID = 60;

/** Faint engineering grid + a heavier decade line every 6 cells. */
const Grid: React.FC<{opacity: number}> = ({opacity}) => (
  <AbsoluteFill
    style={{
      opacity,
      backgroundImage: `
        linear-gradient(${color.rule}22 1px, transparent 1px),
        linear-gradient(90deg, ${color.rule}22 1px, transparent 1px),
        linear-gradient(${color.rule}3d 1px, transparent 1px),
        linear-gradient(90deg, ${color.rule}3d 1px, transparent 1px)`,
      backgroundSize: `${GRID}px ${GRID}px, ${GRID}px ${GRID}px, ${GRID * 6}px ${
        GRID * 6
      }px, ${GRID * 6}px ${GRID * 6}px`,
    }}
  />
);

/** Registration ticks in each corner, the way the README figures are cropped. */
const Ticks: React.FC<{opacity: number}> = ({opacity}) => {
  const arm = 34;
  const inset = 56;
  const corners = [
    {x: inset, y: inset, sx: 1, sy: 1},
    {x: 1920 - inset, y: inset, sx: -1, sy: 1},
    {x: inset, y: 1080 - inset, sx: 1, sy: -1},
    {x: 1920 - inset, y: 1080 - inset, sx: -1, sy: -1},
  ];
  return (
    <svg
      width={1920}
      height={1080}
      style={{position: 'absolute', inset: 0, opacity}}
    >
      {corners.map((c, i) => (
        <g key={i} stroke={color.ruleHi} strokeWidth={1.5}>
          <line x1={c.x} y1={c.y} x2={c.x + arm * c.sx} y2={c.y} />
          <line x1={c.x} y1={c.y} x2={c.x} y2={c.y + arm * c.sy} />
        </g>
      ))}
    </svg>
  );
};

export const Plate: React.FC<{
  plate: string;
  title: string;
  children: React.ReactNode;
  /** Dims the grid for scenes that carry their own dense artwork. */
  quiet?: boolean;
}> = ({plate, title, children, quiet = false}) => {
  const frame = useCurrentFrame();
  const chrome = ramp(frame, 0, 20);

  return (
    <AbsoluteFill style={{backgroundColor: color.void, fontFamily: font.sans}}>
      <Grid opacity={(quiet ? 0.35 : 0.85) * chrome} />

      {/* Warm floor light — keeps the near-black from reading as flat #000. */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(120% 80% at 50% 108%, ${color.amberInk}66 0%, transparent 62%)`,
        }}
      />
      {/* Vignette */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(78% 78% at 50% 46%, transparent 40%, rgba(0,0,0,0.72) 100%)',
        }}
      />

      <Ticks opacity={chrome} />

      <AbsoluteFill>{children}</AbsoluteFill>

      {/* Footer rail */}
      <div
        style={{
          position: 'absolute',
          left: 96,
          right: 96,
          bottom: 62,
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          opacity: chrome * 0.9,
        }}
      >
        <span
          style={{
            ...label,
            fontSize: 15,
            fontWeight: 500,
            color: color.amber,
          }}
        >
          Plate {plate}
        </span>
        <span style={{flex: 1, height: 1, background: color.rule}} />
        <span
          style={{
            ...label,
            fontSize: 15,
            fontWeight: 400,
            color: color.mutedDim,
          }}
        >
          {title}
        </span>
      </div>
    </AbsoluteFill>
  );
};
