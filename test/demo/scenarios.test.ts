import { describe, expect, it } from 'vitest';
import { demoScenarios, getDemoScenario } from '../../demo/src/scenarios.js';

describe('fictional map scenarios', () => {
  it('provides three named fictional scenarios with a 48-hour simulation', () => {
    expect(demoScenarios.map((scenario) => scenario.id)).toEqual([
      'eastward-spread',
      'tidal-turn',
      'coastal-interception',
    ]);

    for (const scenario of demoScenarios) {
      expect(scenario.isFictional).toBe(true);
      expect(scenario.input.config?.horizonsHours).toEqual([2, 4, 24, 48]);
      expect(scenario.coast.features.length).toBeGreaterThan(0);
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
