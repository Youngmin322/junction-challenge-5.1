import { describe, expect, it } from 'vitest';
import { RiskZoneValidationError, validateSimulationInput } from '../../src/index.js';

const baseInput = () => ({
  seed: {
    observedAt: '2026-08-23T00:00:00.000Z',
    species: 'jellyfish',
    geometry: { kind: 'point' as const, position: [129, 37] as const },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 5,
    positionUncertaintyMeters: 0,
  },
  offshoreFlow: {
    velocityAt: () => ({
      uMetersPerSecond: 1,
      vMetersPerSecond: 0,
      sourceTime: new Date('2026-08-23T00:00:00.000Z'),
      validAt: new Date('2026-08-23T00:00:00.000Z'),
    }),
  },
  navigability: { canTraverse: () => ({ passable: true }) },
  gate: {
    kind: 'endpoints' as const,
    start: [129.1, 36.9] as const,
    end: [129.1, 37.1] as const,
    minDepthMeters: 0,
    maxDepthMeters: 10,
  },
  config: {
    horizonsHours: [2],
    timeStepMinutes: 15,
    snapshotIntervalMinutes: 60,
    regionCellSizeMeters: 1_000,
    randomSeed: 1,
  },
});

describe('simulation input validation', () => {
  it('rejects a horizon that is not divisible by the simulation step', () => {
    const input = baseInput();
    input.config.timeStepMinutes = 17;

    expect(() => validateSimulationInput(input)).toThrow(RiskZoneValidationError);
    expect(() => validateSimulationInput(input)).toThrow(/config.timeStepMinutes/);
  });

  it('rejects a reversed inclusive gate depth range', () => {
    const input = baseInput();
    input.gate.minDepthMeters = 10;
    input.gate.maxDepthMeters = 2;

    expect(() => validateSimulationInput(input)).toThrow(/gate.minDepthMeters/);
  });

  it('rejects a confidence value outside its provenance range', () => {
    const input = baseInput();
    input.seed.confidence = 1.1;

    expect(() => validateSimulationInput(input)).toThrow(/seed.confidence/);
  });

  it('applies the documented default horizons and grid settings', () => {
    const input = baseInput();
    delete (input as { config?: unknown }).config;

    expect(validateSimulationInput(input)).toMatchObject({
      horizonsHours: [2, 4, 24, 48],
      timeStepMinutes: 15,
      snapshotIntervalMinutes: 60,
      regionCellSizeMeters: 1_000,
      randomSeed: 1,
    });
  });
});
