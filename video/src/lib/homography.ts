/**
 * Map a rectangle onto an arbitrary convex quadrilateral, as a CSS transform.
 *
 * This is what lets the app be composited into a photographed screen. The
 * mock-ups are shot from three-quarter, side and top-down angles, so their
 * glass is a perspective-projected rectangle — not a rotation, not a skew, and
 * not anything `rotateY` can produce, because a real camera's projection is
 * projective and CSS's affine primitives are not. A homography is exactly the
 * transform that takes the app's flat layout to the pixels the camera would
 * have recorded had the app been on that screen.
 *
 * CSS can express it: `matrix3d` is a full 4x4 projective transform, and the
 * 2D homography embeds into it directly. `transform-origin: 0 0` is required,
 * since the maths is written about the element's own origin.
 */

export type Point = [number, number];

export type Quad = {tl: Point; tr: Point; br: Point; bl: Point};

/** Solve A x = b by Gaussian elimination with partial pivoting. */
const solve = (A: number[][], b: number[]): number[] => {
  const n = b.length;
  const m = A.map((row, i) => [...row, b[i]]);

  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(m[r][col]) > Math.abs(m[pivot][col])) pivot = r;
    }
    if (Math.abs(m[pivot][col]) < 1e-12) {
      throw new Error('degenerate quad: the four corners are not in general position');
    }
    [m[col], m[pivot]] = [m[pivot], m[col]];

    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = m[r][col] / m[col][col];
      for (let c = col; c <= n; c++) m[r][c] -= f * m[col][c];
    }
  }
  // Elimination ran against every other row, so `m` is diagonal by now.
  return m.map((row, i) => row[n] / row[i]);
};

/**
 * The homography taking (0,0)-(w,h) to `quad`, as the eight free coefficients
 * of
 *
 *     x' = (a x + b y + c) / (g x + h y + 1)
 *     y' = (d x + e y + f) / (g x + h y + 1)
 *
 * Each corner correspondence contributes two rows; four corners determine all
 * eight unknowns exactly, so this is a solve and not a fit.
 */
export const homographyFor = (w: number, h: number, quad: Quad): number[] => {
  const src: Point[] = [[0, 0], [w, 0], [w, h], [0, h]];
  const dst: Point[] = [quad.tl, quad.tr, quad.br, quad.bl];

  const A: number[][] = [];
  const b: number[] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [X, Y] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -x * X, -y * X]);
    b.push(X);
    A.push([0, 0, 0, x, y, 1, -x * Y, -y * Y]);
    b.push(Y);
  }
  return solve(A, b);
};

/**
 * The same transform as a `matrix3d(...)` string.
 *
 * `matrix3d` takes its sixteen values in COLUMN-major order, and the third
 * column and row belong to z, which a flat plane does not use. So the 3x3
 * homography lands in the corners of the 4x4: the projective row (g, h) goes
 * into the w-components of the x and y columns, which is what makes the
 * division by (g x + h y + 1) happen in the rasteriser.
 */
export const matrix3dFor = (w: number, h: number, quad: Quad): string => {
  const [a, b, c, d, e, f, g, hh] = homographyFor(w, h, quad);
  const m = [
    a, d, 0, g,
    b, e, 0, hh,
    0, 0, 1, 0,
    c, f, 0, 1,
  ];
  return `matrix3d(${m.map((v) => Number(v.toFixed(8))).join(',')})`;
};

/** Where a point in the rectangle lands on the quad. Used for placing lights. */
export const project = (w: number, h: number, quad: Quad, p: Point): Point => {
  const [a, b, c, d, e, f, g, hh] = homographyFor(w, h, quad);
  const den = g * p[0] + hh * p[1] + 1;
  return [(a * p[0] + b * p[1] + c) / den, (d * p[0] + e * p[1] + f) / den];
};
