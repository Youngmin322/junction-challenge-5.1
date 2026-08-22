import type { FeatureCollection, Polygon } from 'geojson';
import { distanceMeters } from './geo.js';
import type { EarliestArrivalCellProperties, Position } from './types.js';

export type ApproachPriority =
  | 'immediate-monitoring'
  | 'near-intake'
  | 'approach-corridor'
  | 'far-offshore';

export interface ApproachPriorityThresholds {
  immediate: number;
  near: number;
  corridor: number;
}

export interface ApproachPriorityCellProperties extends EarliestArrivalCellProperties {
  distanceToIntakeMeters: number;
  approachPriority: ApproachPriority;
}

export interface BuildApproachPriorityBandsInput {
  arrivalBands: FeatureCollection<Polygon, EarliestArrivalCellProperties>;
  intakePosition: Position;
  thresholdsMeters?: ApproachPriorityThresholds;
}

export const DEFAULT_APPROACH_PRIORITY_THRESHOLDS: ApproachPriorityThresholds = {
  immediate: 2_000,
  near: 5_000,
  corridor: 12_000,
};

export function approachPriorityForDistance(
  distanceToIntakeMeters: number,
  thresholdsMeters = DEFAULT_APPROACH_PRIORITY_THRESHOLDS,
): ApproachPriority {
  validateThresholds(thresholdsMeters);
  if (!Number.isFinite(distanceToIntakeMeters) || distanceToIntakeMeters < 0) {
    throw new RangeError('Distance to intake must be a finite non-negative number.');
  }
  if (distanceToIntakeMeters <= thresholdsMeters.immediate) return 'immediate-monitoring';
  if (distanceToIntakeMeters <= thresholdsMeters.near) return 'near-intake';
  if (distanceToIntakeMeters <= thresholdsMeters.corridor) return 'approach-corridor';
  return 'far-offshore';
}

export function buildApproachPriorityBands(
  input: BuildApproachPriorityBandsInput,
): FeatureCollection<Polygon, ApproachPriorityCellProperties> {
  const thresholds = input.thresholdsMeters ?? DEFAULT_APPROACH_PRIORITY_THRESHOLDS;
  validateThresholds(thresholds);

  return {
    type: 'FeatureCollection',
    features: input.arrivalBands.features.map((feature) => {
      const distanceToIntakeMeters = distanceMeters(
        polygonCenter(feature.geometry),
        input.intakePosition,
      );
      return {
        ...feature,
        properties: {
          ...feature.properties,
          distanceToIntakeMeters,
          approachPriority: approachPriorityForDistance(distanceToIntakeMeters, thresholds),
        },
      };
    }),
  };
}

function polygonCenter(polygon: Polygon): Position {
  const exterior = polygon.coordinates[0];
  if (!exterior || exterior.length < 3) {
    throw new RangeError('An arrival cell polygon must have an exterior boundary.');
  }
  const first = exterior[0];
  const last = exterior.at(-1);
  const boundary = first && last && first[0] === last[0] && first[1] === last[1]
    ? exterior.slice(0, -1)
    : exterior;
  const total = boundary.reduce(
    (sum, coordinate) => [sum[0] + coordinate[0], sum[1] + coordinate[1]] as const,
    [0, 0] as const,
  );
  return [total[0] / boundary.length, total[1] / boundary.length];
}

function validateThresholds(thresholds: ApproachPriorityThresholds): void {
  if (
    !Number.isFinite(thresholds.immediate) ||
    !Number.isFinite(thresholds.near) ||
    !Number.isFinite(thresholds.corridor) ||
    thresholds.immediate <= 0 ||
    thresholds.immediate >= thresholds.near ||
    thresholds.near >= thresholds.corridor
  ) {
    throw new RangeError('Approach-priority thresholds must be positive and strictly increasing.');
  }
}
