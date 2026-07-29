import React from 'react';

/**
 * A MacBook Pro built as real geometry in the CSS-3D world: a display plane
 * hinged to a base slab. The camera can orbit it and `children` render live on
 * the screen.
 *
 * Proportions follow a 14" Pro rather than being eyeballed — an earlier pass
 * had the base as deep as the lid is tall and read as a 17" desktop
 * replacement. Real 14" Pro is 312.6 x 221.2 x 15.5mm, so the lid is ~1.41x
 * wider than tall, the base is exactly as deep as the lid is tall (they stack
 * when shut), and the slab is only ~7% of the lid height.
 */

export const SCREEN = {w: 1920, h: 1240};

/** mm -> world units, using the 14" Pro's 312.6mm width as the reference. */
const MM = (SCREEN.w + 44) / 312.6;

const BEZEL = 22;
const CHIN = 74;
const LID_W = SCREEN.w + BEZEL * 2;
const LID_H = SCREEN.h + BEZEL + CHIN;
const LID_THICKNESS = 15.5 * MM * 0.62;

/** Base is as deep as the lid is tall; they stack flush when closed. */
const BASE_D = LID_H * 0.88;
const BASE_T = 15.5 * MM;

/** Degrees the lid leans back from vertical. */
const LID_LEAN = 12;

export type Alu = {
  light: string;
  mid: string;
  dark: string;
  deep: string;
  edge: string;
  /** Keyboard well + display glass. */
  well: string;
};

/**
 * Aluminium has to be lit by the room it is in. Rendering the bright silver
 * body into the warm low-key environment made the machine look pasted on — a
 * white laptop floating in a dark photograph. Each environment supplies its own
 * metal.
 */
export const ALU_SILVER: Alu = {
  light: '#eceef1',
  mid: '#d3d7dd',
  dark: '#aeb3bc',
  deep: '#8f949e',
  edge: '#f6f7f9',
  well: '#17191d',
};

export type MacBookProps = {
  /** World position of the hinge (centre of the back edge of the base). */
  position?: [number, number, number];
  /** Degrees the whole machine is turned on the desk. */
  yaw?: number;
  scale?: number;
  /** 0 = closed, 1 = fully open. */
  open?: number;
  /** Screen contents, laid out in a SCREEN.w x SCREEN.h box. */
  children?: React.ReactNode;
  /** 0-1 strength of the diagonal glare across the display. */
  glare?: number;
  /** Contact shadow opacity. */
  shadow?: number;
  opacity?: number;
  /** Rim light along the aluminium edges — for dark environments. */
  rim?: number;
  /** Metal, supplied by the environment. */
  alu?: Alu;
};

const Plane: React.FC<{
  w: number;
  h: number;
  transform: string;
  style?: React.CSSProperties;
  children?: React.ReactNode;
}> = ({w, h, transform, style, children}) => (
  <div
    style={{
      position: 'absolute',
      left: -w / 2,
      top: -h / 2,
      width: w,
      height: h,
      transform,
      transformStyle: 'preserve-3d',
      ...style,
    }}
  >
    {children}
  </div>
);

