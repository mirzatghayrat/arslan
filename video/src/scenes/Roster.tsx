import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Chip, Eyebrow, Mono, Panel} from '../components/primitives';
import {pop, ramp} from '../lib/anim';
import {color, label} from '../theme';

/** The roster from the client's Spawns Ledger, trimmed to six. */
const SPAWNS = [
  {
    name: 'Research Analyst',
    kind: 'RESEARCH · WEB · SYNTHESIS',
    items: ['web research', 'source triangulation'],
    mcp: ['fetch', 'nation-mcp-server'],
    n: 3,
  },
  {
    name: 'Data & Chart Analyst',
    kind: 'ANALYTICS · DATA · VISUALIZATION',
    items: ['data analysis', 'matplotlib'],
    mcp: ['memory', 'sequential-thinking'],
    n: 4,
  },
  {
    name: 'Content & Copywriter',
    kind: 'MARKETING · CONTENT · COPYWRITING',
    items: ['copywriting', 'content strategy'],
    mcp: ['fetch', 'notion'],
    n: 3,
  },
  {
    name: 'Coding Assistant',
    kind: 'ENGINEERING · SOFTWARE DEVELOPMENT',
    items: ['ruff', 'debugging'],
    mcp: ['github-mcp-server', 'git'],
    n: 4,
  },
  {
    name: 'Financial Research Analyst',
    kind: 'FINANCE · MARKET RESEARCH',
    items: ['market & financial research', 'competitive landscape'],
    mcp: ['brave-search', 'fetch'],
    n: 4,
  },
  {
    name: 'Deck Master',
    kind: 'DESIGN · PRESENTATION',
    items: ['presentation discipline', 'deck design'],
    mcp: ['filesystem', 'memory'],
    n: 3,
  },
];

const CARD_W = 500;
const CARD_H = 272;
const GAP_X = 50;
const GAP_Y = 26;
const ORIGIN_X = 160;
const ORIGIN_Y = 266;

export const Roster: React.FC = () => {
  const frame = useCurrentFrame();
  const foot = ramp(frame, 176, 24);

  return (
    <Plate plate="03" title="A team you raise" quiet>
      <div style={{position: 'absolute', left: 160, top: 108}}>
        <Eyebrow delay={2}>A persona team you grow</Eyebrow>
        <div
          style={{
            marginTop: 20,
            fontSize: 40,
            fontWeight: 500,
            color: color.inkSoft,
            opacity: ramp(frame, 10, 22),
          }}
        >
          Arslan is the front door.{' '}
          <span style={{color: color.amber}}>You build the specialists behind it.</span>
        </div>
      </div>

      {SPAWNS.map((s, i) => {
        const col = i % 3;
        const row = Math.floor(i / 3);
        const p = pop(frame, 34 + col * 7 + row * 16);
        return (
          <Panel
            key={s.name}
            style={{
              position: 'absolute',
              left: ORIGIN_X + col * (CARD_W + GAP_X),
              top: ORIGIN_Y + row * (CARD_H + GAP_Y),
              width: CARD_W,
              height: CARD_H,
              padding: '22px 24px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              opacity: Math.min(1, p * 1.5),
              transform: `translateY(${(1 - p) * 30}px) scale(${0.96 + p * 0.04})`,
            }}
          >
            <div>
              <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 10,
                    border: `1px solid ${color.amber}59`,
                    background: `${color.amber}12`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  <span style={{...label, fontSize: 13, color: color.amber, fontWeight: 600}}>
                    {s.name[0]}
                  </span>
                </div>
                <div style={{flex: 1, minWidth: 0}}>
                  <div
                    style={{
                      fontSize: 22,
                      fontWeight: 600,
                      color: color.ink,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {s.name}
                  </div>
                  <div style={{...label, fontSize: 10.5, color: color.faint, marginTop: 5}}>
                    {s.kind}
                  </div>
                </div>
                <Chip tone={color.green} size={11}>
                  idle
                </Chip>
              </div>

              <div
                style={{
                  marginTop: 20,
                  ...label,
                  fontSize: 10.5,
                  color: color.faint,
                }}
              >
                Equipped
              </div>
              <div style={{marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
                {s.items.map((it) => (
                  <Chip key={it} tone={color.mutedDim} size={12}>
                    {it}
                  </Chip>
                ))}
              </div>

              <div style={{marginTop: 18, ...label, fontSize: 10.5, color: color.faint}}>
                MCP servers
              </div>
              <div style={{marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap'}}>
                {s.mcp.map((m) => (
                  <Chip key={m} tone={color.violet} size={12}>
                    {m}
                  </Chip>
                ))}
              </div>
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                borderTop: `1px solid ${color.rule}`,
                paddingTop: 14,
              }}
            >
              <Mono size={13} tone={color.faint}>
                {s.n} skill pack{s.n === 1 ? '' : 's'} · {s.mcp.length} MCP
              </Mono>
              <Chip tone={color.amber} size={11} filled>
                configure
              </Chip>
            </div>
          </Panel>
        );
      })}

      <div
        style={{
          position: 'absolute',
          left: 160,
          bottom: 128,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          opacity: foot,
          transform: `translateY(${(1 - foot) * 10}px)`,
        }}
      >
        <span style={{width: 40, height: 1, background: color.amberDeep}} />
        <Mono size={19} tone={color.muted}>
          Equip them with tools, SKILL.md packs, and MCP servers — then let the
          evolution loop refine them.
        </Mono>
      </div>
    </Plate>
  );
};
