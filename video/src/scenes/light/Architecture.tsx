import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {drawPath} from '../../lib/anim';
import {straight, wire, type Wire} from '../../lib/geom';
import {light} from '../../lightTheme';
import {font} from '../../theme';

/**
 * The mark handed over by the previous scene is still on screen and still the
 * same size — this scene just lets its three legs keep going until they reach
 * the spawns. Nothing cuts; the figure the cat was wearing becomes the figure
 * the product runs on.
 */

const HOST = {x: 960, y: 540};
const HOST_R = 74;

const SPAWNS = [
  {x: 1418, y: 330, name: 'Research', at: 74},
  {x: 1418, y: 540, name: 'Data & Charts', at: 84},
  {x: 1418, y: 750, name: 'Engineering', at: 94},
];

const YOU = {x: 502, y: 540};

const IN: Wire = straight({x: YOU.x + 96, y: YOU.y}, {x: HOST.x - HOST_R - 16, y: HOST.y});
const LEGS: Wire[] = SPAWNS.map((s, i) =>
  i === 1
    ? straight({x: HOST.x + HOST_R + 16, y: HOST.y}, {x: s.x - 74, y: s.y})
    : wire(
        {x: HOST.x + HOST_R + 16, y: HOST.y},
        {x: HOST.x + 190, y: HOST.y},
        {x: s.x - 210, y: s.y},
        {x: s.x - 74, y: s.y},
      ),
);

const glide = Easing.bezier(0.4, 0, 0.2, 1);

const ramp = (frame: number, start: number, len: number) =>
  interpolate(frame, [start, start + len], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

export const Architecture: React.FC = () => {
  const frame = useCurrentFrame();

  const you = ramp(frame, 40, 26);
  const line = ramp(frame, 148, 30);
  const line2 = ramp(frame, 196, 30);
  const close = ramp(frame, 250, 30);

  return (
    <AbsoluteFill style={{background: light.background, fontFamily: font.sans}}>
      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        <path
          d={IN.d}
          stroke={light.borderStrong}
          strokeWidth={1.75}
          fill="none"
          {...drawPath(you, IN.length)}
        />
        {LEGS.map((w, i) => (
          <path
            key={i}
            d={w.d}
            stroke={light.primary}
            strokeWidth={1.75}
            fill="none"
            opacity={0.85}
            {...drawPath(ramp(frame, SPAWNS[i].at - 26, 34), w.length)}
          />
        ))}
      </svg>

      {/* You */}
      <div
        style={{
          position: 'absolute',
          left: YOU.x - 96,
          top: YOU.y - 40,
          width: 192,
          textAlign: 'center',
          opacity: ramp(frame, 26, 24),
        }}
      >
        <div
          style={{
            fontFamily: font.mono,
            fontSize: 12,
            letterSpacing: '0.24em',
            color: light.subtle,
            textTransform: 'uppercase',
          }}
        >
          You
        </div>
        <div style={{marginTop: 12, fontSize: 27, fontWeight: 600, color: light.ink}}>
          One thread
        </div>
      </div>

      {/* Host — sits exactly where the handed-over mark settled */}
      <div
        style={{
          position: 'absolute',
          left: HOST.x - HOST_R,
          top: HOST.y - HOST_R,
          width: HOST_R * 2,
          height: HOST_R * 2,
          borderRadius: 999,
          border: `1.75px solid ${light.primary}`,
          background: light.surface,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: `0 18px 44px rgba(217,116,26,0.18)`,
        }}
      >
        <div style={{textAlign: 'center'}}>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 11,
              letterSpacing: '0.2em',
              color: light.hub,
              fontWeight: 600,
            }}
          >
            HOST
          </div>
          <div
            style={{
              fontFamily: font.mono,
              fontSize: 11,
              letterSpacing: '0.2em',
              color: light.hub,
              fontWeight: 600,
            }}
          >
            AGENT
          </div>
        </div>
      </div>

      {/* Spawns */}
      {SPAWNS.map((s, i) => {
        const p = ramp(frame, s.at, 26);
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: s.x - 74,
              top: s.y - 37,
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              opacity: p,
              transform: `translateX(${(1 - p) * 22}px)`,
            }}
          >
            <div
              style={{
                width: 74,
                height: 74,
                borderRadius: 999,
                flexShrink: 0,
                background: light.surface,
                border: `1.5px solid ${light.border}`,
                boxShadow: '0 10px 26px rgba(15,23,42,0.07)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <span
                style={{
                  width: 13,
                  height: 13,
                  borderRadius: 999,
                  background: light.primary,
                }}
              />
            </div>
            <div style={{fontSize: 25, fontWeight: 600, color: light.ink, whiteSpace: 'nowrap'}}>
              {s.name}
            </div>
          </div>
        );
      })}

      {/* Two lines, one at a time */}
      <div style={{position: 'absolute', left: 132, top: 128, width: 1100}}>
        <div
          style={{
            fontSize: 58,
            fontWeight: 600,
            letterSpacing: '-0.03em',
            color: light.ink,
            opacity: line,
            transform: `translateY(${(1 - line) * 14}px)`,
          }}
        >
          One host agent.
        </div>
        <div
          style={{
            marginTop: 10,
            fontSize: 58,
            fontWeight: 600,
            letterSpacing: '-0.03em',
            color: light.primary,
            opacity: line2,
            transform: `translateY(${(1 - line2) * 14}px)`,
          }}
        >
          Spawns you raised yourself.
        </div>
      </div>

      <div
        style={{
          position: 'absolute',
          left: 132,
          bottom: 118,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          opacity: close,
          transform: `translateY(${(1 - close) * 10}px)`,
        }}
      >
        <span style={{width: 38, height: 1.5, background: light.primary}} />
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 17,
            color: light.muted,
          }}
        >
          Your machine · your keys · nothing ships until you press Promote
        </span>
      </div>
    </AbsoluteFill>
  );
};
