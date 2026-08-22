import { createLocalProjection, pointInPolygon } from './geo.js';
import type { MutableParticle, ObservationSeed, Position } from './types.js';

export function materializeParticles(
  seed: ObservationSeed,
  randomSeed: number,
): MutableParticle[] {
  const random = mulberry32(randomSeed);
  const positions =
    seed.geometry.kind === 'point'
      ? samplePoint(seed.geometry.position, seed.positionUncertaintyMeters, seed.ensembleSize, random)
      : samplePolygon(seed.geometry.rings, seed.ensembleSize, random);

  return positions.map((position, index) => ({
    id: `particle-${index + 1}`,
    depthMeters: seed.depthMeters,
    status: 'active',
    firstGateArrivalAt: null,
    coordinates: [position],
  }));
}

function samplePoint(
  center: Position,
  uncertaintyMeters: number,
  count: number,
  random: () => number,
): Position[] {
  if (uncertaintyMeters === 0) {
    return Array.from({ length: count }, () => [center[0], center[1]] as Position);
  }

  const projection = createLocalProjection(center);
  return Array.from({ length: count }, () => {
    const radius = Math.sqrt(random()) * uncertaintyMeters;
    const angle = random() * Math.PI * 2;
    return projection.toGeographic([Math.cos(angle) * radius, Math.sin(angle) * radius]);
  });
}

function samplePolygon(
  rings: Position[][],
  count: number,
  random: () => number,
): Position[] {
  const exterior = rings[0];
  const longitudes = exterior.map(([longitude]) => longitude);
  const latitudes = exterior.map(([, latitude]) => latitude);
  const minimumLongitude = Math.min(...longitudes);
  const maximumLongitude = Math.max(...longitudes);
  const minimumLatitude = Math.min(...latitudes);
  const maximumLatitude = Math.max(...latitudes);
  const positions: Position[] = [];
  const maximumAttempts = count * 100;

  for (let attempt = 0; attempt < maximumAttempts && positions.length < count; attempt += 1) {
    const candidate: Position = [
      minimumLongitude + (maximumLongitude - minimumLongitude) * random(),
      minimumLatitude + (maximumLatitude - minimumLatitude) * random(),
    ];
    if (pointInPolygon(candidate, rings)) positions.push(candidate);
  }

  if (positions.length !== count) {
    throw new Error('seed.geometry: could not sample the requested ensemble within the polygon');
  }
  return positions;
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}
