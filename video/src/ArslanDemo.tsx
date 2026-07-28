import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {ColdOpen} from './scenes/ColdOpen';
import {Outro} from './scenes/Outro';
import {PromotionGate} from './scenes/PromotionGate';
import {RequestPath} from './scenes/RequestPath';
import {Roster} from './scenes/Roster';
import {Safety} from './scenes/Safety';
import {SecondBrain} from './scenes/SecondBrain';
import {Thesis} from './scenes/Thesis';
import {easeInOut} from './lib/anim';
import {color, SCENE_OVERLAP, SCENES} from './theme';

const SCENE_COMPONENTS: Record<string, React.FC> = {
  'cold-open': ColdOpen,
  thesis: Thesis,
  'request-path': RequestPath,
  roster: Roster,
  promotion: PromotionGate,
  'second-brain': SecondBrain,
  safety: Safety,
  outro: Outro,
};

/**
 * Cross-fade with a touch of scale, so consecutive dark plates read as a cut
 * between drawings rather than a dissolve into mush.
 */
const Transition: React.FC<{
  duration: number;
  isFirst: boolean;
  isLast: boolean;
  children: React.ReactNode;
}> = ({duration, isFirst, isLast, children}) => {
  const frame = useCurrentFrame();
  const inP = isFirst
    ? 1
    : interpolate(frame, [0, SCENE_OVERLAP], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: easeInOut,
      });
  const outP = isLast
    ? 1
    : interpolate(frame, [duration - SCENE_OVERLAP, duration], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing: easeInOut,
      });
  const o = inP * outP;
  return (
    <AbsoluteFill
      style={{
        opacity: o,
        transform: `scale(${1 + (1 - inP) * 0.015 - (1 - outP) * 0.01})`,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export const ArslanDemo: React.FC = () => {
  let cursor = 0;

  return (
    <AbsoluteFill style={{backgroundColor: color.void}}>
      {SCENES.map((s, i) => {
        const Comp = SCENE_COMPONENTS[s.id];
        // Scenes overlap by SCENE_OVERLAP frames so the outgoing plate is still
        // on screen while the next one fades up.
        const from = cursor;
        cursor += s.duration - SCENE_OVERLAP;
        return (
          <Sequence key={s.id} from={from} durationInFrames={s.duration} layout="none">
            <Transition
              duration={s.duration}
              isFirst={i === 0}
              isLast={i === SCENES.length - 1}
            >
              <Comp />
            </Transition>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
