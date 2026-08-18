import React from 'react';
import {Img, staticFile} from 'remotion';
import {matrix3dFor, type Quad} from '../lib/homography';

/**
 * A photographed MacBook with the app composited into its screen.
 *
 * This replaces the hand-built `MacBook`, which was two hinged CSS planes with
 * a drawn keyboard. That read as a diagram of a laptop rather than a laptop,
 * and in a film whose whole job is to make the product look finished, the one
 * unconvincing object was the one holding the product.
 *
 * WHAT CHANGES BY USING PHOTOGRAPHS. The room is baked in. There is no floor to
 * orbit around any more, because the light, the shadow the machine casts on the
 * linen and the falloff on the back wall were all decided when the picture was
 * made. So the camera language becomes cuts between fixed angles with a push, a
 * pull or a drift inside each — which is what a product film mostly is anyway.
 * What it buys is that every frame is photographic.
 *
 * WHAT DOES NOT CHANGE. The screen is still live DOM. The app is real text and
 * a real `OffthreadVideo` transformed onto the glass, not baked to a texture,
 * so it stays sharp under a push and it stays editable in code.
 */

/**
 * The app's own coordinate space. Its aspect matches the straight-on mock-up's
 * glass (1271 x 879 as measured), so `front` shows the layout undistorted and
 * the angled mock-ups foreshorten it exactly as their cameras would have.
 */
export const SCREEN = {w: 1600, h: 1106};

/** Every mock-up was generated at 2048 square. */
export const MOCKUP_SIZE = 2048;

/** Corner rounding of the glass, in SCREEN units, scaled from the asset. */
const GLASS_RADIUS = 38;

/** Percent of the picture's width over which it cross-fades into the clamp. */
const EDGE_BLEND = 5;

export type MockupSpec = {
  /** Path under `public/`. */
  src: string;
  /**
   * The glass, in mock-up pixels.
   *
   * Measured, not guessed: flood-fill the glass from its own bright centre
   * (which survives the shadowed corners that a fixed threshold clips off),
   * take the convex hull, find the largest inscribed quadrilateral to locate
   * the four rounded corners, then fit each edge by total least squares over
   * the hull run between them and intersect neighbours. The corners are
   * therefore where the straight edges MEET — the corner the glass would have
   * if it were not rounded, which is the point a homography wants.
   */
  quad: Quad;
  /** Angle of the specular band across the glass, degrees. */
  glare: number;
  /** How strongly the room warms the glass, 0-1. */
  ambient: number;
  /**
   * The set, continued past the left and right edges of the picture.
   *
   * The mock-ups are 2048 square and the film is 16:9, so pulling back until
   * the frame is wider than the image runs off the picture into black — which
   * is exactly where the last shot wants to go, since the copy needs empty set
   * to sit on. Each entry is nine colours read down the outermost six pixel
   * columns of that side, played back as a vertical gradient. That is an edge
   * clamp of the real photograph rather than an invented backdrop: the set is a
   * smooth wash at both margins, so continuing each row outward at the colour
   * it already has is what the camera would have recorded.
   */
  edges: {left: string[]; right: string[]};
  /** Beyond the extended set. The picture's darkest corner. */
  void: string;
};

const rgb = (t: [number, number, number][]) => t.map(([r, g, b]) => `rgb(${r},${g},${b})`);

