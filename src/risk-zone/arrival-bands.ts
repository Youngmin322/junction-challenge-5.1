import type { Feature, FeatureCollection, Polygon } from 'geojson';
import { createLocalProjection } from './geo.js';
import type {
  ArrivalBand,
  EarliestArrivalCellProperties,
  ParticleTrajectory,
  Position,
} from './types.js';

export type { ArrivalBand, EarliestArrivalCellProperties } from './types.js';

export interface BuildEarliestArrivalBandsInput {
  trajectories: readonly ParticleTrajectory[];
  anchor: Position;
  timeStepMinutes: number;
  cellSizeMeters: number;
  maximumArrivalMinutes: number;
}

interface ArrivalCell {
  x: number;
  y: number;
  earliestArrivalMinutes: number;
  particleIds: Set<string>;
}

export function arrivalBandForMinutes(minutes: number): ArrivalBand | null {
  if (minutes < 0 || !Number.isFinite(minutes)) return null;
  if (minutes <= 120) return 'within-2h';
  if (minutes <= 240) return 'within-4h';
  if (minutes <= 1_440) return 'within-24h';
  if (minutes <= 2_880) return 'within-48h';
  return null;
}

export function buildEarliestArrivalBands(
  input: BuildEarliestArrivalBandsInput,
): FeatureCollection<Polygon, EarliestArrivalCellProperties> {
  const projection = createLocalProjection(input.anchor);
  const cells = new Map<string, ArrivalCell>();

  for (const trajectory of input.trajectories) {
    const firstPosition = trajectory.coordinates[0];
    if (!firstPosition) continue;
    recordPosition(cells, firstPosition, 0, trajectory.id, input, projection);

    for (let coordinateIndex = 1; coordinateIndex < trajectory.coordinates.length; coordinateIndex += 1) {
      const from = trajectory.coordinates[coordinateIndex - 1]!;
      const to = trajectory.coordinates[coordinateIndex]!;
      const fromMinutes = (coordinateIndex - 1) * input.timeStepMinutes;
      const toMinutes = coordinateIndex * input.timeStepMinutes;
      if (fromMinutes > input.maximumArrivalMinutes) break;

      const [fromX, fromY] = projection.toLocal(from);
      const [toX, toY] = projection.toLocal(to);
      const distance = Math.hypot(toX - fromX, toY - fromY);
      const stepCount = Math.max(1, Math.ceil(distance / (input.cellSizeMeters / 2)));

      for (let step = 1; step <= stepCount; step += 1) {
        const fraction = step / stepCount;
        const elapsedMinutes = fromMinutes + (toMinutes - fromMinutes) * fraction;
        if (elapsedMinutes > input.maximumArrivalMinutes) continue;
        recordPosition(
          cells,
          projection.toGeographic([
            fromX + (toX - fromX) * fraction,
            fromY + (toY - fromY) * fraction,
          ]),
          elapsedMinutes,
          trajectory.id,
          input,
          projection,
        );
      }
    }
  }

  const features: Array<Feature<Polygon, EarliestArrivalCellProperties>> = [];
  for (const cell of cells.values()) {
    const arrivalBand = arrivalBandForMinutes(cell.earliestArrivalMinutes);
    if (!arrivalBand) continue;
    features.push({
      type: 'Feature',
      properties: {
        cellId: cellKey(cell.x, cell.y),
        earliestArrivalMinutes: cell.earliestArrivalMinutes,
        arrivalBand,
        simulatedParticleVisits: cell.particleIds.size,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [cellBoundary(cell.x, cell.y, input.cellSizeMeters, projection)],
      },
    });
  }

  return { type: 'FeatureCollection', features };
}

function recordPosition(
  cells: Map<string, ArrivalCell>,
  position: Position,
  elapsedMinutes: number,
  particleId: string,
  input: BuildEarliestArrivalBandsInput,
  projection: ReturnType<typeof createLocalProjection>,
): void {
  if (elapsedMinutes > input.maximumArrivalMinutes) return;
  const [xMeters, yMeters] = projection.toLocal(position);
  const x = Math.floor(xMeters / input.cellSizeMeters);
  const y = Math.floor(yMeters / input.cellSizeMeters);
  const key = cellKey(x, y);
  const existing = cells.get(key);
  if (existing) {
    existing.earliestArrivalMinutes = Math.min(existing.earliestArrivalMinutes, elapsedMinutes);
    existing.particleIds.add(particleId);
    return;
  }
  cells.set(key, {
    x,
    y,
    earliestArrivalMinutes: elapsedMinutes,
    particleIds: new Set([particleId]),
  });
}

function cellBoundary(
  x: number,
  y: number,
  cellSizeMeters: number,
  projection: ReturnType<typeof createLocalProjection>,
): number[][] {
  const minimumX = x * cellSizeMeters;
  const minimumY = y * cellSizeMeters;
  return [
    projection.toGeographic([minimumX, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY]),
  ].map(([longitude, latitude]) => [longitude, latitude]);
}

function cellKey(x: number, y: number): string {
  return `${x}:${y}`;
}
