import { describe, expect, it } from 'vitest';
import { materializeParticles, pointInPolygon } from '../../src/index.js';

const observedAt = '2026-08-23T00:00:00.000Z';

describe('observation ensemble materialization', () => {
  it('preserves an exact point observation when no position uncertainty is supplied', () => {
    const particles = materializeParticles(
      {
        observedAt,
        species: 'jellyfish',
        geometry: { kind: 'point', position: [129, 37] },
        depthMeters: 1,
        confidence: 0.9,
        ensembleSize: 3,
        positionUncertaintyMeters: 0,
      },
      12,
    );

    expect(particles.map((particle) => particle.coordinates)).toEqual([
      [[129, 37]],
      [[129, 37]],
      [[129, 37]],
    ]);
  });

  it('samples a polygon deterministically without placing particles outside it', () => {
    const rings = [
      [
        [129, 37],
        [129.02, 37],
        [129.02, 37.02],
        [129, 37.02],
        [129, 37],
      ],
    ] as const;
    const seed = {
      observedAt,
      species: 'salp',
      geometry: { kind: 'polygon' as const, rings: rings.map((ring) => [...ring]) },
      depthMeters: 1,
      confidence: 0.7,
      ensembleSize: 10,
      positionUncertaintyMeters: 0,
    };

    const first = materializeParticles(seed, 42);
    const second = materializeParticles(seed, 42);

    expect(first).toEqual(second);
    expect(first.every((particle) => pointInPolygon(particle.coordinates[0], rings))).toBe(true);
    expect(first.map((particle) => particle.id)).toEqual([
      'particle-1',
      'particle-2',
      'particle-3',
      'particle-4',
      'particle-5',
      'particle-6',
      'particle-7',
      'particle-8',
      'particle-9',
      'particle-10',
    ]);
  });
});
