import type { FeatureCollection, Polygon } from 'geojson';
import { describe, expect, it } from 'vitest';
import { filterArrivalBands, prepareApproachBands } from '../../demo/src/map-data.js';
import type { EarliestArrivalCellProperties } from '../../src/risk-zone/types.js';

const bands: FeatureCollection<Polygon, EarliestArrivalCellProperties> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {
        cellId: '0:0',
        earliestArrivalMinutes: 120,
        arrivalBand: 'within-2h',
        simulatedParticleVisits: 3,
      },
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    },
    {
      type: 'Feature',
      properties: {
        cellId: '1:0',
        earliestArrivalMinutes: 1_440,
        arrivalBand: 'within-24h',
        simulatedParticleVisits: 2,
      },
      geometry: { type: 'Polygon', coordinates: [[[2, 0], [3, 0], [3, 1], [2, 0]]] },
    },
  ],
};

describe('map arrival-band data', () => {
  it('shows only cells reached by the selected timeline time', () => {
    expect(filterArrivalBands(bands, 120).features).toHaveLength(1);
    expect(filterArrivalBands(bands, 1_440).features).toHaveLength(2);
  });

  it('adds approach priority without changing timeline arrival data', () => {
    const prepared = prepareApproachBands(bands, [2 / 3, 1 / 3]);

    expect(prepared.features[0]?.properties).toMatchObject({
      cellId: '0:0',
      earliestArrivalMinutes: 120,
      arrivalBand: 'within-2h',
      approachPriority: 'immediate-monitoring',
    });
    expect(filterArrivalBands(prepared, 120).features).toHaveLength(1);
  });
});
