import { describe, expect, it } from 'vitest';
import { calculateRiskZone, normalizePublicCurrentRecord } from '../../src/index.js';

const observedAt = '2026-08-23T00:00:00.000Z';
const currentRows = [
  {
    issuedAt: observedAt,
    validAt: observedAt,
    longitude: 129,
    latitude: 37,
    depthMeters: 1,
    speedMetersPerSecond: 1,
    directionDegrees: 90,
    directionConvention: 'toward' as const,
  },
  {
    issuedAt: observedAt,
    validAt: '2026-08-23T02:00:00.000Z',
    longitude: 129,
    latitude: 37,
    depthMeters: 1,
    speedMetersPerSecond: 1,
    directionDegrees: 90,
    directionConvention: 'toward' as const,
  },
];

describe('simple public-data facade', () => {
  it('converts a directional public-current record into east/north velocity', () => {
    const normalized = normalizePublicCurrentRecord(currentRows[0]);

    expect(normalized.uMetersPerSecond).toBeCloseTo(1, 10);
    expect(normalized.vMetersPerSecond).toBeCloseTo(0, 10);
  });

  it('runs a conditional calculation from observation, current, coast, and gate rows', () => {
    const result = calculateRiskZone({
      observation: {
        observedAt,
        species: 'jellyfish',
        geometry: { kind: 'point', position: [129, 37] },
        depthMeters: 1,
        confidence: 0.8,
        ensembleSize: 1,
        positionUncertaintyMeters: 0,
      },
      offshoreCurrents: currentRows,
      coast: {
        landPolygons: [],
        bathymetryPoints: [{ longitude: 129, latitude: 37, depthMeters: 30 }],
        minimumWaterDepthMeters: 3,
        maximumBathymetryLookupMeters: 10_000,
      },
      gate: {
        kind: 'endpoints',
        start: [129.04, 36.99],
        end: [129.04, 37.01],
        minDepthMeters: 0,
        maxDepthMeters: 10,
      },
      config: { horizonsHours: [2] },
    });

    expect(result.horizonSummaries[0]).toMatchObject({
      horizonHours: 2,
      conditionalGateConnectionFraction: 1,
      etaMinutes: { p50: 60 },
    });
  });
});
