import React from 'react';
import {AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame} from 'remotion';
import {Architecture} from './scenes/light/Architecture';
import {Creature} from './scenes/light/Creature';
import {light, LIGHT_OVERLAP, LIGHT_SCENES} from './lightTheme';

const SCENE_COMPONENTS: Record<string, React.FC> = {
  creature: Creature,
  architecture: Architecture,
};

/**
 * Straight dissolves, no scale. The dark film cross-wipes between plates
 * because they are separate drawings; here the mark is continuous across the
 * seam, so anything that moves the frame would break the hand-off.
 */
const Dissolve: React.FC<{
  duration: number;
  isFirst: boolean;
  isLast: boolean;
  children: React.ReactNode;
}> = ({duration, isFirst, isLast, children}) => {
  const frame = useCurrentFrame();
  const easing = Easing.bezier(0.4, 0, 0.2, 1);
  const inP = isFirst
    ? 1
    : interpolate(frame, [0, LIGHT_OVERLAP], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing,
      });
  const outP = isLast
    ? 1
    : interpolate(frame, [duration - LIGHT_OVERLAP, duration], [1, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
        easing,
      });
  return <AbsoluteFill style={{opacity: inP * outP}}>{children}</AbsoluteFill>;
};

export const ArslanLight: React.FC = () => {
  let cursor = 0;
  return (
    <AbsoluteFill style={{backgroundColor: light.background}}>
      {LIGHT_SCENES.map((s, i) => {
        const Comp = SCENE_COMPONENTS[s.id];
        const from = cursor;
        cursor += s.duration - LIGHT_OVERLAP;
        return (
          <Sequence key={s.id} from={from} durationInFrames={s.duration} layout="none">
            <Dissolve
              duration={s.duration}
              isFirst={i === 0}
              isLast={i === LIGHT_SCENES.length - 1}
            >
              <Comp />
            </Dissolve>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
