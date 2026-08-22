import type { FeatureCollection, Polygon } from 'geojson';
import { describe, expect, it } from 'vitest';
import {
  approachPriorityForDistance,
  buildApproachPriorityBands,
} from '../../src/risk-zone/approach-priority.js';
import type { EarliestArrivalCellProperties } from '../../src/risk-zone/types.js';

describe('intake approach priority bands', () => {
  it('uses inclusive 2 km, 5 km, and 12 km monitoring boundaries', () => {
    expect(approachPriorityForDistance(2_000)).toBe('immediate-monitoring');
    expect(approachPriorityForDistance(2_001)).toBe('near-intake');
    expect(approachPriorityForDistance(5_000)).toBe('near-intake');
    expect(approachPriorityForDistance(5_001)).toBe('approach-corridor');
    expect(approachPriorityForDistance(12_000)).toBe('approach-corridor');
    expect(approachPriorityForDistance(12_001)).toBe('far-offshore');
  });

  it('adds intake distance while preserving earliest-arrival properties', () => {
    const arrivalBands: FeatureCollection<Polygon, EarliestArrivalCellProperties> = {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        properties: {
          cellId: '0:0',
          earliestArrivalMinutes: 180,
          arrivalBand: 'within-4h',
          simulatedParticleVisits: 7,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [129.379, 37.089],
            [129.387, 37.089],
            [129.387, 37.097],
            [129.379, 37.097],
            [129.379, 37.089],
          ]],
        },
      }],
    };

    const result = buildApproachPriorityBands({
      arrivalBands,
      intakePosition: [129.383, 37.093],
    });

    expect(result.features[0]?.properties).toMatchObject({
      cellId: '0:0',
      earliestArrivalMinutes: 180,
      arrivalBand: 'within-4h',
      simulatedParticleVisits: 7,
      approachPriority: 'immediate-monitoring',
    });
    expect(result.features[0]?.properties.distanceToIntakeMeters).toBeLessThan(1);
  });

  it('rejects non-positive or non-increasing thresholds', () => {
    expect(() => approachPriorityForDistance(1_000, {
      immediate: 0,
      near: 5_000,
      corridor: 12_000,
    })).toThrow(/positive and strictly increasing/i);

    expect(() => buildApproachPriorityBands({
      arrivalBands: { type: 'FeatureCollection', features: [] },
      intakePosition: [129.383, 37.093],
      thresholdsMeters: { immediate: 2_000, near: 2_000, corridor: 12_000 },
    })).toThrow(/positive and strictly increasing/i);
  });
});
