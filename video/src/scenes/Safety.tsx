import React from 'react';
import {useCurrentFrame} from 'remotion';
import {Plate} from '../components/Plate';
import {Chip, Eyebrow, Mono, Panel} from '../components/primitives';
import {drawPath, pop, ramp} from '../lib/anim';
import {color, font, label} from '../theme';

const BOX = {x: 200, y: 300, w: 660, h: 336};
const NET = {x: 1420, y: 372, w: 300, h: 256};
const PROXY = {x: 1000, y: 738, w: 380, h: 132};

export const Safety: React.FC = () => {
  const frame = useCurrentFrame();

  const box = pop(frame, 16);
  const denied = ramp(frame, 76, 16);
  const proxy = pop(frame, 96);
  const foot = ramp(frame, 142, 22);

  return (
    <Plate plate="06" title="Safe by default" quiet>
      <div style={{position: 'absolute', left: 200, top: 104}}>
        <Eyebrow delay={2} tone={color.green}>
          Safe by default, not disclaimed
        </Eyebrow>
        <div
          style={{
            marginTop: 20,
            fontSize: 40,
            fontWeight: 500,
            color: color.inkSoft,
            opacity: ramp(frame, 10, 22),
          }}
        >
          Generated code runs network-denied —{' '}
          <span style={{color: color.amber}}>and fails closed, not open.</span>
        </div>
      </div>

      <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
        {/* sandbox → network, struck through */}
        {(() => {
          const x0 = BOX.x + BOX.w + 12;
          const x1 = NET.x - 12;
          const y = 470;
          const p = ramp(frame, 56, 20);
          return (
            <g>
              {/* Dashed, so it grows by extending its endpoint rather than by
                  unrolling a dash offset the dash pattern already owns. */}
              <line
                x1={x0}
                y1={y}
                x2={x0 + (x1 - x0) * p}
                y2={y}
                stroke={color.red}
                strokeWidth={1.5}
                strokeDasharray="8 8"
                opacity={0.7}
              />
              <g opacity={denied} transform={`translate(${(x0 + x1) / 2} ${y})`}>
                <circle r={26} fill={color.void} stroke={color.red} strokeWidth={2} />
                <line x1={-11} y1={-11} x2={11} y2={11} stroke={color.red} strokeWidth={2.5} />
                <line x1={11} y1={-11} x2={-11} y2={11} stroke={color.red} strokeWidth={2.5} />
              </g>
            </g>
          );
        })()}

        {/* sandboxed git → proxy → network */}
        {(() => {
          const p = ramp(frame, 104, 26);
          const start = {x: BOX.x + BOX.w / 2, y: BOX.y + BOX.h + 12};
          const d = `M ${start.x} ${start.y} L ${start.x} ${PROXY.y + 66} L ${PROXY.x - 12} ${
            PROXY.y + 66
          }`;
          const len = PROXY.y + 66 - start.y + (PROXY.x - 12 - start.x);
          return (
            <path
              d={d}
              fill="none"
              stroke={color.green}
              strokeWidth={1.5}
              {...drawPath(p, len)}
            />
          );
        })()}
        {(() => {
          const p = ramp(frame, 122, 24);
          const d = `M ${PROXY.x + PROXY.w + 12} ${PROXY.y + 66} L ${NET.x + NET.w / 2} ${
            PROXY.y + 66
          } L ${NET.x + NET.w / 2} ${NET.y + NET.h + 12}`;
          const len =
            NET.x + NET.w / 2 - (PROXY.x + PROXY.w + 12) + (PROXY.y + 66 - (NET.y + NET.h + 12));
          return (
            <path
              d={d}
              fill="none"
              stroke={color.green}
              strokeWidth={1.5}
              {...drawPath(p, len)}
            />
          );
        })()}
      </svg>

      {/* ---- sandbox ---- */}
      <div
        style={{
          position: 'absolute',
          left: BOX.x,
          top: BOX.y,
          width: BOX.w,
          height: BOX.h,
          border: `1.5px dashed ${color.green}88`,
          borderRadius: 18,
          background: `linear-gradient(160deg, ${color.green}0d, transparent 60%)`,
          opacity: Math.min(1, box * 1.4),
          transform: `scale(${0.97 + box * 0.03})`,
          padding: 26,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
          <span style={{...label, fontSize: 13, fontWeight: 600, color: color.green}}>
            Kernel sandbox
          </span>
          <span style={{flex: 1, height: 1, background: `${color.green}33`}} />
          <Chip tone={color.green} size={11}>
            macOS seatbelt
          </Chip>
        </div>

        <Panel
          style={{
            marginTop: 24,
            padding: '20px 22px',
            borderRadius: 12,
          }}
        >
          <Mono size={14} tone={color.faint} tracking="0.14em">
            GENERATED CODE
          </Mono>
          <div
            style={{
              marginTop: 14,
              fontFamily: font.mono,
              fontSize: 17,
              lineHeight: 1.7,
              color: color.inkSoft,
            }}
          >
            <div>
              <span style={{color: color.violet}}>import</span> pandas{' '}
              <span style={{color: color.violet}}>as</span> pd
            </div>
            <div>df = pd.read_parquet(<span style={{color: color.amberSoft}}>"q3.parquet"</span>)</div>
            <div>df.groupby(<span style={{color: color.amberSoft}}>"region"</span>).sum()</div>
          </div>
        </Panel>

        <div style={{marginTop: 22, display: 'flex', gap: 10, flexWrap: 'wrap'}}>
          <Chip tone={color.green} size={12}>
            no network
          </Chip>
          <Chip tone={color.green} size={12}>
            scoped fs
          </Chip>
          <Chip tone={color.green} size={12}>
            no raw tokens
          </Chip>
        </div>
      </div>

      {/* ---- network ---- */}
      <Panel
        style={{
          position: 'absolute',
          left: NET.x,
          top: NET.y,
          width: NET.w,
          height: NET.h,
          padding: '24px 26px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 14,
          opacity: ramp(frame, 40, 18),
        }}
      >
        <div style={{...label, fontSize: 13, color: color.muted, fontWeight: 600}}>
          Network
        </div>
        <Mono size={15} tone={color.faint}>
          the open internet
        </Mono>
      </Panel>

      <div
        style={{
          position: 'absolute',
          left: BOX.x + BOX.w + 70,
          top: 512,
          width: 420,
          opacity: denied,
          textAlign: 'center',
        }}
      >
        <Mono size={16} tone={color.red} tracking="0.18em">
          DENIED AT THE KERNEL
        </Mono>
      </div>

      {/* ---- credential proxy ---- */}
      <Panel
        tone={color.green}
        style={{
          position: 'absolute',
          left: PROXY.x,
          top: PROXY.y,
          width: PROXY.w,
          height: PROXY.h,
          padding: '20px 24px',
          opacity: Math.min(1, proxy * 1.4),
          transform: `translateY(${(1 - proxy) * 16}px)`,
        }}
      >
        <Mono size={13} tone={color.green} tracking="0.14em">
          CREDENTIAL-INJECTING PROXY
        </Mono>
        <div style={{marginTop: 12, fontSize: 18, color: color.inkSoft, lineHeight: 1.4}}>
          Sandboxed git reaches the network. The token never crosses the boundary.
        </div>
      </Panel>

      <div
        style={{
          position: 'absolute',
          left: 200,
          bottom: 128,
          display: 'flex',
          alignItems: 'center',
          gap: 18,
          opacity: foot,
        }}
      >
        <span style={{width: 40, height: 1, background: color.amberDeep}} />
        <Mono size={19} tone={color.muted}>
          Local-first · bring your own key · zero third-party servers in the middle.
        </Mono>
      </div>
    </Plate>
  );
};
