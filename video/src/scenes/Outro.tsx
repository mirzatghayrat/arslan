import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Mark} from '../components/Mark';
import {Plate} from '../components/Plate';
import {Chip, Mono} from '../components/primitives';
import {ease, pop, ramp} from '../lib/anim';
import {color, label} from '../theme';

export const Outro: React.FC = () => {
  const frame = useCurrentFrame();

  const word = pop(frame, 18);
  const cta = pop(frame, 44);
  const url = ramp(frame, 66, 22);
  const chips = ramp(frame, 82, 22);
  const scale = interpolate(frame, [0, 165], [1, 1.03], {easing: ease});

  return (
    <Plate plate="07" title="Get it">
      <AbsoluteFill
        style={{
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${scale})`,
        }}
      >
        <Mark frame={frame} size={132} delay={2} live />

        <div
          style={{
            marginTop: 34,
            fontSize: 96,
            fontWeight: 500,
            color: color.ink,
            letterSpacing: '0.05em',
            opacity: Math.min(1, word * 1.4),
            transform: `translateY(${(1 - word) * 20}px)`,
          }}
        >
          ARSLAN
        </div>

        <div
          style={{
            marginTop: 14,
            ...label,
            fontSize: 17,
            fontWeight: 500,
            color: color.amber,
            opacity: Math.min(1, word * 1.2),
          }}
        >
          Local AI Orchestrator
        </div>

        {/* Download pill */}
        <div
          style={{
            marginTop: 54,
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            padding: '20px 40px',
            borderRadius: 999,
            background: `linear-gradient(180deg, ${color.amberHi}, ${color.amber})`,
            color: color.void,
            fontSize: 26,
            fontWeight: 700,
            letterSpacing: '0.01em',
            opacity: Math.min(1, cta * 1.4),
            transform: `translateY(${(1 - cta) * 18}px) scale(${0.96 + cta * 0.04})`,
            boxShadow: `0 0 ${52 + Math.sin(frame / 12) * 14}px ${color.amber}55, 0 20px 50px rgba(0,0,0,0.5)`,
          }}
        >
          <span style={{fontSize: 24}}>↓</span>
          Download for macOS
        </div>

        <div style={{marginTop: 30, opacity: url}}>
          <Mono size={22} tone={color.muted} tracking="0.06em">
            github.com/mirzatghayrat/arslan
          </Mono>
        </div>

        <div
          style={{
            marginTop: 40,
            display: 'flex',
            gap: 12,
            opacity: chips,
            transform: `translateY(${(1 - chips) * 10}px)`,
          }}
        >
          <Chip tone={color.mutedDim} size={14}>
            Apache-2.0
          </Chip>
          <Chip tone={color.mutedDim} size={14}>
            Apple Silicon
          </Chip>
          <Chip tone={color.mutedDim} size={14}>
            bring your own key
          </Chip>
          <Chip tone={color.mutedDim} size={14}>
            pre-v1
          </Chip>
        </div>
      </AbsoluteFill>
    </Plate>
  );
};
