import { describe, expect, it } from 'vitest';
import {
  CONDITIONAL_CONNECTIVITY_DISCLAIMER,
  createLocalProjection,
  nearestRankPercentile,
  simulateConditionalConnectivity,
} from '../../src/index.js';
import type { FlowFieldProvider, MonitoringGate, SimulationInput } from '../../src/index.js';

const observedAt = '2026-08-23T00:00:00.000Z';
const anchor = [129, 37] as const;
const projection = createLocalProjection(anchor);

const gateAtEastwardDistance = (distanceMeters: number): MonitoringGate => ({
  kind: 'endpoints',
  start: projection.toGeographic([distanceMeters, -500]),
  end: projection.toGeographic([distanceMeters, 500]),
  minDepthMeters: 0,
  maxDepthMeters: 5,
});

const constantFlow = (uMetersPerSecond: number, vMetersPerSecond: number): FlowFieldProvider => ({
  velocityAt: ({ validAt }) => ({
    uMetersPerSecond,
    vMetersPerSecond,
    sourceTime: new Date(observedAt),
    validAt,
  }),
});

const baseInput = (overrides: Partial<SimulationInput> = {}): SimulationInput => ({
  seed: {
    observedAt,
    species: 'jellyfish',
    geometry: { kind: 'point', position: anchor },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 1,
    positionUncertaintyMeters: 0,
  },
  offshoreFlow: constantFlow(1, 0),
  navigability: { canTraverse: () => ({ passable: true }) },
  gate: gateAtEastwardDistance(3_600),
  ...overrides,
});

describe('conditional connectivity simulation', () => {
  it('propagates a forward particle, records a gate arrival, and marks the result conditional', () => {
    const result = simulateConditionalConnectivity(baseInput());
    const twoHour = result.horizonSummaries.find((summary) => summary.horizonHours === 2)!;

    expect(result.classification).toBe('conditional-connectivity-not-blockage-probability');
    expect(result.disclaimer).toBe(CONDITIONAL_CONNECTIVITY_DISCLAIMER);
    expect(result.horizonSummaries.map((summary) => summary.horizonHours)).toEqual([2, 4, 24, 48]);
    expect(result.particleTrajectories[0].coordinates.at(-1)![0]).toBeGreaterThan(anchor[0]);
    expect(twoHour.conditionalGateConnectionFraction).toBe(1);
    expect(twoHour.etaMinutes).toEqual({ p10: 60, p50: 60, p90: 60 });
    expect(result.snapshots.at(-1)!.regions.type).toBe('FeatureCollection');
  });

  it('terminates a particle with missing flow coverage instead of assuming still water', () => {
    const result = simulateConditionalConnectivity(baseInput({
      offshoreFlow: { velocityAt: () => null },
      config: { horizonsHours: [2] },
    }));

    expect(result.particleTrajectories[0].status).toBe('outside-flow-coverage');
    expect(result.snapshots.at(-1)!.representedParticleCount).toBe(0);
    expect(result.diagnostics).toContainEqual(expect.objectContaining({ code: 'flow-coverage-miss' }));
  });

  it('exposes mutually exclusive earliest-arrival cells for map rendering', () => {
    const result = simulateConditionalConnectivity(baseInput({
      config: { horizonsHours: [2], regionCellSizeMeters: 1_000 },
    }));

    expect(result).toHaveProperty('earliestArrivalBands');
    expect((result as unknown as {
      earliestArrivalBands: { features: Array<{ properties: { arrivalBand: string } }> };
    }).earliestArrivalBands.features).toContainEqual(expect.objectContaining({
      properties: expect.objectContaining({ arrivalBand: 'within-2h' }),
    }));
  });

  it('terminates a particle that cannot traverse the coastline', () => {
    const result = simulateConditionalConnectivity(baseInput({
      navigability: { canTraverse: () => ({ passable: false, reason: 'land' }) },
      config: { horizonsHours: [2] },
    }));

    expect(result.particleTrajectories[0].status).toBe('blocked-land');
    expect(result.diagnostics).toContainEqual(expect.objectContaining({
      code: 'navigability-rejection',
      particleId: 'particle-1',
    }));
  });

  it('uses nearest-rank ETA percentiles', () => {
    expect(nearestRankPercentile([10, 40, 100], 10)).toBe(10);
    expect(nearestRankPercentile([10, 40, 100], 50)).toBe(40);
    expect(nearestRankPercentile([10, 40, 100], 90)).toBe(100);
    expect(nearestRankPercentile([], 50)).toBeNull();
  });
});
