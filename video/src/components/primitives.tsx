import React from 'react';
import {useCurrentFrame} from 'remotion';
import {pop, ramp} from '../lib/anim';
import {color, font, label} from '../theme';

/** Small amber mono kicker with a leading dash, as used across the site. */
export const Eyebrow: React.FC<{
  children: React.ReactNode;
  delay?: number;
  tone?: string;
}> = ({children, delay = 0, tone = color.amber}) => {
  const frame = useCurrentFrame();
  const p = ramp(frame, delay, 18);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        opacity: p,
        transform: `translateX(${(1 - p) * -12}px)`,
      }}
    >
      <span style={{width: 26, height: 1.5, background: tone}} />
      <span style={{...label, fontSize: 16, fontWeight: 500, color: tone}}>
        {children}
      </span>
    </div>
  );
};

/** Headline line that rises out of a clipping mask. */
export const Rise: React.FC<{
  children: React.ReactNode;
  delay?: number;
  size?: number;
  weight?: number;
  tone?: string;
  lineHeight?: number;
  tracking?: string;
}> = ({
  children,
  delay = 0,
  size = 64,
  weight = 600,
  tone = color.ink,
  lineHeight = 1.18,
  tracking = '-0.02em',
}) => {
  const frame = useCurrentFrame();
  const p = pop(frame, delay);
  return (
    <div style={{overflow: 'hidden', paddingBottom: size * 0.1}}>
      <div
        style={{
          fontSize: size,
          fontWeight: weight,
          color: tone,
          lineHeight,
          letterSpacing: tracking,
          transform: `translateY(${(1 - p) * (size * 1.2)}px)`,
          opacity: Math.min(1, p * 1.6),
        }}
      >
        {children}
      </div>
    </div>
  );
};

/** Rounded mono chip — the client's tool/skill/status pills. */
export const Chip: React.FC<{
  children: React.ReactNode;
  tone?: string;
  filled?: boolean;
  size?: number;
}> = ({children, tone = color.muted, filled = false, size = 15}) => (
  <span
    style={{
      fontFamily: font.mono,
      fontSize: size,
      letterSpacing: '0.06em',
      color: filled ? color.void : tone,
      background: filled ? tone : `${tone}14`,
      border: `1px solid ${filled ? tone : `${tone}44`}`,
      borderRadius: 999,
      padding: `${size * 0.32}px ${size * 0.8}px`,
      whiteSpace: 'nowrap',
      fontWeight: filled ? 600 : 400,
    }}
  >
    {children}
  </span>
);

/** Panel with the client's card treatment: 1px rule, faint fill, soft radius. */
export const Panel: React.FC<{
  children?: React.ReactNode;
  style?: React.CSSProperties;
  tone?: string;
  glow?: number;
}> = ({children, style, tone = color.rule, glow = 0}) => (
  <div
    style={{
      background: `linear-gradient(160deg, ${color.panel}f2, ${color.plate}f2)`,
      border: `1px solid ${tone}`,
      borderRadius: 16,
      boxShadow:
        glow > 0
          ? `0 0 ${40 * glow}px ${color.amber}${Math.round(glow * 60)
              .toString(16)
              .padStart(2, '0')}, 0 18px 48px rgba(0,0,0,0.55)`
          : '0 18px 48px rgba(0,0,0,0.45)',
      ...style,
    }}
  >
    {children}
  </div>
);

/** Thin horizontal rule that wipes open from the left. */
export const Wipe: React.FC<{
  progress: number;
  tone?: string;
  height?: number;
}> = ({progress, tone = color.rule, height = 1}) => (
  <div style={{height, background: tone, transform: `scaleX(${progress})`, transformOrigin: 'left'}} />
);

export const Mono: React.FC<{
  children: React.ReactNode;
  size?: number;
  tone?: string;
  weight?: number;
  tracking?: string;
}> = ({children, size = 18, tone = color.muted, weight = 400, tracking = '0.02em'}) => (
  <span
    style={{
      fontFamily: font.mono,
      fontSize: size,
      color: tone,
      fontWeight: weight,
      letterSpacing: tracking,
    }}
  >
    {children}
  </span>
);
