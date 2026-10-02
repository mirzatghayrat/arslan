import { describe, expect, it } from 'vitest';
import { GLYPH, GLYPH_OF, ORBIT_RADIUS, frameAt, mix, stemPath } from '../island/mascotEngine';

const dist = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1]);

describe('island mascot constellation', () => {
  it('maps every state to the approved shape', () => {
    expect(GLYPH_OF).toEqual({
      idle: 'y', working: 'y', searching: 'orbit', approval: 'bang', finished: 'smile', stopped: 'flat', sleeping: 'small',
    });
  });

  it('every shape is complete: four dots, a two-segment stem, a width', () => {
    for (const g of Object.values(GLYPH)) {
      expect(g.S).toHaveLength(14);
      for (const d of [g.C, g.L, g.R, g.B]) expect(d).toHaveLength(3);
    }
  });

  it('tweens from one shape to the next and lands exactly on it', () => {
    expect(frameAt('idle', GLYPH.y, GLYPH.smile, 0, 0).g).toEqual(GLYPH.y);
    expect(frameAt('stopped', GLYPH.y, GLYPH.flat, 1, 0).g).toEqual(GLYPH.flat);
    const mid = mix(GLYPH.y, GLYPH.bang, 0.5);
    expect(mid.B[1]).toBeCloseTo((GLYPH.y.B[1] + GLYPH.bang.B[1]) / 2);
  });

  it('searching: the three outer dots circle the centre on the track', () => {
    for (const sec of [0, 0.4, 1.3, 7.9]) {
      const { g, ring } = frameAt('searching', GLYPH.y, GLYPH.orbit, 1, sec);
      expect(ring).toBe(ORBIT_RADIUS);
      for (const d of [g.L, g.R, g.B]) expect(dist(d, g.C)).toBeCloseTo(ORBIT_RADIUS, 6);
    }
    const a = frameAt('searching', GLYPH.y, GLYPH.orbit, 1, 0.2).g.L;
    const b = frameAt('searching', GLYPH.y, GLYPH.orbit, 1, 0.6).g.L;
    expect(dist(a, b)).toBeGreaterThan(1);               // they move
  });

  it('working: signals run along the lines from the top dot', () => {
    const { g, sparks } = frameAt('working', GLYPH.y, GLYPH.y, 1, 0.3);
    expect(sparks).toHaveLength(3);
    sparks.forEach((sp, i) => {
      const end = [g.L, g.R, g.B][i];
      // on the segment C→end: distances add up
      expect(dist(g.C, sp) + dist(sp, end)).toBeCloseTo(dist(g.C, end), 6);
    });
  });

  it('the head never moves: only the constellation does', () => {
    // The engine has no head transform at all — breathing and blinking are CSS.
    const f = frameAt('finished', GLYPH.y, GLYPH.smile, 1, 2);
    expect(Object.keys(f.g).sort()).toEqual(['B', 'C', 'L', 'R', 'S', 'w']);
  });

  it('draws the stem as two cubic segments', () => {
    expect(stemPath(GLYPH.ask.S)).toMatch(/^M566\.0 704\.0C.* C?.*C.*$/);
  });
});
