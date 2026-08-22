import type { Feature, FeatureCollection, GeoJsonProperties, Geometry, Polygon } from 'geojson';
import {
  buildApproachPriorityBands,
  type ApproachPriority,
  type ApproachPriorityCellProperties,
} from '../../src/risk-zone/approach-priority.js';
import { createLocalProjection } from '../../src/risk-zone/geo.js';
import type { EarliestArrivalCellProperties, Position } from '../../src/risk-zone/types.js';

export interface BuildCurrentOrientedFanEnvelopeInput {
  intakePosition: Position;
  uMetersPerSecond: number;
  vMetersPerSecond: number;
}

export interface CurrentFanBandProperties {
  approachPriority: ApproachPriority;
  displayMode: 'current-oriented-fan';
  minimumDistanceRatio: number;
  maximumDistanceRatio: number;
  currentSpeedMetersPerSecond: number;
  envelopeLengthMeters: number;
  halfAngleDegrees: number;
  axisBearingDegrees: number;
}

const FAN_BANDS: ReadonlyArray<{
  approachPriority: ApproachPriority;
  minimumDistanceRatio: number;
  maximumDistanceRatio: number;
}> = [
  { approachPriority: 'immediate-monitoring', minimumDistanceRatio: 0, maximumDistanceRatio: 0.12 },
  { approachPriority: 'near-intake', minimumDistanceRatio: 0.12, maximumDistanceRatio: 0.3 },
  { approachPriority: 'approach-corridor', minimumDistanceRatio: 0.3, maximumDistanceRatio: 0.65 },
  { approachPriority: 'far-offshore', minimumDistanceRatio: 0.65, maximumDistanceRatio: 1 },
];

export function buildCurrentOrientedFanEnvelope(
  input: BuildCurrentOrientedFanEnvelopeInput,
): FeatureCollection<Polygon, CurrentFanBandProperties> {
  const speed = Math.hypot(input.uMetersPerSecond, input.vMetersPerSecond);
  if (!Number.isFinite(speed)) throw new RangeError('Current velocity must be finite.');

  const normalizedSpeed = clamp((speed - 0.05) / 0.45, 0, 1);
  const envelopeLengthMeters = interpolate(9_000, 22_000, normalizedSpeed);
  const halfAngleDegrees = interpolate(38, 10, normalizedSpeed);
  const upstreamX = speed > 0 ? -input.uMetersPerSecond / speed : 1;
  const upstreamY = speed > 0 ? -input.vMetersPerSecond / speed : 0;
  const axisRadians = Math.atan2(upstreamY, upstreamX);
  const axisBearingDegrees = normalizeDegrees(
    (Math.atan2(upstreamX, upstreamY) * 180) / Math.PI,
  );
  const projection = createLocalProjection(input.intakePosition);

  const features: Array<Feature<Polygon, CurrentFanBandProperties>> = FAN_BANDS.map((band) => ({
    type: 'Feature',
    properties: {
      ...band,
      displayMode: 'current-oriented-fan',
      currentSpeedMetersPerSecond: speed,
      envelopeLengthMeters,
      halfAngleDegrees,
      axisBearingDegrees,
    },
    geometry: {
      type: 'Polygon',
      coordinates: [fanBandBoundary({
        innerRadiusMeters: envelopeLengthMeters * band.minimumDistanceRatio,
        outerRadiusMeters: envelopeLengthMeters * band.maximumDistanceRatio,
        axisRadians,
        halfAngleRadians: (halfAngleDegrees * Math.PI) / 180,
        projection,
      })],
    },
  }));

  return { type: 'FeatureCollection', features };
}

export function prepareApproachBands(
  arrivalBands: FeatureCollection<Polygon, EarliestArrivalCellProperties>,
  intakePosition: Position,
): FeatureCollection<Polygon, ApproachPriorityCellProperties> {
  return buildApproachPriorityBands({ arrivalBands, intakePosition });
}

export function filterArrivalBands<
  GeometryType extends Geometry,
  Properties extends GeoJsonProperties,
>(
  bands: FeatureCollection<GeometryType, Properties>,
  maximumArrivalMinutes: number,
): FeatureCollection<GeometryType, Properties> {
  return {
    type: 'FeatureCollection',
    features: bands.features.filter((feature) => {
      const value = feature.properties?.earliestArrivalMinutes;
      return typeof value === 'number' && value <= maximumArrivalMinutes;
    }),
  };
}

function fanBandBoundary(args: {
  innerRadiusMeters: number;
  outerRadiusMeters: number;
  axisRadians: number;
  halfAngleRadians: number;
  projection: ReturnType<typeof createLocalProjection>;
}): number[][] {
  const arcSteps = 16;
  const outer = Array.from({ length: arcSteps + 1 }, (_, index) => {
    const fraction = index / arcSteps;
    const angle = args.axisRadians - args.halfAngleRadians + 2 * args.halfAngleRadians * fraction;
    return args.projection.toGeographic([
      Math.cos(angle) * args.outerRadiusMeters,
      Math.sin(angle) * args.outerRadiusMeters,
    ]);
  });
  const inner = args.innerRadiusMeters === 0
    ? [args.projection.toGeographic([0, 0])]
    : Array.from({ length: arcSteps + 1 }, (_, index) => {
      const fraction = index / arcSteps;
      const angle = args.axisRadians + args.halfAngleRadians - 2 * args.halfAngleRadians * fraction;
      return args.projection.toGeographic([
        Math.cos(angle) * args.innerRadiusMeters,
        Math.sin(angle) * args.innerRadiusMeters,
      ]);
    });
  const first = outer[0]!;
  return [...outer, ...inner, first].map(([longitude, latitude]) => [longitude, latitude]);
}

function interpolate(start: number, end: number, fraction: number): number {
  return start + (end - start) * fraction;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function normalizeDegrees(value: number): number {
  return ((value % 360) + 360) % 360;
}
