import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Freeze,
  interpolate,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import {Mark} from '../../components/Mark';
import {CHARACTER, light} from '../../lightTheme';
import {font} from '../../theme';

/**
 * The whole film turns on one observation: the emblem glowing on the cat's
 * chest IS the Arslan mark — one node with legs radiating out of it. So this
 * scene starts on the character, pushes into that emblem, and hands off to the
 * vector mark at the same screen position and size. The character's chest and
 * the architecture diagram are the same drawing; the cut just makes it literal.
 *
 * The footage is placed at roughly its native size rather than blown up to
 * full bleed. 1280x720 stretched across a 1920 frame is visibly soft, and a
 * product sitting in negative space is the language being borrowed anyway.
 */

// The card is a touch under native width, so the plate is a downscale.
const CARD = {x: 620, y: 208, w: 1180, h: 664};

// Where the emblem lands on the canvas once the card is placed.
const EMBLEM = {
  x: CARD.x + CHARACTER.emblem.x * CARD.w,
  y: CARD.y + CHARACTER.emblem.y * CARD.h,
  size: CHARACTER.emblem.size * CARD.w,
};

const PUSH_START = 178;
const PUSH_END = 268;
const HANDOFF = 248;
const PUSH_SCALE = 2.1;

/**
 * The mark's figure fills only the middle ~59% of its 32-unit viewBox (host
 * circle top at y=10, lowest spawn at y=27.5, x from 6.5 to 25.5). Sizing the
 * SVG box to the emblem's span would therefore draw a mark noticeably smaller
 * than the glow it is replacing, and the hand-off would read as a shrink.
 */
const MARK_BOX = 1 / 0.594;

/** Long, even curve — no spring overshoot anywhere in this cut. */
const glide = Easing.bezier(0.4, 0, 0.2, 1);

export const Creature: React.FC = () => {
  const frame = useCurrentFrame();

  const enter = interpolate(frame, [0, 34], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

  const push = interpolate(frame, [PUSH_START, PUSH_END], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });
  const scale = 1 + (PUSH_SCALE - 1) * push;

  // Focus falls away as we run out of real pixels, so the softness reads as a
  // rack focus rather than as an upscale.
  const blur = interpolate(frame, [PUSH_START + 46, PUSH_END], [0, 3.5], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // Type is out before the move starts; nothing competes with the push.
  const wordmark = interpolate(frame, [58, 88, 168, 194], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });
  const tagline = interpolate(frame, [80, 108, 168, 190], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

  const handoff = interpolate(frame, [HANDOFF, HANDOFF + 26], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });

  // The vector mark takes over at the emblem's exact size, then settles to the
  // centre of the frame as the plate behind it washes out.
  const settle = interpolate(frame, [HANDOFF + 18, 300], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: glide,
  });
  const markSize = EMBLEM.size * scale * MARK_BOX;
  const markX = EMBLEM.x + (960 - EMBLEM.x) * settle;
  const markY = EMBLEM.y + (540 - EMBLEM.y) * settle;
  const markScale = 1 + 1.7 * settle;

  return (
    <AbsoluteFill style={{background: light.background, fontFamily: font.sans}}>
      {/* Character plate */}
      <AbsoluteFill
        style={{
          opacity: enter * (1 - handoff * 0.9),
          transform: `scale(${scale})`,
          transformOrigin: `${EMBLEM.x}px ${EMBLEM.y}px`,
          filter: blur > 0.05 ? `blur(${blur}px)` : undefined,
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: CARD.x,
            top: CARD.y,
            width: CARD.w,
            height: CARD.h,
            borderRadius: 26,
            overflow: 'hidden',
            background: light.surface,
            boxShadow: `0 42px 90px rgba(15,23,42,0.13), 0 3px 10px rgba(15,23,42,0.05)`,
            transform: `translateY(${(1 - enter) * 26}px) scale(${0.985 + enter * 0.015})`,
          }}
        >
          {/* Hold on the settled pose once the clip runs out, rather than
              cutting away from it. */}
          <Freeze frame={Math.min(frame, CHARACTER.frames - 1)}>
            <OffthreadVideo
              src={staticFile(CHARACTER.src)}
              muted
              style={{width: '100%', height: '100%', objectFit: 'cover'}}
            />
          </Freeze>
        </div>
      </AbsoluteFill>

      {/* Type, in the clean left third */}
      <div
        style={{
          position: 'absolute',
          left: 132,
          top: 404,
          width: 440,
        }}
      >
        <div
          style={{
            fontSize: 92,
            fontWeight: 600,
            letterSpacing: '-0.035em',
            color: light.ink,
            lineHeight: 1,
            opacity: wordmark,
            transform: `translateY(${(1 - wordmark) * 16}px)`,
          }}
        >
          Arslan
        </div>
        <div
          style={{
            marginTop: 24,
            fontFamily: font.mono,
            fontSize: 15,
            letterSpacing: '0.26em',
            textTransform: 'uppercase',
            color: light.primary,
            opacity: tagline,
            transform: `translateY(${(1 - tagline) * 12}px)`,
          }}
        >
          Local AI Orchestrator
        </div>
      </div>

      {/* Wash the plate out from under the mark. Ordering matters more than
          z-index here: this has to cover the footage but never the mark. */}
      <AbsoluteFill
        style={{
          background: light.background,
          opacity: interpolate(frame, [HANDOFF + 24, 300], [0, 1], {
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
            easing: glide,
          }),
        }}
      />

      {/* The mark, arriving exactly where the emblem was */}
      <div
        style={{
          position: 'absolute',
          left: markX - markSize / 2,
          top: markY - markSize / 2,
          width: markSize,
          height: markSize,
          opacity: handoff,
          transform: `scale(${markScale})`,
          transformOrigin: 'center',
        }}
      >
        <Mark frame={frame - HANDOFF + 99} size={markSize} live tone={light.primary} />
      </div>

    </AbsoluteFill>
  );
};