export const MOCKUPS = {
  /** Straight on. The only one whose glass is an undistorted rectangle. */
  front: {
    src: 'mockups/front.jpg',
    quad: {
      tl: [394.1, 589.0],
      tr: [1665.3, 589.0],
      br: [1670.1, 1468.0],
      bl: [389.9, 1468.0],
    },
    glare: 118,
    ambient: 0.2,
    edges: {
      left: rgb([[84, 30, 4], [97, 38, 1], [125, 57, 8], [157, 79, 15], [193, 105, 31], [221, 132, 50], [240, 152, 60], [147, 116, 88], [13, 8, 4]]),
      right: rgb([[94, 35, 5], [111, 46, 8], [140, 63, 12], [174, 91, 25], [205, 114, 39], [227, 141, 58], [244, 158, 72], [227, 202, 179], [110, 85, 63]]),
    },
    void: '#0d0501',
  },
  /** Three-quarter from the left, machine turned away. The workhorse angle. */
  threequarter: {
    src: 'mockups/threequarter.jpg',
    quad: {
      tl: [698.3, 393.4],
      tr: [1731.2, 567.2],
      br: [1715.9, 1341.0],
      bl: [703.1, 1125.5],
    },
    glare: 104,
    ambient: 0.26,
    edges: {
      left: rgb([[33, 10, 2], [39, 11, 0], [51, 18, 0], [65, 28, 1], [79, 34, 1], [188, 175, 161], [191, 178, 163], [0, 0, 0], [1, 1, 1]]),
      right: rgb([[75, 31, 2], [98, 49, 8], [136, 76, 18], [176, 112, 40], [203, 137, 59], [227, 158, 78], [26, 16, 9], [57, 52, 46], [12, 12, 8]]),
    },
    void: '#050201',
  },
  /** Near-profile, lit from behind. Strong falloff to the right of the glass. */
  side: {
    src: 'mockups/side.jpg',
    quad: {
      tl: [324.4, 538.3],
      tr: [1235.8, 584.3],
      br: [1243.9, 1336.0],
      bl: [323.1, 1364.2],
    },
    glare: 112,
    ambient: 0.24,
    edges: {
      left: rgb([[80, 28, 4], [88, 34, 1], [109, 46, 2], [127, 59, 5], [148, 72, 8], [163, 83, 14], [181, 160, 138], [0, 0, 0], [1, 1, 1]]),
      right: rgb([[102, 38, 4], [123, 56, 8], [154, 75, 12], [185, 97, 25], [208, 116, 39], [223, 134, 51], [201, 175, 152], [0, 0, 0], [2, 2, 2]]),
    },
    void: '#060201',
  },
  /** Looking down, machine turned on the set. Nothing around it but amber. */
  top: {
    src: 'mockups/top.jpg',
    quad: {
      tl: [794.7, 457.0],
      tr: [1553.6, 705.4],
      br: [1505.3, 1168.2],
      bl: [784.9, 910.0],
    },
    glare: 96,
    ambient: 0.3,
    edges: {
      left: rgb([[20, 4, 4], [33, 12, 3], [58, 22, 0], [113, 56, 8], [166, 93, 32], [202, 125, 57], [218, 140, 70], [226, 148, 73], [225, 147, 72]]),
      right: rgb([[24, 5, 0], [39, 12, 3], [61, 25, 4], [97, 45, 5], [135, 69, 16], [170, 94, 30], [192, 111, 45], [207, 125, 50], [214, 132, 56]]),
    },
    void: '#0f0301',
  },
} satisfies Record<string, MockupSpec>;

export type MockupName = keyof typeof MOCKUPS;

/**
 * The rectangle of the mock-up that fills the frame, in normalised mock-up
 * coordinates. `w` is the fraction of the image's width the frame spans, so
 * smaller is closer; `cx`/`cy` are the point held at frame centre.
 *
 * This is the camera now. Interpolating it gives push, pull and drift, which is
 * the whole vocabulary a flat plate honestly supports.
 */
export type View = {cx: number; cy: number; w: number};

/**
 * The glass treatment.
 *
 * Replacing every pixel inside the quad throws away the asset's baked
 * reflection along with its placeholder artwork, and an app composited flat
 * reads as a rectangle pasted onto a photograph. A 5x5 luminance probe of the
 * original glass was tried as a way to recover the lighting, and abandoned: the
 * placeholder wallpaper is itself a top-bright gradient, so what the probe
 * measures is artwork times lighting with no way to divide one out, and
 * reproducing the result would have washed the app beige. These layers are set
 * by eye per mock-up instead.
 */
const Glass: React.FC<{spec: MockupSpec}> = ({spec}) => (
  <>
    {/* Room light warming the glass, falling off away from the key. */}
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: `linear-gradient(${spec.glare + 60}deg, rgba(198,116,38,${spec.ambient}) 0%, rgba(198,116,38,${spec.ambient * 0.28}) 38%, rgba(198,116,38,0) 72%)`,
        mixBlendMode: 'multiply',
        pointerEvents: 'none',
      }}
    />
    {/* One soft specular band. Never a sweeping shine — this glass is still. */}
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: `linear-gradient(${spec.glare}deg, rgba(255,247,235,0.19) 0%, rgba(255,247,235,0.055) 26%, rgba(255,255,255,0) 47%)`,
        pointerEvents: 'none',
      }}
    />
    {/* The glass sits a hair below the bezel, so its edge catches a shadow. */}
    <div
      style={{
        position: 'absolute',
        inset: 0,
        borderRadius: GLASS_RADIUS,
        boxShadow: 'inset 0 0 26px rgba(24,14,6,0.28), inset 0 2px 5px rgba(24,14,6,0.40)',
        pointerEvents: 'none',
      }}
    />
  </>
);

/**
 * One mock-up filling the frame, with `children` on its screen.
 *
 * The image is laid out at its native 2048 square and the whole thing is then
 * scaled and offset by `view`, so the app is transformed once — onto the glass
 * — and the camera move rides on top of it. Folding the camera into the
 * homography instead would recompute the projection every frame for no gain and
 * make the numbers impossible to reason about between shots.
 */
