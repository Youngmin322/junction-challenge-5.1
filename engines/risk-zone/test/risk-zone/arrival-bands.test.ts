import { describe, expect, it } from 'vitest';
import {
  arrivalBandForMinutes,
  buildEarliestArrivalBands,
} from '../../src/risk-zone/arrival-bands.js';

describe('earliest arrival map bands', () => {
  it('keeps the earliest visit when a particle returns to an occupied cell', () => {
    const bands = buildEarliestArrivalBands({
      trajectories: [
        {
          id: 'particle-1',
          status: 'active',
          firstGateArrivalAt: null,
          coordinates: [[129, 37], [129.01, 37], [129, 37]],
        },
      ],
      anchor: [129, 37],
      timeStepMinutes: 60,
      cellSizeMeters: 2_000,
      maximumArrivalMinutes: 2_880,
    });

    const returnedCell = bands.features.find(
      (feature) => feature.properties?.cellId === '0:0',
    );

    expect(returnedCell?.properties).toMatchObject({
      earliestArrivalMinutes: 0,
      simulatedParticleVisits: 1,
      arrivalBand: 'within-2h',
    });
  });

  it('fills intermediate cells along a movement segment', () => {
    const bands = buildEarliestArrivalBands({
      trajectories: [
        {
          id: 'particle-1',
          status: 'active',
          firstGateArrivalAt: null,
          coordinates: [[129, 37], [129.027, 37]],
        },
      ],
      anchor: [129, 37],
      timeStepMinutes: 60,
      cellSizeMeters: 1_000,
      maximumArrivalMinutes: 2_880,
    });

    expect(bands.features).toHaveLength(3);
  });

  it('labels inclusive time-band boundaries and omits arrivals after 48 hours', () => {
    expect(arrivalBandForMinutes(120)).toBe('within-2h');
    expect(arrivalBandForMinutes(121)).toBe('within-4h');
    expect(arrivalBandForMinutes(240)).toBe('within-4h');
    expect(arrivalBandForMinutes(241)).toBe('within-24h');
    expect(arrivalBandForMinutes(1_440)).toBe('within-24h');
    expect(arrivalBandForMinutes(1_441)).toBe('within-48h');
    expect(arrivalBandForMinutes(2_880)).toBe('within-48h');
    expect(arrivalBandForMinutes(2_881)).toBeNull();
  });
});
