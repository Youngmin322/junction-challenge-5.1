import type { FeatureCollection, Polygon } from 'geojson';
import { describe, expect, it } from 'vitest';
import { filterArrivalBands } from '../../demo/src/map-data.js';

const bands: FeatureCollection<Polygon> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { earliestArrivalMinutes: 120, arrivalBand: 'within-2h' },
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    },
    {
      type: 'Feature',
      properties: { earliestArrivalMinutes: 1_440, arrivalBand: 'within-24h' },
      geometry: { type: 'Polygon', coordinates: [[[2, 0], [3, 0], [3, 1], [2, 0]]] },
    },
  ],
};

describe('map arrival-band data', () => {
  it('shows only cells reached by the selected timeline time', () => {
    expect(filterArrivalBands(bands, 120).features).toHaveLength(1);
    expect(filterArrivalBands(bands, 1_440).features).toHaveLength(2);
  });
});
