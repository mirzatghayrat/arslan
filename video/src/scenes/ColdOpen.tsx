import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {Mark} from '../components/Mark';
import {Plate} from '../components/Plate';
import {Mono} from '../components/primitives';
import {ease, pop, ramp} from '../lib/anim';
import {color, label} from '../theme';

const WORD = 'ARSLAN';

export const ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();

  const tagline = ramp(frame, 62, 22);
  const rule = ramp(frame, 74, 26);
  const footer = ramp(frame, 88, 22);

  // Very slow push-in so the still frame never feels frozen.
  const scale = interpolate(frame, [0, 150], [1.04, 1], {easing: ease});

  return (
    <Plate plate="00" title="Arslan">
      <AbsoluteFill
        style={{
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${scale})`,
        }}
      >
        <div style={{marginBottom: 42}}>
          <Mark frame={frame} size={168} delay={6} live />
        </div>

        <div style={{display: 'flex', gap: 22}}>
          {WORD.split('').map((ch, i) => {
            const p = pop(frame, 26 + i * 4);
            return (
              <span
                key={i}
                style={{
                  fontSize: 118,
                  fontWeight: 500,
                  color: color.ink,
                  letterSpacing: '0.04em',
                  lineHeight: 1,
                  opacity: Math.min(1, p * 1.4),
                  transform: `translateY(${(1 - p) * 26}px)`,
                  display: 'inline-block',
                }}
              >
                {ch}
              </span>
            );
          })}
        </div>

        <div
          style={{
            marginTop: 30,
            display: 'flex',
            alignItems: 'center',
            gap: 26,
            opacity: tagline,
          }}
        >
          <span
            style={{
              width: 90 * rule,
              height: 1,
              background: color.rule,
            }}
          />
          <span
            style={{
              ...label,
              fontSize: 19,
              fontWeight: 500,
              color: color.amber,
            }}
          >
            Local AI Orchestrator
          </span>
          <span
            style={{
              width: 90 * rule,
              height: 1,
              background: color.rule,
            }}
          />
        </div>

        <div
          style={{
            marginTop: 74,
            display: 'flex',
            gap: 18,
            alignItems: 'center',
            opacity: footer,
            transform: `translateY(${(1 - footer) * 10}px)`,
          }}
        >
          <Mono size={16} tone={color.mutedDim} tracking="0.2em">
            PRODUCT DEMO
          </Mono>
          <span style={{color: color.faint}}>·</span>
          <Mono size={16} tone={color.mutedDim} tracking="0.2em">
            8 PLATES
          </Mono>
          <span style={{color: color.faint}}>·</span>
          <Mono size={16} tone={color.mutedDim} tracking="0.2em">
            MACOS · BYOK
          </Mono>
        </div>
      </AbsoluteFill>
    </Plate>
  );
};
