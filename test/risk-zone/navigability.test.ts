import { describe, expect, it } from 'vitest';
import { CoastAndBathymetryProvider } from '../../src/index.js';

const request = {
  from: [0, 0] as const,
  to: [2, 0] as const,
  particleDepthMeters: 1,
  at: new Date('2026-08-23T00:00:00.000Z'),
};

const landRing = [
  [0.9, -0.1],
  [1.1, -0.1],
  [1.1, 0.1],
  [0.9, 0.1],
  [0.9, -0.1],
] as const;

describe('coastline and bathymetry navigability', () => {
  it('rejects a movement segment that crosses supplied land', () => {
    const provider = new CoastAndBathymetryProvider({
      landPolygons: [[landRing.map(([longitude, latitude]) => [longitude, latitude] as [number, number])]],
      bathymetry: { depthAt: () => 20 },
      minimumWaterDepthMeters: 3,
      sampleSpacingMeters: 20_000,
    });

    expect(provider.canTraverse(request)).toEqual({ passable: false, reason: 'land' });
  });

  it('rejects a segment through water shallower than its configured limit', () => {
    const provider = new CoastAndBathymetryProvider({
      landPolygons: [],
      bathymetry: { depthAt: () => 2 },
      minimumWaterDepthMeters: 3,
      sampleSpacingMeters: 20_000,
    });

    expect(provider.canTraverse(request)).toEqual({ passable: false, reason: 'shallow-water' });
  });

  it('treats unavailable bathymetry as unavailable navigation coverage', () => {
    const provider = new CoastAndBathymetryProvider({
      landPolygons: [],
      bathymetry: { depthAt: () => null },
      minimumWaterDepthMeters: 3,
      sampleSpacingMeters: 20_000,
    });

    expect(provider.canTraverse(request)).toEqual({ passable: false, reason: 'outside-coverage' });
  });
});
