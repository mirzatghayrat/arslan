// Curated line-art avatar library: 20 human faces + 12 cats.
// Each variant is a fixed, vetted combination of parts. A spawn deterministically
// picks one variant + a generated colour from a hash of its name (see SpawnAvatar).
// Parts return SVG-fragment strings drawn in the given colour `c`.

type Part = (c: string) => string;

const S = (c: string) =>
  ` fill="none" stroke="${c}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"`;
const dot = (x: number, y: number, c: string) => `<circle cx="${x}" cy="${y}" r="2.5" fill="${c}"/>`;

const FS: Record<string, Part> = {
  round: (c) => `<path d="M27 50 Q27 25 50 25 Q73 25 73 50 Q73 80 50 82 Q27 80 27 50Z"${S(c)}/>`,
  oval: (c) => `<path d="M30 48 Q30 23 50 23 Q70 23 70 48 Q70 84 50 86 Q30 84 30 48Z"${S(c)}/>`,
  wide: (c) => `<path d="M25 50 Q25 29 50 29 Q75 29 75 50 Q75 77 50 79 Q25 77 25 50Z"${S(c)}/>`,
  heart: (c) => `<path d="M30 46 Q30 24 50 24 Q70 24 70 46 Q70 68 50 84 Q30 68 30 46Z"${S(c)}/>`,
  long: (c) => `<path d="M30 48 Q30 23 50 23 Q70 23 70 48 Q70 86 50 88 Q30 86 30 48Z"${S(c)}/>`,
  sq: (c) => `<path d="M28 48 Q28 28 38 27 Q50 26 62 27 Q72 28 72 48 Q72 76 62 79 Q50 80 38 79 Q28 76 28 48Z"${S(c)}/>`,
};

const HAIR: Record<string, Part> = {
  cap: (c) => `<path d="M25 45 Q27 21 50 21 Q73 21 75 45"${S(c)}/><path d="M34 30 Q42 25 50 27 Q58 25 66 30"${S(c)}/>`,
  sideL: (c) => `<path d="M27 46 Q25 19 50 19 Q75 19 73 42"${S(c)}/><path d="M50 21 Q40 24 33 36"${S(c)}/>`,
  sideR: (c) => `<path d="M27 42 Q27 19 50 19 Q75 19 73 46"${S(c)}/><path d="M50 21 Q60 24 67 36"${S(c)}/>`,
  bun: (c) => `<path d="M28 42 Q30 20 50 20 Q70 20 72 42"${S(c)}/><circle cx="50" cy="13" r="6"${S(c)}/>`,
  tuft: (c) => `<path d="M32 30 Q40 18 50 24"${S(c)}/><path d="M50 24 Q60 18 68 30"${S(c)}/>`,
  spiky: (c) => `<path d="M28 40 Q30 24 50 24 Q70 24 72 40"${S(c)}/><path d="M28 38 L33 27 L39 36 L45 25 L51 36 L57 25 L63 36 L70 29"${S(c)}/>`,
  curtain: (c) => `<path d="M25 46 Q23 20 50 20 Q77 20 75 46"${S(c)}/><path d="M50 22 V33"${S(c)}/><path d="M37 24 Q33 33 32 42"${S(c)}/><path d="M63 24 Q67 33 68 42"${S(c)}/>`,
  fringe: (c) => `<path d="M24 41 Q26 23 50 23 Q74 23 76 41"${S(c)}/><path d="M30 35 H45"${S(c)}/><path d="M55 35 H70"${S(c)}/>`,
  wavy: (c) => `<path d="M26 44 Q24 22 50 22 Q76 22 74 44"${S(c)}/><path d="M32 30 Q38 26 44 30 Q50 26 56 30 Q62 26 68 30"${S(c)}/>`,
  crop: (c) => `<path d="M27 42 Q29 23 50 23 Q71 23 73 42"${S(c)}/>`,
};

const EYE: Record<string, Part> = {
  dots: (c) => dot(42, 52, c) + dot(58, 52, c),
  lines: (c) => `<path d="M39 52 H47"${S(c)}/><path d="M53 52 H61"${S(c)}/>`,
  happy: (c) => `<path d="M39 54 Q43 50 47 54"${S(c)}/><path d="M53 54 Q57 50 61 54"${S(c)}/>`,
  round: (c) => `<circle cx="42" cy="53" r="3"${S(c)}/><circle cx="58" cy="53" r="3"${S(c)}/>`,
  sleepy: (c) => `<path d="M40 53 Q43 55 46 53"${S(c)}/><path d="M54 53 Q57 55 60 53"${S(c)}/>`,
  wink: (c) => dot(42, 52, c) + `<path d="M54 53 Q57 50 60 53"${S(c)}/>`,
};

const MOU: Record<string, Part> = {
  smile: (c) => `<path d="M45 64 Q50 68 55 64"${S(c)}/>`,
  line: (c) => `<path d="M46 66 H55"${S(c)}/>`,
  o: (c) => `<circle cx="50" cy="64" r="3"${S(c)}/>`,
  smirk: (c) => `<path d="M46 65 Q53 68 58 63"${S(c)}/>`,
};

const brow: Part = (c) => `<path d="M55 45 Q61 43 66 46"${S(c)}/>`;

