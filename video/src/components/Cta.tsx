import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {MASTHEAD, PRODUCT} from '../facts';
import {font} from '../theme';

/**
 * The close.
 *
 * Type in world space is the one thing that must never touch the machine: a
 * caption laid across the hardware turns an app demo into a laptop advert, and
 * that mistake cost a whole pass of this film. The top-down mock-up earns this
 * shot by having empty set around the machine, so the words have somewhere of
 * their own to be, and the camera pulls back into that space rather than
 * cutting to it.
 *
 * White on amber rather than the app's ink on white: this is the only moment
 * the film leaves the screen, and it should look like the set it is standing
 * on, not like a slide pasted over one.
 */
export const Cta: React.FC<{start: number}> = ({start}) => {
  const frame = useCurrentFrame();
  const ease = Easing.bezier(0.22, 1, 0.36, 1);
  const step = (a: number, b: number) =>
    interpolate(frame, [start + a, start + b], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: ease,
    });

  const head = step(0, 34);
  const sub = step(14, 48);
  const btn = step(30, 64);

  return (
    <div
      style={{
        position: 'absolute',
        left: 128,
        top: 296,
        width: 620,
        fontFamily: font.sans,
      }}
    >
      <div
        style={{
          fontSize: 92,
          fontWeight: 650,
          letterSpacing: '-0.04em',
          color: '#FFF6EA',
          lineHeight: 1.02,
          textShadow: '0 10px 40px rgba(60,26,0,0.4)',
          opacity: head,
          transform: `translateY(${(1 - head) * 22}px)`,
        }}
      >
        {PRODUCT.name}
      </div>
      <div
        style={{
          marginTop: 20,
          fontSize: 26,
          color: 'rgba(255,238,219,0.86)',
          lineHeight: 1.45,
          maxWidth: 510,
          opacity: sub,
          transform: `translateY(${(1 - sub) * 18}px)`,
        }}
      >
        {MASTHEAD.a} {MASTHEAD.b}
      </div>
      <div
        style={{
          marginTop: 44,
          display: 'inline-flex',
          alignItems: 'center',
          gap: 15,
          background: '#FFF6EA',
          color: '#231204',
          borderRadius: 999,
          padding: '20px 38px',
          fontSize: 25,
          fontWeight: 600,
          boxShadow: '0 20px 54px rgba(48,20,0,0.45)',
          opacity: btn,
          transform: `translateY(${(1 - btn) * 16}px) scale(${0.965 + btn * 0.035})`,
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
          color: 'rgba(255,235,213,0.66)',
          letterSpacing: '0.06em',
          opacity: btn,
        }}
      >
        {PRODUCT.platform} · {PRODUCT.license} · {PRODUCT.status}
      </div>
    </div>
  );
};
