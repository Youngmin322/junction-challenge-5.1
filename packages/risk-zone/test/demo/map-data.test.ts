import type { FeatureCollection, Polygon } from 'geojson';
import { describe, expect, it } from 'vitest';
import {
  buildCurrentOrientedFanEnvelope,
  filterArrivalBands,
  prepareApproachBands,
  traceUpstreamCurrentCenterline,
} from '../../demo/src/map-data.js';
import type { EarliestArrivalCellProperties } from '../../src/risk-zone/types.js';

const bands: FeatureCollection<Polygon, EarliestArrivalCellProperties> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: {
        cellId: '0:0',
        earliestArrivalMinutes: 120,
        arrivalBand: 'within-2h',
        simulatedParticleVisits: 3,
      },
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    },
    {
      type: 'Feature',
      properties: {
        cellId: '1:0',
        earliestArrivalMinutes: 1_440,
        arrivalBand: 'within-24h',
        simulatedParticleVisits: 2,
      },
      geometry: { type: 'Polygon', coordinates: [[[2, 0], [3, 0], [3, 1], [2, 0]]] },
    },
  ],
};

describe('map arrival-band data', () => {
  it('shows only cells reached by the selected timeline time', () => {
    expect(filterArrivalBands(bands, 120).features).toHaveLength(1);
    expect(filterArrivalBands(bands, 1_440).features).toHaveLength(2);
  });

  it('adds approach priority without changing timeline arrival data', () => {
    const prepared = prepareApproachBands(bands, [2 / 3, 1 / 3]);

    expect(prepared.features[0]?.properties).toMatchObject({
      cellId: '0:0',
      earliestArrivalMinutes: 120,
      arrivalBand: 'within-2h',
      approachPriority: 'immediate-monitoring',
    });
    expect(filterArrivalBands(prepared, 120).features).toHaveLength(1);
  });
});

describe('current-oriented fan envelope', () => {
  it('keeps all four colour bands while rotating upstream from the current', () => {
    const westwardCurrent = buildCurrentOrientedFanEnvelope({
      intakePosition: [129.397, 37.0931],
      uMetersPerSecond: -0.2,
      vMetersPerSecond: 0,
    });
    const northwardCurrent = buildCurrentOrientedFanEnvelope({
      intakePosition: [129.397, 37.0931],
      uMetersPerSecond: 0,
      vMetersPerSecond: 0.2,
    });

    expect(westwardCurrent.features.map((feature) => feature.properties.approachPriority)).toEqual([
      'immediate-monitoring',
      'near-intake',
      'approach-corridor',
      'far-offshore',
    ]);
    expect(northwardCurrent.features).toHaveLength(4);
    expect(westwardCurrent.features[0]?.properties.axisBearingDegrees).toBeCloseTo(90);
    expect(northwardCurrent.features[0]?.properties.axisBearingDegrees).toBeCloseTo(180);

    const westwardFarCoordinates = westwardCurrent.features[3]!.geometry.coordinates[0]!;
    const northwardFarCoordinates = northwardCurrent.features[3]!.geometry.coordinates[0]!;
    expect(westwardFarCoordinates.every(([longitude]) => longitude > 129.397)).toBe(true);
    expect(northwardFarCoordinates.every(([, latitude]) => latitude < 37.0931)).toBe(true);
  });

  it('makes fast-current envelopes longer and directionally narrower', () => {
    const slow = buildCurrentOrientedFanEnvelope({
      intakePosition: [129.397, 37.0931],
      uMetersPerSecond: -0.08,
      vMetersPerSecond: 0,
    });
    const fast = buildCurrentOrientedFanEnvelope({
      intakePosition: [129.397, 37.0931],
      uMetersPerSecond: -0.5,
      vMetersPerSecond: 0,
    });

    expect(fast.features[0]?.properties.envelopeLengthMeters)
      .toBeGreaterThan(slow.features[0]!.properties.envelopeLengthMeters);
    expect(fast.features[0]?.properties.halfAngleDegrees)
      .toBeLessThan(slow.features[0]!.properties.halfAngleDegrees);
    expect(slow.features).toHaveLength(4);
    expect(fast.features).toHaveLength(4);
  });

  it('bends the centerline when the current direction changes across space', () => {
    const centerline = traceUpstreamCurrentCenterline({
      intakePosition: [129.397, 37.0931],
      uMetersPerSecond: -0.2,
      vMetersPerSecond: 0,
      sampleVelocityAt: ([longitude]) => ({
        uMetersPerSecond: -0.2,
        vMetersPerSecond: Math.min(0.16, Math.max(0, (longitude - 129.397) * 0.4)),
      }),
    });

    const first = centerline.positions[0]!;
    const second = centerline.positions[1]!;
    const penultimate = centerline.positions.at(-2)!;
    const last = centerline.positions.at(-1)!;

    expect(centerline.positions.length).toBeGreaterThan(20);
    expect(Math.abs(second[1] - first[1])).toBeLessThan(0.0001);
    expect(last[1] - penultimate[1]).toBeLessThan(-0.0001);
    expect(last[1]).toBeLessThan(37.085);
  });

  it('does not fabricate a corridor when spatial current coverage is incomplete', () => {
    const input = {
      intakePosition: [129.397, 37.0931] as const,
      uMetersPerSecond: -0.2,
      vMetersPerSecond: 0,
      sampleVelocityAt: ([longitude]: readonly [number, number]) => longitude < 129.42
        ? { uMetersPerSecond: -0.2, vMetersPerSecond: 0 }
        : null,
    };

    const centerline = traceUpstreamCurrentCenterline(input);
    const envelope = buildCurrentOrientedFanEnvelope(input);

    expect(centerline.coverageComplete).toBe(false);
    expect(centerline.positions.length).toBeGreaterThan(1);
    expect(envelope.features).toHaveLength(0);
  });
});
