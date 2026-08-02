import React from 'react';
import {Composition} from 'remotion';
import './fonts';
import {ArslanDemo} from './ArslanDemo';
import {ArslanLight} from './ArslanLight';
import {ArslanFilm, FILM_FRAMES} from './ArslanFilm';
import {Blueprint, BLUEPRINT_FRAMES, BLUEPRINT_SIZE} from './films/Blueprint';
import {Press, PRESS_FRAMES} from './films/Press';
import {Origin, ORIGIN_FRAMES} from './films/Origin';
import {Pulse, PULSE_FRAMES} from './films/Pulse';
import {Runway, RUNWAY_FRAMES} from './films/Runway';
import {System, SYSTEM_FRAMES} from './films/System';
import {Terminal, TERMINAL_FRAMES} from './films/Terminal';
import {ArslanShort, SHORT_FRAMES} from './ArslanShort';
import {SHOT_COUNT, ShotMock} from './ShotMock';
import {ColdOpen} from './scenes/ColdOpen';
import {Outro} from './scenes/Outro';
import {PromotionGate} from './scenes/PromotionGate';
import {RequestPath} from './scenes/RequestPath';
import {Roster} from './scenes/Roster';
import {Safety} from './scenes/Safety';
import {SecondBrain} from './scenes/SecondBrain';
import {Thesis} from './scenes/Thesis';
import {LIGHT_TOTAL} from './lightTheme';
import {Architecture} from './scenes/light/Architecture';
import {Creature} from './scenes/light/Creature';
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

    {/* Light cut: the character clip and the architecture, one continuous
        hand-off through the mark on the cat's chest. */}
    <Composition
      id="ArslanLight"
      component={ArslanLight}
      durationInFrames={LIGHT_TOTAL}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />
    {/* The cinematic cut, at two lengths. Both open on the character and pull
        back until it turns out to have been a screen, and both close by pulling
        back off the machine into the download rather than cutting to it. The 30
        is built out of arrivals and the 60 out of holds — see either file. */}
    <Composition
      id="ArslanShort"
      component={ArslanShort}
      durationInFrames={SHORT_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />
    <Composition
      id="ArslanFilm"
      component={ArslanFilm}
      durationInFrames={FILM_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* Four 30-second cuts, one per visual language. Each is self-contained:
        they share fonts and nothing else, because the brief was maximum
        stylistic distance between them. */}
    <Composition
      id="F1-Terminal"
      component={Terminal}
      durationInFrames={TERMINAL_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    <Composition
      id="F2-Press"
      component={Press}
      durationInFrames={PRESS_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    <Composition
      id="F3-System"
      component={System}
      durationInFrames={SYSTEM_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    <Composition
      id="F4-Pulse"
      component={Pulse}
      durationInFrames={PULSE_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* Square, for a LinkedIn feed — the only film with a named destination.
        A square post takes roughly half again the vertical space of 16:9 there,
        and a block diagram reads top-to-bottom anyway. */}
    <Composition
      id="F5-Blueprint"
      component={Blueprint}
      durationInFrames={BLUEPRINT_FRAMES}
      fps={VIDEO.fps}
      width={BLUEPRINT_SIZE}
      height={BLUEPRINT_SIZE}
    />

    {/* Built from a named shot list rather than a free hand, and from the real
        client rather than drawn UI — the only cut here whose frames are screen
        capture. 36s, because eight signature moves with the holds their cards
        require do not fit in thirty. */}
    <Composition
      id="F6-Runway"
      component={Runway}
      durationInFrames={RUNWAY_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* The Runway shot list at sixty seconds, opening and closing on the brand
        character. The emblem on the cat's chest is the Arslan mark, so the film
        pushes into it, hands off to the vector at the same place and size, and
        lets the mark hand off again into the first neon frame. */}
    <Composition
      id="F7-Origin"
      component={Origin}
      durationInFrames={ORIGIN_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* Framing mock-ups: one frame per shot, for `remotion still`. */}
    <Composition
      id="ShotMock"
      component={ShotMock}
      durationInFrames={SHOT_COUNT}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    <Composition
      id="Light-01-creature"
      component={Creature}
      durationInFrames={300}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />
    <Composition
      id="Light-02-architecture"
      component={Architecture}
      durationInFrames={300}
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
