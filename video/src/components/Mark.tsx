import React from 'react';
import {interpolate} from 'remotion';
import {drawPath, ease, pop} from '../lib/anim';
import {color} from '../theme';

/**
 * The Arslan mark (web/public/favicon.svg) rebuilt as a timed drawing: three
 * legs fan out of one host node into three spawns. It is the same figure the
 * request-path plate expands into, so the film's first frame is already the
 * architecture diagram.
 */
export const Mark: React.FC<{
  frame: number;
  size?: number;
  delay?: number;
  /** Pulses the spawn nodes once they have landed. */
  live?: boolean;
  /** Accent, so the light film can pass the product's light-theme primary. */
  tone?: string;
}> = ({frame, size = 220, delay = 0, live = false, tone = color.amber}) => {
  const f = frame - delay;

  const host = pop(f, 0);
  const legs = interpolate(f, [8, 34], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: ease,
  });

  const legDefs = [
    {x1: 16, y1: 13, x2: 9, y2: 23},
    {x1: 16, y1: 13, x2: 16, y2: 25},
    {x1: 16, y1: 13, x2: 23, y2: 23},
  ];
  const spawns = [
    {cx: 9, cy: 23},
    {cx: 16, cy: 25},
    {cx: 23, cy: 23},
  ];

  return (
    <svg width={size} height={size} viewBox="0 0 32 32" style={{overflow: 'visible'}}>
      <defs>
        <filter id="mark-glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation={0.55} result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <g filter="url(#mark-glow)">
        {legDefs.map((l, i) => {
          const len = Math.hypot(l.x2 - l.x1, l.y2 - l.y1);
          const p = interpolate(legs, [i * 0.16, i * 0.16 + 0.7], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          });
          return (
            <line
              key={i}
              x1={l.x1}
              y1={l.y1}
              x2={l.x2}
              y2={l.y2}
              stroke={tone}
              strokeWidth={2}
              strokeLinecap="round"
              {...drawPath(p, len)}
            />
          );
        })}

        <circle
          cx={16}
          cy={13}
          r={3 * host}
          fill={tone}
        />

        {spawns.map((sp, i) => {
          const p = pop(f, 20 + i * 5);
          const pulse = live
            ? 1 + Math.sin((f - 40 - i * 9) / 11) * 0.09
            : 1;
          return (
            <circle
              key={i}
              cx={sp.cx}
              cy={sp.cy}
              r={2.5 * p * (f > 40 ? pulse : 1)}
              fill={tone}
            />
          );
        })}
      </g>
    </svg>
  );
};
