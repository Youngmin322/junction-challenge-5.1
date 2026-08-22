import { describe, expect, it } from 'vitest';
import { createLocalProjection } from '../../src/risk-zone/geo.js';
import { buildCurrentOrientedFanEnvelope } from '../../demo/src/map-data.js';
import {
  demoScenarios,
  getDemoScenario,
  HANUL_SITE_POSITION,
} from '../../demo/src/scenarios.js';

describe('fictional map scenarios', () => {
  it('provides Hanul first plus the three explanatory 48-hour scenarios', () => {
    expect(demoScenarios.map((scenario) => scenario.id)).toEqual([
      'hanul-approach',
      'eastward-spread',
      'tidal-turn',
      'coastal-interception',
    ]);

    for (const scenario of demoScenarios) {
      expect(scenario.isFictional).toBe(true);
      expect(scenario.input.config?.horizonsHours).toEqual([2, 4, 24, 48]);
      expect(scenario.dataMode).toBe('synthetic');
    }
  });

  it('starts east of Hanul and directs the synthetic current toward the site', () => {
    const scenario = getDemoScenario('hanul-approach');
    const seed = scenario.input.seed.geometry.kind === 'point'
      ? scenario.input.seed.geometry.position
      : scenario.input.seed.geometry.rings[0][0]!;
    const velocity = scenario.input.offshoreFlow.velocityAt({
      position: seed,
      depthMeters: scenario.input.seed.depthMeters,
      validAt: new Date(scenario.input.seed.observedAt),
    });
    const [towardSiteX, towardSiteY] = createLocalProjection(seed).toLocal(HANUL_SITE_POSITION);

    expect(HANUL_SITE_POSITION).toEqual([129.38301, 37.0931]);
    expect(seed[0]).toBeGreaterThan(HANUL_SITE_POSITION[0]);
    expect(scenario.mapContext).toBe('real-site');
    expect(velocity).not.toBeNull();
    expect(
      velocity!.uMetersPerSecond * towardSiteX +
      velocity!.vMetersPerSecond * towardSiteY,
    ).toBeGreaterThan(0);
  });

  it('changes the Hanul cross-current enough to visibly rotate the fan over time', () => {
    const scenario = getDemoScenario('hanul-approach');
    const startedAt = new Date(scenario.input.seed.observedAt);
    const sixHoursLater = new Date(startedAt.valueOf() + 6 * 60 * 60 * 1_000);
    const request = {
      position: scenario.intakePosition,
      depthMeters: scenario.input.seed.depthMeters,
    };
    const initial = scenario.input.offshoreFlow.velocityAt({ ...request, validAt: startedAt });
    const later = scenario.input.offshoreFlow.velocityAt({ ...request, validAt: sixHoursLater });

    expect(initial).not.toBeNull();
    expect(later).not.toBeNull();
    expect(Math.abs(later!.vMetersPerSecond - initial!.vMetersPerSecond)).toBeGreaterThan(0.05);
  });

  it('changes the Hanul speed enough to visibly resize the fan over time', () => {
    const scenario = getDemoScenario('hanul-approach');
    const startedAt = new Date(scenario.input.seed.observedAt);
    const sixHoursLater = new Date(startedAt.valueOf() + 6 * 60 * 60 * 1_000);
    const request = {
      position: scenario.intakePosition,
      depthMeters: scenario.input.seed.depthMeters,
    };
    const initial = scenario.input.offshoreFlow.velocityAt({ ...request, validAt: startedAt })!;
    const later = scenario.input.offshoreFlow.velocityAt({ ...request, validAt: sixHoursLater })!;
    const initialSpeed = Math.hypot(initial.uMetersPerSecond, initial.vMetersPerSecond);
    const laterSpeed = Math.hypot(later.uMetersPerSecond, later.vMetersPerSecond);

    expect(Math.abs(laterSpeed - initialSpeed)).toBeGreaterThan(0.05);
  });

  it('changes the Hanul current direction across space to form a curved corridor', () => {
    const scenario = getDemoScenario('hanul-approach');
    const validAt = new Date(
      new Date(scenario.input.seed.observedAt).valueOf() + 24 * 60 * 60 * 1_000,
    );
    const request = { depthMeters: scenario.input.seed.depthMeters, validAt };
    const nearIntake = scenario.input.offshoreFlow.velocityAt({
      ...request,
      position: scenario.intakePosition,
    })!;
    const offshore = scenario.input.offshoreFlow.velocityAt({
      ...request,
      position: [129.5, 37.0931],
    })!;

    expect(Math.abs(offshore.vMetersPerSecond - nearIntake.vMetersPerSecond))
      .toBeGreaterThan(0.1);
  });

  it('keeps four simple Hanul ribbon polygons across the full timeline', () => {
    const scenario = getDemoScenario('hanul-approach');
    const startedAt = new Date(scenario.input.seed.observedAt);

    for (let selectedHours = 0; selectedHours <= 48; selectedHours += 1) {
      const validAt = new Date(startedAt.valueOf() + selectedHours * 60 * 60 * 1_000);
      const request = { depthMeters: scenario.input.seed.depthMeters, validAt };
      const intakeCurrent = scenario.input.offshoreFlow.velocityAt({
        ...request,
        position: scenario.intakePosition,
      })!;
      const envelope = buildCurrentOrientedFanEnvelope({
        intakePosition: scenario.intakePosition,
        uMetersPerSecond: intakeCurrent.uMetersPerSecond,
        vMetersPerSecond: intakeCurrent.vMetersPerSecond,
        sampleVelocityAt: (position) => scenario.input.offshoreFlow.velocityAt({
          ...request,
          position,
        }),
      });

      expect(envelope.features, `${selectedHours}h band count`).toHaveLength(4);
      for (const feature of envelope.features) {
        expect(isSimpleClosedRing(feature.geometry.coordinates[0]!), `${selectedHours}h polygon`)
          .toBe(true);
      }
    }
  });

  it('turns the tidal scenario flow after four hours', () => {
    const scenario = getDemoScenario('tidal-turn');
    const position = scenario.input.seed.geometry.kind === 'point'
      ? scenario.input.seed.geometry.position
      : scenario.input.seed.geometry.rings[0][0]!;
    const startedAt = new Date(scenario.input.seed.observedAt);
    const sixHoursLater = new Date(startedAt.valueOf() + 6 * 60 * 60 * 1_000);

    expect(scenario.input.offshoreFlow.velocityAt({
      position,
      depthMeters: scenario.input.seed.depthMeters,
      validAt: startedAt,
    })).toMatchObject({ uMetersPerSecond: 0.2, vMetersPerSecond: 0.08 });
    expect(scenario.input.offshoreFlow.velocityAt({
      position,
      depthMeters: scenario.input.seed.depthMeters,
      validAt: sixHoursLater,
    })).toMatchObject({ uMetersPerSecond: 0.04, vMetersPerSecond: -0.16 });
  });
});

