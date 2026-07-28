/**
 * Palette + type scale lifted from the Arslan site and README plates
 * (docs/index.html, docs/diagrams/*) so the video reads as the same
 * blueprint, not as a separate piece of marketing art.
 */

export const color = {
  // Plate
  void: '#0a0b0e',
  plate: '#0e0f13',
  panel: '#1a1b21',
  panelHi: '#26272e',

  // Rules & strokes
  rule: '#35373f',
  ruleHi: '#4c4e58',

  // Type
  ink: '#ededf0',
  inkSoft: '#cfd0d6',
  muted: '#93959e',
  mutedDim: '#7b7d88',
  faint: '#585a65',

  // Accent — Arslan amber
  amber: '#e6863c',
  amberHi: '#f2a768',
  amberSoft: '#f8cd9e',
  amberDeep: '#96551e',
  amberInk: '#4d3418',

  // Signal colors (used sparingly, same hues as the client's status chips)
  green: '#9fe0b5',
  violet: '#b497cf',
  pink: '#ff9ffc',
  red: '#ff8f8f',
} as const;

export const font = {
  sans: "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif",
  mono: "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace",
} as const;

/** Wide letterspaced mono, the site's label voice. */
export const label = {
  fontFamily: font.mono,
  letterSpacing: '0.28em',
  textTransform: 'uppercase' as const,
};

export const VIDEO = {
  width: 1920,
  height: 1080,
  fps: 30,
} as const;

/**
 * Scene table. Durations are in frames at 30fps and are the single source of
 * truth — `ArslanDemo` lays scenes out by walking this list, so re-timing a
 * scene here shifts everything after it automatically.
 */
export const SCENES = [
  {id: 'cold-open', plate: '00', title: 'Arslan', duration: 150},
  {id: 'thesis', plate: '01', title: 'The shape of it', duration: 195},
  {id: 'request-path', plate: '02', title: 'Request path', duration: 315},
  {id: 'roster', plate: '03', title: 'A team you raise', duration: 240},
  {id: 'promotion', plate: '04', title: 'Promotion gate', duration: 315},
  {id: 'second-brain', plate: '05', title: 'Second brain', duration: 255},
  {id: 'safety', plate: '06', title: 'Safe by default', duration: 195},
  {id: 'outro', plate: '07', title: 'Get it', duration: 165},
] as const;

/** Frames of overlap between consecutive scenes, for the cross-fade. */
export const SCENE_OVERLAP = 12;

/** Scenes overlap, so the film is shorter than the sum of its plates. */
export const TOTAL_FRAMES =
  SCENES.reduce((n, s) => n + s.duration, 0) - (SCENES.length - 1) * SCENE_OVERLAP;