export const MacBook: React.FC<MacBookProps> = ({
  position = [0, 0, 0],
  yaw = 0,
  scale = 1,
  open = 1,
  children,
  glare = 0.3,
  shadow = 0.5,
  opacity = 1,
  rim = 0,
  alu = ALU_SILVER,
}) => {
  const ALU = alu;
  const lean = LID_LEAN * open + (1 - open) * -89;

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        transformStyle: 'preserve-3d',
        transform: `translate3d(${position[0]}px, ${position[1]}px, ${position[2]}px) rotateY(${yaw}deg) scale3d(${scale}, ${scale}, ${scale})`,
        opacity,
      }}
    >
      {/* ---------- contact shadow ----------
          Sits just ABOVE the desk plane (smaller y is higher). Putting it level
          with or below the floor hides it behind the floor's own fill. */}
      {shadow > 0 ? (
        <Plane
          w={LID_W * 1.28}
          h={BASE_D * 1.9}
          transform={`rotateX(90deg) translateY(${BASE_D * 0.44}px) translateZ(${-BASE_T / 2 + 4}px)`}
          style={{
            background: `radial-gradient(50% 50% at 50% 50%, rgba(0,0,0,${0.62 * shadow}) 0%, rgba(0,0,0,${0.3 * shadow}) 34%, rgba(0,0,0,0) 68%)`,
            filter: 'blur(30px)',
          }}
        />
      ) : null}

      {/* ---------- base slab ---------- */}
      <Plane
        w={LID_W}
        h={BASE_D}
        transform={`rotateX(90deg) translateY(${BASE_D / 2}px) translateZ(${BASE_T / 2}px)`}
        style={{
          background: `linear-gradient(178deg, ${ALU.mid} 0%, ${ALU.light} 22%, ${ALU.mid} 70%, ${ALU.dark} 100%)`,
          borderRadius: 26,
          overflow: 'hidden',
          boxShadow: rim > 0 ? `inset 0 0 0 1.5px ${ALU.edge}` : undefined,
        }}
      >
        {/* speaker grilles flank the keyboard */}
        {[0.045, 0.878].map((L) => (
          <div
            key={L}
            style={{
              position: 'absolute',
              left: `${L * 100}%`,
              top: '6%',
              width: '7.7%',
              height: '46%',
              borderRadius: 6,
              background:
                `repeating-linear-gradient(90deg, ${ALU.dark} 0 2px, ${ALU.mid} 2px 5px)`,
              opacity: 0.75,
            }}
          />
        ))}

        {/* keyboard well */}
        <div
          style={{
            position: 'absolute',
            left: '13.5%',
            top: '5.5%',
            width: '73%',
            height: '47%',
            borderRadius: 10,
            background: ALU.well,
            boxShadow: 'inset 0 3px 8px rgba(0,0,0,0.55)',
            display: 'grid',
            gridTemplateRows: 'repeat(6, 1fr)',
            gap: 5,
            padding: 9,
          }}
        >
          {Array.from({length: 6}).map((_, r) => (
            <div
              key={r}
              style={{
                display: 'grid',
                gridTemplateColumns: r === 5 ? '1fr 1fr 1fr 5fr 1fr 1fr 1fr' : 'repeat(14, 1fr)',
                gap: 5,
              }}
            >
              {Array.from({length: r === 5 ? 7 : 14}).map((__, c) => (
                <div
                  key={c}
                  style={{
                    background: `linear-gradient(180deg, ${ALU.well}, #000)`,
                    borderRadius: 3.5,
                    boxShadow: '0 1px 0 rgba(0,0,0,0.55)',
                  }}
                />
              ))}
            </div>
          ))}
        </div>

        {/* trackpad */}
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            top: '60%',
            width: '33%',
            height: '33%',
            borderRadius: 12,
            background: `linear-gradient(180deg, ${ALU.light}, ${ALU.mid})`,
            boxShadow: 'inset 0 0 0 1.5px rgba(140,147,158,0.5)',
          }}
        />
      </Plane>

      {/* front edge, with the shallow finger slot the reference shows */}
      <Plane
        w={LID_W}
        h={BASE_T}
        transform={`translateZ(${BASE_D}px)`}
        style={{
          background: `linear-gradient(180deg, ${ALU.edge} 0%, ${ALU.mid} 45%, ${ALU.deep} 100%)`,
          borderBottomLeftRadius: 9,
          borderBottomRightRadius: 9,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            top: 0,
            width: '17%',
            height: '82%',
            borderBottomLeftRadius: 40,
            borderBottomRightRadius: 40,
            background: `linear-gradient(180deg, ${ALU.deep}, ${ALU.dark})`,
            opacity: 0.9,
          }}
        />
      </Plane>

      {/* ---------- lid ---------- */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          transformStyle: 'preserve-3d',
          transform: `rotateX(${lean}deg)`,
        }}
      >
        {/* aluminium shell behind the display */}
        <Plane
          w={LID_W}
          h={LID_H}
          transform={`translateY(${-LID_H / 2}px) translateZ(${-LID_THICKNESS}px) rotateY(180deg)`}
          style={{
            background: `linear-gradient(165deg, ${ALU.light}, ${ALU.dark} 60%, ${ALU.deep})`,
            borderRadius: 24,
          }}
        />

        {/* display face: black glass, thin uniform bezel, notch */}
        <Plane
          w={LID_W}
          h={LID_H}
          transform={`translateY(${-LID_H / 2}px)`}
          style={{
            background: ALU.well,
            borderRadius: 24,
            overflow: 'hidden',
            boxShadow: `0 0 0 2px ${ALU.dark}, inset 0 0 0 1px rgba(255,255,255,${0.06 + 0.3 * rim})`,
          }}
        >
          <div
            style={{
              position: 'absolute',
              left: BEZEL,
              top: BEZEL,
              width: SCREEN.w,
              height: SCREEN.h,
              overflow: 'hidden',
              borderRadius: 5,
              background: '#ffffff',
            }}
          >
            {children}
          </div>

          {/* notch */}
          <div
            style={{
              position: 'absolute',
              left: '50%',
              transform: 'translateX(-50%)',
              top: 0,
              width: 236,
              height: BEZEL + 18,
              background: ALU.well,
              borderBottomLeftRadius: 11,
              borderBottomRightRadius: 11,
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'center',
              paddingBottom: 5,
            }}
          >
            <div style={{width: 7, height: 7, borderRadius: 7, background: '#1b2733'}} />
          </div>

          {/* one soft diagonal band of glare, never a sweeping shine */}
          {glare > 0 ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background: `linear-gradient(118deg, rgba(255,255,255,${0.15 * glare}) 0%, rgba(255,255,255,${0.045 * glare}) 24%, rgba(255,255,255,0) 44%)`,
                pointerEvents: 'none',
              }}
            />
          ) : null}
        </Plane>
      </div>
    </div>
  );
};