export const Mockup: React.FC<{
  mockup: MockupName;
  view: View;
  children?: React.ReactNode;
  /** Frame size. Defaults to the composition's 1920x1080. */
  frame?: {w: number; h: number};
  opacity?: number;
}> = ({mockup, view, children, frame = {w: 1920, h: 1080}, opacity = 1}) => {
  const spec = MOCKUPS[mockup];
  const scale = frame.w / (view.w * MOCKUP_SIZE);
  const tx = frame.w / 2 - scale * view.cx * MOCKUP_SIZE;
  const ty = frame.h / 2 - scale * view.cy * MOCKUP_SIZE;

  return (
    <>
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: MOCKUP_SIZE,
        height: MOCKUP_SIZE,
        transformOrigin: '0 0',
        transform: `translate(${tx}px, ${ty}px) scale(${scale})`,
        opacity,
      }}
    >
      {/* The set continued sideways, so a wide frame has picture in it.
          The clamp is faithful but cannot be carried far: `front`'s right edge
          crosses the lit linen, and a bright row extended a whole image width
          becomes a pale slab that reads as a wall. So it is taken out to the
          picture's own darkest corner within the first half, which doubles as
          the falloff a real set has at the edge of the light and buries the
          seam under the part of the ramp that is already moving. */}
      {(['left', 'right'] as const).map((side) => (
        <div
          key={side}
          style={{
            position: 'absolute',
            [side === 'left' ? 'right' : 'left']: `${100 - EDGE_BLEND}%`,
            top: 0,
            width: MOCKUP_SIZE,
            height: MOCKUP_SIZE,
            background: `linear-gradient(180deg, ${spec.edges[side].join(', ')})`,
          }}
        >
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: `linear-gradient(to ${side}, ${spec.void}00 0%, ${spec.void}dd 26%, ${spec.void} 52%)`,
            }}
          />
        </div>
      ))}

      {/* The picture's own margins dissolve into the clamp rather than butting
          against it. Reproducing an edge column as an interpolated gradient is
          never exact to the pixel, and a straight join showed as a hairline the
          length of the frame; crossing the two over the outer few per cent
          removes it. Nothing is lost — the machine never comes within this much
          of the edge in any of the four pictures. */}
      <Img
        src={staticFile(spec.src)}
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: MOCKUP_SIZE,
          height: MOCKUP_SIZE,
          maskImage: `linear-gradient(90deg, transparent 0%, #000 ${EDGE_BLEND}%, #000 ${100 - EDGE_BLEND}%, transparent 100%)`,
          WebkitMaskImage: `linear-gradient(90deg, transparent 0%, #000 ${EDGE_BLEND}%, #000 ${100 - EDGE_BLEND}%, transparent 100%)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: SCREEN.w,
          height: SCREEN.h,
          transformOrigin: '0 0',
          transform: matrix3dFor(SCREEN.w, SCREEN.h, spec.quad),
          borderRadius: GLASS_RADIUS,
          overflow: 'hidden',
          background: '#FAFBFC',
        }}
      >
        {children}
        <Glass spec={spec} />
      </div>
    </div>

    {/* Vignette, in FRAME space rather than plate space, so it stays put while
        the camera moves instead of sliding around with the picture. It pulls
        the four mock-ups — shot at different distances and carrying different
        amounts of set — into looking like one roll of film. */}
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background:
          'radial-gradient(76% 82% at 50% 46%, rgba(0,0,0,0) 42%, rgba(0,0,0,0.34) 100%)',
        pointerEvents: 'none',
      }}
    />
    </>
  );
};

/** Bounding box of a mock-up's glass, normalised. */
export const glassBox = (mockup: MockupName) => {
  const q = MOCKUPS[mockup].quad;
  const xs = [q.tl[0], q.tr[0], q.br[0], q.bl[0]];
  const ys = [q.tl[1], q.tr[1], q.br[1], q.bl[1]];
  return {
    x0: Math.min(...xs) / MOCKUP_SIZE,
    x1: Math.max(...xs) / MOCKUP_SIZE,
    y0: Math.min(...ys) / MOCKUP_SIZE,
    y1: Math.max(...ys) / MOCKUP_SIZE,
  };
};

/**
 * The view that fills the frame with a mock-up's glass — the opening of the
 * film, where the character clip is full bleed and nothing yet says "screen".
 *
 * `bleed` above 1 pushes in past the glass so no bezel shows at the start; the
 * pull-back from there is then one uninterrupted move.
 */
export const insideGlass = (mockup: MockupName, bleed = 1): View => {
  const b = glassBox(mockup);
  return {
    cx: (b.x0 + b.x1) / 2,
    cy: (b.y0 + b.y1) / 2,
    w: (b.x1 - b.x0) / bleed,
  };
};
