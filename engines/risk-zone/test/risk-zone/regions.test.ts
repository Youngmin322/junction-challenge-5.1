import { describe, expect, it } from 'vitest';
import { buildConnectivityRegions } from '../../src/index.js';

describe('conditional connectivity regions', () => {
  it('groups diagonally touching occupied cells into one region', () => {
    const regions = buildConnectivityRegions(
      [
        [129, 37],
        [129.011, 37.011],
      ],
      [129, 37],
      1_000,
    );

    expect(regions.features).toHaveLength(1);
    expect(regions.features[0].geometry.type).toBe('MultiPolygon');
    expect(regions.features[0].geometry.coordinates).toHaveLength(2);
    expect(regions.features[0].properties).toMatchObject({
      occupiedCellCount: 2,
      representedParticleCount: 2,
    });
  });

  it('splits disconnected occupied cells and removes duplicate particle positions', () => {
    const regions = buildConnectivityRegions(
      [
        [129, 37],
        [129, 37],
        [129.04, 37.04],
      ],
      [129, 37],
      1_000,
    );

    expect(regions.features).toHaveLength(2);
    expect(regions.features.reduce((count, feature) => count + feature.properties!.occupiedCellCount, 0))
      .toBe(2);
  });

  it('represents no live particles with an empty feature collection', () => {
    expect(buildConnectivityRegions([], [129, 37], 1_000).features).toEqual([]);
  });
});