function isSimpleClosedRing(ring: readonly (readonly number[])[]): boolean {
  if (ring.length < 4 || !samePoint(ring[0]!, ring.at(-1)!)) return false;
  const edgeCount = ring.length - 1;
  for (let first = 0; first < edgeCount; first += 1) {
    if (samePoint(ring[first]!, ring[first + 1]!)) return false;
    for (let second = first + 1; second < edgeCount; second += 1) {
      const adjacent = second === first + 1 || (first === 0 && second === edgeCount - 1);
      if (adjacent) continue;
      if (segmentsIntersect(ring[first]!, ring[first + 1]!, ring[second]!, ring[second + 1]!)) {
        return false;
      }
    }
  }
  return true;
}

function segmentsIntersect(
  firstStart: readonly number[],
  firstEnd: readonly number[],
  secondStart: readonly number[],
  secondEnd: readonly number[],
): boolean {
  const firstSideA = cross(firstStart, firstEnd, secondStart);
  const firstSideB = cross(firstStart, firstEnd, secondEnd);
  const secondSideA = cross(secondStart, secondEnd, firstStart);
  const secondSideB = cross(secondStart, secondEnd, firstEnd);
  const epsilon = 1e-12;
  if (firstSideA * firstSideB < -epsilon && secondSideA * secondSideB < -epsilon) {
    return true;
  }
  return (Math.abs(firstSideA) <= epsilon && pointOnSegment(firstStart, firstEnd, secondStart))
    || (Math.abs(firstSideB) <= epsilon && pointOnSegment(firstStart, firstEnd, secondEnd))
    || (Math.abs(secondSideA) <= epsilon && pointOnSegment(secondStart, secondEnd, firstStart))
    || (Math.abs(secondSideB) <= epsilon && pointOnSegment(secondStart, secondEnd, firstEnd));
}

function cross(origin: readonly number[], end: readonly number[], point: readonly number[]): number {
  return (end[0]! - origin[0]!) * (point[1]! - origin[1]!)
    - (end[1]! - origin[1]!) * (point[0]! - origin[0]!);
}

function pointOnSegment(start: readonly number[], end: readonly number[], point: readonly number[]): boolean {
  const epsilon = 1e-12;
  return point[0]! >= Math.min(start[0]!, end[0]!) - epsilon
    && point[0]! <= Math.max(start[0]!, end[0]!) + epsilon
    && point[1]! >= Math.min(start[1]!, end[1]!) - epsilon
    && point[1]! <= Math.max(start[1]!, end[1]!) + epsilon;
}

function samePoint(first: readonly number[], second: readonly number[]): boolean {
  return Math.abs(first[0]! - second[0]!) < 1e-12
    && Math.abs(first[1]! - second[1]!) < 1e-12;
}
