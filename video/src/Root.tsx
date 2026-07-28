import React from 'react';
import {Composition} from 'remotion';
import './fonts';
import {ArslanDemo} from './ArslanDemo';
import {ColdOpen} from './scenes/ColdOpen';
import {Outro} from './scenes/Outro';
import {PromotionGate} from './scenes/PromotionGate';
import {RequestPath} from './scenes/RequestPath';
import {Roster} from './scenes/Roster';
import {Safety} from './scenes/Safety';
import {SecondBrain} from './scenes/SecondBrain';
import {Thesis} from './scenes/Thesis';
import {SCENES, TOTAL_FRAMES, VIDEO} from './theme';

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

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="ArslanDemo"
      component={ArslanDemo}
      durationInFrames={TOTAL_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* Each plate is also registered on its own, so a single scene can be
        re-timed in the Studio without scrubbing through the whole film. */}
    {SCENES.map((s) => (
      <Composition
        key={s.id}
        id={`Scene-${s.plate}-${s.id}`}
        component={SCENE_COMPONENTS[s.id]}
        durationInFrames={s.duration}
        fps={VIDEO.fps}
        width={VIDEO.width}
        height={VIDEO.height}
      />
    ))}
  </>
);
