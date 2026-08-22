import {
  simulateConditionalConnectivity,
  type FlowFieldProvider,
  type NavigabilityProvider,
} from '../src/index.js';

const observedAt = '2026-08-23T00:00:00.000Z';

const eastwardCurrent: FlowFieldProvider = {
  velocityAt: ({ validAt }) => ({
    uMetersPerSecond: 1,
    vMetersPerSecond: 0,
    sourceTime: new Date(observedAt),
    validAt,
  }),
};

const openWater: NavigabilityProvider = {
  canTraverse: () => ({ passable: true }),
};

const result = simulateConditionalConnectivity({
  seed: {
    observedAt,
    species: 'jellyfish',
    geometry: { kind: 'point', position: [129, 37] },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 3,
    positionUncertaintyMeters: 200,
  },
  offshoreFlow: eastwardCurrent,
  navigability: openWater,
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
