export type Pt = {x: number; y: number};

/** Cubic bezier evaluated at t — used to fly packets along the wiring. */
export const cubic = (p0: Pt, c0: Pt, c1: Pt, p1: Pt, t: number): Pt => {
  const u = 1 - t;
  const a = u * u * u;
  const b = 3 * u * u * t;
  const c = 3 * u * t * t;
  const d = t * t * t;
  return {
    x: a * p0.x + b * c0.x + c * c1.x + d * p1.x,
    y: a * p0.y + b * c0.y + c * c1.y + d * p1.y,
  };
};

export const cubicD = (p0: Pt, c0: Pt, c1: Pt, p1: Pt) =>
  `M ${p0.x} ${p0.y} C ${c0.x} ${c0.y}, ${c1.x} ${c1.y}, ${p1.x} ${p1.y}`;

/** Sampled arc length — good enough to normalise dash offsets. */
export const cubicLength = (p0: Pt, c0: Pt, c1: Pt, p1: Pt, steps = 48) => {
  let len = 0;
  let prev = p0;
  for (let i = 1; i <= steps; i++) {
    const pt = cubic(p0, c0, c1, p1, i / steps);
    len += Math.hypot(pt.x - prev.x, pt.y - prev.y);
    prev = pt;
  }
  return len;
};

/** A wire: geometry + its own path string and length, computed once. */
export const wire = (p0: Pt, c0: Pt, c1: Pt, p1: Pt) => ({
  p0,
  c0,
  c1,
  p1,
  d: cubicD(p0, c0, c1, p1),
  length: cubicLength(p0, c0, c1, p1),
  at: (t: number) => cubic(p0, c0, c1, p1, t),
});

export type Wire = ReturnType<typeof wire>;

/** Straight wire expressed as a cubic so it shares the same interface. */
export const straight = (p0: Pt, p1: Pt) =>
  wire(
    p0,
    {x: p0.x + (p1.x - p0.x) / 3, y: p0.y + (p1.y - p0.y) / 3},
    {x: p0.x + ((p1.x - p0.x) * 2) / 3, y: p0.y + ((p1.y - p0.y) * 2) / 3},
    p1,
  );
