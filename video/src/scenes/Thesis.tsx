import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Eyebrow, Mono, Rise} from '../components/primitives';
import {ramp} from '../lib/anim';
import {color} from '../theme';

/**
 * The three claims from the README masthead, one per beat, with the operative
 * clause carried in amber so the eye lands on it before the sentence is read.
 */
const LINES: {lead: string; hit: string; tail: string; at: number}[] = [
  {lead: 'You talk to ', hit: 'one host agent', tail: '.', at: 18},
  {
    lead: 'It routes work to persona spawns ',
    hit: 'you raised yourself',
    tail: '.',
    at: 62,
  },
  {
    lead: 'Their prompts improve on their own — but ',
    hit: 'you press Promote',
    tail: '.',
    at: 106,
  },
];

export const Thesis: React.FC = () => {
  const frame = useCurrentFrame();
  const foot = ramp(frame, 152, 24);

  return (
    <Plate plate="01" title="The shape of it" quiet>
      <AbsoluteFill
        style={{
          justifyContent: 'center',
          paddingLeft: 168,
          paddingRight: 168,
        }}
      >
        <div style={{marginBottom: 46}}>
          <Eyebrow delay={4}>What it is</Eyebrow>
        </div>

        <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
          {LINES.map((l, i) => (
            <Rise key={i} delay={l.at} size={68} weight={500}>
              <span style={{color: color.inkSoft}}>{l.lead}</span>
              <span style={{color: color.amber, fontWeight: 600}}>{l.hit}</span>
              <span style={{color: color.inkSoft}}>{l.tail}</span>
            </Rise>
          ))}
        </div>

        <div
          style={{
            marginTop: 58,
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            opacity: foot,
          }}
        >
          <span style={{width: 40, height: 1, background: color.amberDeep}} />
          <Mono size={20} tone={color.muted}>
            Runs on your machine · your API keys · zero third-party servers
          </Mono>
        </div>
      </AbsoluteFill>
    </Plate>
  );
};
