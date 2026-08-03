import React from 'react';
import {Composition} from 'remotion';
import './fonts';
import {ArslanDemo} from './ArslanDemo';
import {ArslanLight} from './ArslanLight';
import {ArslanFilm, FILM_FRAMES} from './ArslanFilm';
import {Blueprint, BLUEPRINT_FRAMES, BLUEPRINT_SIZE} from './films/Blueprint';
import {Glass, Glass15, Glass15V, GLASS_FRAMES, GLASS15_FRAMES} from './films/Glass';
import {Press, PRESS_FRAMES} from './films/Press';
import {Origin, ORIGIN_FRAMES} from './films/Origin';
import {Pulse, PULSE_FRAMES} from './films/Pulse';
import {Runway, RUNWAY_FRAMES} from './films/Runway';
import {Silk, SILK_FPS, SILK_FRAMES} from './films/Silk';
import {Stage, STAGE_FRAMES} from './films/Stage';
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

    {/* Sixty frames a second, no cuts at all, and every transition through a
        bloomed defocus — built after a reference ad was pulled apart frame by
        frame. The only composition here that is not 30fps. */}
    <Composition
      id="F8-Silk"
      component={Silk}
      durationInFrames={SILK_FRAMES}
      fps={SILK_FPS}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* The staging of the MiniMax H3 generation — a screen floating in black on
        a reflective floor with an amber rim, the creature beside it — rebuilt so
        that the text on every screen is a real screenshot instead of a
        hallucination. Opens on the 2K character the model got right. */}
    <Composition
      id="F9-Stage"
      component={Stage}
      durationInFrames={STAGE_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* The 60s cinematic cut with the real client behind the glass instead of a
        drawing of it. Same SHOTS array as ArslanFilm — imported, not copied — so
        the camera is identical; only what is on the screen changes. Everything
        stays inside the machine, and there are no captions. */}
    <Composition
      id="F10-Glass"
      component={Glass}
      durationInFrames={GLASS_FRAMES}
      fps={VIDEO.fps}
      width={VIDEO.width}
      height={VIDEO.height}
    />

    {/* The same film at fifteen seconds and 2560x1440 — three product screens
        instead of six, because at a quarter of the length a change every two
        seconds gives no page time to be read and multiplies the chances of the
        join between screenshot and glass being noticed. */}
    <Composition
      id="F11-Glass15"
      component={Glass15}
      durationInFrames={GLASS15_FRAMES}
      fps={VIDEO.fps}
      width={2560}
      height={1440}
    />

    {/* The same 15 in 3:4 for Xiaohongshu. A 16:9 note is shown letterboxed and
        small in that feed; the mock-up maths is normalised to frame width, so a
        taller frame keeps the machine the same size and gives it room above and
        below instead of cropping it. */}
    <Composition
      id="F12-Glass15-RED"
      component={Glass15V}
      durationInFrames={GLASS15_FRAMES}
      fps={VIDEO.fps}
      width={1080}
      height={1440}
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
