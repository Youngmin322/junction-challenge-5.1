import { describe, expect, it } from 'vitest';
import { createLocalProjection } from '../../src/risk-zone/geo.js';
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