const EARS: Record<string, Part> = {
  normal: (c) => `<path d="M32 38 L27 18 L46 32"${S(c)}/><path d="M68 38 L73 18 L54 32"${S(c)}/>`,
  big: (c) => `<path d="M31 36 L24 14 L47 30"${S(c)}/><path d="M69 36 L76 14 L53 30"${S(c)}/>`,
  small: (c) => `<path d="M34 38 L31 22 L45 32"${S(c)}/><path d="M66 38 L69 22 L55 32"${S(c)}/>`,
  tall: (c) => `<path d="M34 36 L30 12 L47 30"${S(c)}/><path d="M66 36 L70 12 L53 30"${S(c)}/>`,
  fold: (c) => `<path d="M32 38 L27 18 L46 32"${S(c)}/><path d="M70 34 Q78 26 72 20 Q66 28 56 30"${S(c)}/>`,
};

const CHEAD: Record<string, Part> = {
  round: (c) => `<path d="M28 52 Q28 32 50 32 Q72 32 72 52 Q72 80 50 82 Q28 80 28 52Z"${S(c)}/>`,
  wide: (c) => `<path d="M26 54 Q26 32 50 32 Q74 32 74 54 Q74 80 50 82 Q26 80 26 54Z"${S(c)}/>`,
  narrow: (c) => `<path d="M31 52 Q31 33 50 33 Q69 33 69 52 Q69 80 50 82 Q31 80 31 52Z"${S(c)}/>`,
};

const CEYE: Record<string, Part> = {
  dots: (c) => dot(42, 54, c) + dot(58, 54, c),
  closed: (c) => `<path d="M40 55 Q43 52 46 55"${S(c)}/><path d="M54 55 Q57 52 60 55"${S(c)}/>`,
  round: (c) => `<circle cx="42" cy="54" r="3"${S(c)}/><circle cx="58" cy="54" r="3"${S(c)}/>`,
  wink: (c) => dot(42, 54, c) + `<path d="M54 55 Q57 52 60 55"${S(c)}/>`,
  lines: (c) => `<path d="M40 54 H47"${S(c)}/><path d="M53 54 H60"${S(c)}/>`,
};

const catFeatures: Part = (c) =>
  `<path d="M47 62 L50 65 L53 62"${S(c)}/><path d="M50 65 Q46 68 43 66"${S(c)}/><path d="M50 65 Q54 68 57 66"${S(c)}/>` +
  `<path d="M30 60 H18"${S(c)}/><path d="M30 64 H20"${S(c)}/><path d="M70 60 H82"${S(c)}/><path d="M70 64 H80"${S(c)}/>`;

// [faceShape, hair, eyes, hasBrow(0/1), mouth]
const HUMAN: [string, string, string, number, string][] = [
  ["round", "cap", "dots", 0, "smile"], ["oval", "sideL", "dots", 1, "line"], ["wide", "fringe", "lines", 0, "smile"], ["heart", "bun", "dots", 0, "o"],
  ["round", "curtain", "happy", 0, "smile"], ["long", "spiky", "dots", 1, "line"], ["sq", "crop", "dots", 0, "smirk"], ["oval", "wavy", "lines", 0, "smile"],
  ["round", "tuft", "round", 0, "o"], ["wide", "cap", "sleepy", 0, "line"], ["heart", "sideR", "dots", 1, "smile"], ["long", "curtain", "dots", 0, "line"],
  ["sq", "bun", "lines", 0, "smile"], ["round", "fringe", "wink", 0, "smirk"], ["oval", "spiky", "dots", 0, "line"], ["wide", "crop", "happy", 0, "smile"],
  ["heart", "cap", "dots", 0, "smile"], ["long", "wavy", "lines", 0, "line"], ["round", "sideL", "round", 0, "smile"], ["sq", "tuft", "dots", 1, "smirk"],
];

// [catHead, ears, eyes]
const CAT: [string, string, string][] = [
  ["round", "normal", "dots"], ["round", "normal", "closed"], ["wide", "big", "round"], ["round", "fold", "wink"],
  ["narrow", "tall", "lines"], ["wide", "small", "dots"], ["round", "big", "dots"], ["narrow", "normal", "closed"],
  ["wide", "tall", "round"], ["round", "small", "wink"], ["narrow", "big", "dots"], ["wide", "normal", "closed"],
];

export const AVATAR_COUNT = HUMAN.length + CAT.length; // 32

/** Returns the inner SVG markup (no <svg> wrapper) for avatar `index` in colour `c`. */
export function avatarInnerSvg(index: number, c: string): string {
  const i = ((index % AVATAR_COUNT) + AVATAR_COUNT) % AVATAR_COUNT;
  if (i < HUMAN.length) {
    const [shape, hair, eyes, hasBrow, mouth] = HUMAN[i];
    return FS[shape](c) + HAIR[hair](c) + EYE[eyes](c) + (hasBrow ? brow(c) : "") + MOU[mouth](c);
  }
  const [head, ears, eyes] = CAT[i - HUMAN.length];
  return EARS[ears](c) + CHEAD[head](c) + CEYE[eyes](c) + catFeatures(c);
}
