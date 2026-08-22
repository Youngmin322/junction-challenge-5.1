import { calculateRiskZone } from '../src/index.js';

const observedAt = '2026-08-23T00:00:00.000Z';

const result = calculateRiskZone({
  observation: {
    observedAt,
    species: 'jellyfish',
    geometry: { kind: 'point', position: [129, 37] },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 3,
    positionUncertaintyMeters: 200,
  },
  offshoreCurrents: [
    {
      issuedAt: observedAt,
      validAt: observedAt,
      longitude: 129,
      latitude: 37,
      depthMeters: 1,
      speedMetersPerSecond: 1,
      directionDegrees: 90,
      directionConvention: 'toward',
    },
    {
      issuedAt: observedAt,
      validAt: '2026-08-23T02:00:00.000Z',
      longitude: 129,
      latitude: 37,
      depthMeters: 1,
      speedMetersPerSecond: 1,
      directionDegrees: 90,
      directionConvention: 'toward',
    },
  ],
  coast: {
    landPolygons: [],
    bathymetryPoints: [{ longitude: 129, latitude: 37, depthMeters: 30 }],
    minimumWaterDepthMeters: 3,
    maximumBathymetryLookupMeters: 10_000,
  },
  gate: {
    kind: 'endpoints',
    start: [129.04, 36.995],
    end: [129.04, 37.005],
    minDepthMeters: 0,
    maxDepthMeters: 10,
  },
  config: { horizonsHours: [2] },
});

console.log(JSON.stringify(result, null, 2));
