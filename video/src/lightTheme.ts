/**
 * The light half of the product's own palette — copied from the `:root` /
 * `[data-palette="current"]` block in `web/src/theme/tokens.css`, which is the
 * app's DEFAULT theme, not an invention for this film.
 *
 * It also happens to be the right ground for the character footage: the cat is
 * cream ceramic on a near-white circuit wall lit amber, and `--primary`
 * (#D9741A) is a hair warmer than the dark theme's #e6863c, so the emblem on
 * its chest and the product's accent are effectively the same colour.
 */
export const light = {
  // Surfaces
  background: '#FAFBFC',
  surface: '#FFFFFF',
  surfaceRaised: '#F5F7FA',

  // Ink
  ink: '#0F172A',
  muted: '#64748B',
  subtle: '#94A3B8',

  // Rules
  border: '#E2E8F0',
  borderStrong: '#CBD5E1',

  // Accent
  primary: '#D9741A',
  primaryHover: '#C2640C',
  hub: '#B45309',

  // Signals
  success: '#059669',
  danger: '#DC2626',
  warning: '#B45309',
  info: '#2563EB',
} as const;

/** Source clip geometry, measured rather than guessed. */
export const CHARACTER = {
  src: 'character/arslan-cat.mp4',
  width: 1280,
  height: 720,
  /** 86 source frames at 24fps → 107 frames at the film's 30fps. */
  frames: 107,
  /**
   * Centre of the amber emblem on the cat's chest, normalised to the frame, on
   * the settled final pose. Found by taking the centroid of saturated-amber
   * pixels in the lower-centre box (the eyes are the same hue, so the upper
   * third is excluded). Span there is 83x76px — a clean lock, unlike the
   * mid-clip frames where the glowing wall traces contaminate the measurement.
   *
   * That emblem is the Arslan mark: one node with legs radiating out of it.
   * The film cuts from it straight into the vector mark, so the character's
   * chest and the architecture diagram are literally the same drawing.
   */
  emblem: {
    x: 0.477,
    y: 0.582,
    /**
     * Span of the emblem as the EYE reads it — the whole glowing figure, not
     * the saturated core the centroid pass measured (83px). The arms and their
     * end nodes fall off in intensity, so the visible figure is wider than the
     * pixels that survive a strict amber threshold.
     */
    size: 98 / 1280,
  },
} as const;

export const LIGHT_SCENES = [
  {id: 'creature', duration: 300},
  {id: 'architecture', duration: 300},
] as const;

export const LIGHT_OVERLAP = 12;

export const LIGHT_TOTAL =
  LIGHT_SCENES.reduce((n, s) => n + s.duration, 0) -
  (LIGHT_SCENES.length - 1) * LIGHT_OVERLAP;
