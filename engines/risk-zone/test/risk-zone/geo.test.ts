import { describe, expect, it } from 'vitest';
import {
  createLocalProjection,
  pointInPolygon,
  segmentsIntersect,
} from '../../src/index.js';

describe('local geographic primitives', () => {
  it('round-trips a local metre coordinate around its anchor', () => {
    const projection = createLocalProjection([129, 37]);
    const position = projection.toGeographic([1_250, -740]);

    expect(projection.toLocal(position)[0]).toBeCloseTo(1_250, 8);
    expect(projection.toLocal(position)[1]).toBeCloseTo(-740, 8);
  });

  it('recognizes a particle segment crossing a monitoring gate', () => {
    expect(segmentsIntersect([0, 0], [10, 0], [5, -5], [5, 5])).toBe(true);
    expect(segmentsIntersect([0, 0], [4, 0], [5, -5], [5, 5])).toBe(false);
  });

  it('keeps points on an observation boundary and rejects a polygon hole', () => {
    const rings = [
      [
        [0, 0],
        [10, 0],
        [10, 10],
        [0, 10],
        [0, 0],
      ],
      [
        [4, 4],
        [6, 4],
        [6, 6],
        [4, 6],
        [4, 4],
      ],
    ] as const;

    expect(pointInPolygon([0, 5], rings)).toBe(true);
    expect(pointInPolygon([2, 2], rings)).toBe(true);
    expect(pointInPolygon([5, 5], rings)).toBe(false);
  });
});
