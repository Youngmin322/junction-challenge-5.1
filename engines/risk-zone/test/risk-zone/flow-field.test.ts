import { describe, expect, it } from 'vitest';
import {
  effectiveVelocityAt,
  GriddedFlowFieldProvider,
} from '../../src/index.js';
import type { NearshoreFlowPolicy } from '../../src/index.js';

const at = (value: string) => new Date(value);
const requestAt = (position: readonly [number, number], value: string) => ({
  position,
  depthMeters: 1,
  validAt: at(value),
});
const sample = (
  validAt: string,
  position: readonly [number, number],
  uMetersPerSecond: number,
  vMetersPerSecond: number,
) => ({
  validAt: at(validAt),
  sourceTime: at('2026-08-23T00:00:00.000Z'),
  position,
  depthMeters: 1,
  uMetersPerSecond,
  vMetersPerSecond,
});

describe('current-field providers', () => {
  it('interpolates u and v between valid-time grid records', () => {
    const field = new GriddedFlowFieldProvider([
      sample('2026-08-23T00:00:00.000Z', [129, 37], 0, 0),
      sample('2026-08-23T01:00:00.000Z', [129, 37], 2, 4),
    ]);

    expect(field.velocityAt(requestAt([129, 37], '2026-08-23T00:30:00.000Z'))).toMatchObject({
      uMetersPerSecond: 1,
      vMetersPerSecond: 2,
    });
  });

  it('returns no velocity outside available valid-time coverage', () => {
    const field = new GriddedFlowFieldProvider([
      sample('2026-08-23T00:00:00.000Z', [129, 37], 1, 0),
    ]);

    expect(field.velocityAt(requestAt([129, 37], '2026-08-23T00:15:00.000Z'))).toBeNull();
  });

  it('replaces offshore flow inside a configured nearshore zone', () => {
    const offshore = { velocityAt: () => sample('2026-08-23T00:00:00.000Z', [0, 0], 1, 0) };
    const nearshore = { velocityAt: () => sample('2026-08-23T00:00:00.000Z', [0, 0], -2, 0) };
    const policy = {
      mode: 'replace' as const,
      provider: nearshore,
      zone: {
        kind: 'polygon' as const,
        rings: [[[ -1, -1 ], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
      },
    } satisfies NearshoreFlowPolicy;

    expect(effectiveVelocityAt(requestAt([0, 0], '2026-08-23T00:00:00.000Z'), offshore, policy))
      .toMatchObject({ uMetersPerSecond: -2, vMetersPerSecond: 0 });
    expect(effectiveVelocityAt(requestAt([2, 0], '2026-08-23T00:00:00.000Z'), offshore, policy))
      .toMatchObject({ uMetersPerSecond: 1, vMetersPerSecond: 0 });
  });

  it('adds a nearshore vector only when the policy labels it residual', () => {
    const offshore = { velocityAt: () => sample('2026-08-23T00:00:00.000Z', [0, 0], 1, 2) };
    const residual = { velocityAt: () => sample('2026-08-23T00:00:00.000Z', [0, 0], -0.5, 3) };
    const policy = {
      mode: 'residualAdd' as const,
      isResidual: true as const,
      provider: residual,
      zone: {
        kind: 'polygon' as const,
        rings: [[[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]],
      },
    } satisfies NearshoreFlowPolicy;

    expect(effectiveVelocityAt(requestAt([0, 0], '2026-08-23T00:00:00.000Z'), offshore, policy))
      .toMatchObject({ uMetersPerSecond: 0.5, vMetersPerSecond: 5 });
  });
});
