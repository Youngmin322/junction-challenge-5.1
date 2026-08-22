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
  sampleVelocityAt?: (position: Position) => CurrentVector | null;
}

export interface CurrentVector {
  uMetersPerSecond: number;
  vMetersPerSecond: number;
}

export interface TracedCurrentCenterline {
  positions: Position[];
  coverageComplete: boolean;
  currentSpeedMetersPerSecond: number;
  envelopeLengthMeters: number;
  halfAngleDegrees: number;
  axisBearingDegrees: number;
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
  const centerline = traceUpstreamCurrentCenterline(input);
  if (!centerline.coverageComplete || centerline.positions.length < 2) {
    return { type: 'FeatureCollection', features: [] };
  }
  const projection = createLocalProjection(input.intakePosition);

  const features: Array<Feature<Polygon, CurrentFanBandProperties>> = FAN_BANDS.map((band) => ({
    type: 'Feature',
    properties: {
      ...band,
      displayMode: 'current-oriented-fan',
      currentSpeedMetersPerSecond: centerline.currentSpeedMetersPerSecond,
      envelopeLengthMeters: centerline.envelopeLengthMeters,
      halfAngleDegrees: centerline.halfAngleDegrees,
      axisBearingDegrees: centerline.axisBearingDegrees,
    },
    geometry: {
      type: 'Polygon',
      coordinates: [curvedFanBandBoundary({
        centerline: centerline.positions,
        minimumDistanceRatio: band.minimumDistanceRatio,
        maximumDistanceRatio: band.maximumDistanceRatio,
        envelopeLengthMeters: centerline.envelopeLengthMeters,
        halfAngleRadians: (centerline.halfAngleDegrees * Math.PI) / 180,
        projection,
      })],
    },
  }));

  return { type: 'FeatureCollection', features };
}

export function traceUpstreamCurrentCenterline(
  input: BuildCurrentOrientedFanEnvelopeInput,
): TracedCurrentCenterline {
  const speed = Math.hypot(input.uMetersPerSecond, input.vMetersPerSecond);
  if (!Number.isFinite(speed)) throw new RangeError('Current velocity must be finite.');

  const normalizedSpeed = clamp((speed - 0.05) / 0.45, 0, 1);
  const envelopeLengthMeters = interpolate(9_000, 22_000, normalizedSpeed);
  const halfAngleDegrees = interpolate(38, 10, normalizedSpeed);
  const initialUpstream = normalizedUpstream(
    input.uMetersPerSecond,
    input.vMetersPerSecond,
    [1, 0],
  );
  const axisBearingDegrees = normalizeDegrees(
    (Math.atan2(initialUpstream[0], initialUpstream[1]) * 180) / Math.PI,
  );
  const projection = createLocalProjection(input.intakePosition);
  const stepCount = 40;
  const stepMeters = envelopeLengthMeters / stepCount;
  const localPositions: Array<readonly [number, number]> = [[0, 0]];
  let previousDirection = initialUpstream;
  let coverageComplete = true;

  for (let index = 0; index < stepCount; index += 1) {
    const current = localPositions.at(-1)!;
    const geographic = projection.toGeographic(current);
    const sampled = input.sampleVelocityAt
      ? input.sampleVelocityAt(geographic)
      : input;
    if (!sampled) {
      coverageComplete = false;
      break;
    }
    const sampledUpstream = normalizedUpstream(
      sampled.uMetersPerSecond,
      sampled.vMetersPerSecond,
      previousDirection,
    );
    const direction = normalizeVector([
      previousDirection[0] * 0.45 + sampledUpstream[0] * 0.55,
      previousDirection[1] * 0.45 + sampledUpstream[1] * 0.55,
    ], previousDirection);
    localPositions.push([
      current[0] + direction[0] * stepMeters,
      current[1] + direction[1] * stepMeters,
    ]);
    previousDirection = direction;
  }

  return {
    positions: localPositions.map((position) => projection.toGeographic(position)),
    coverageComplete,
    currentSpeedMetersPerSecond: speed,
    envelopeLengthMeters,
    halfAngleDegrees,
    axisBearingDegrees,
  };
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

function curvedFanBandBoundary(args: {
  centerline: Position[];
  minimumDistanceRatio: number;
  maximumDistanceRatio: number;
  envelopeLengthMeters: number;
  halfAngleRadians: number;
  projection: ReturnType<typeof createLocalProjection>;
}): number[][] {
  const localCenterline = args.centerline.map((position) => args.projection.toLocal(position));
  const lastIndex = localCenterline.length - 1;
  const startIndex = Math.round(args.minimumDistanceRatio * lastIndex);
  const endIndex = Math.round(args.maximumDistanceRatio * lastIndex);
  const safeHalfWidths = buildCurvatureSafeHalfWidths(
    localCenterline,
    args.envelopeLengthMeters,
    args.halfAngleRadians,
  );
  const left: Position[] = [];
  const right: Position[] = [];

  for (let index = startIndex; index <= endIndex; index += 1) {
    const current = localCenterline[index]!;
    const previous = localCenterline[Math.max(0, index - 1)]!;
    const next = localCenterline[Math.min(lastIndex, index + 1)]!;
    const tangent = normalizeVector([next[0] - previous[0], next[1] - previous[1]], [1, 0]);
    const normal = [-tangent[1], tangent[0]] as const;
    const halfWidth = safeHalfWidths[index]!;
    left.push(args.projection.toGeographic([
      current[0] + normal[0] * halfWidth,
      current[1] + normal[1] * halfWidth,
    ]));
    right.push(args.projection.toGeographic([
      current[0] - normal[0] * halfWidth,
      current[1] - normal[1] * halfWidth,
    ]));
  }

  const boundary = [...left, ...right.reverse()];
  if (boundary.length > 1 && samePosition(boundary[0]!, boundary.at(-1)!)) {
    boundary.pop();
  }
  const first = boundary[0]!;
  return [...boundary, first].map(([longitude, latitude]) => [longitude, latitude]);
}

function samePosition(first: Position, second: Position): boolean {
  return Math.abs(first[0] - second[0]) < 1e-12
    && Math.abs(first[1] - second[1]) < 1e-12;
}

function buildCurvatureSafeHalfWidths(
  centerline: ReadonlyArray<readonly [number, number]>,
  envelopeLengthMeters: number,
  halfAngleRadians: number,
): number[] {
  const lastIndex = centerline.length - 1;
  const widths = centerline.map((_, index) => {
    const nominalWidth = (index / lastIndex) * envelopeLengthMeters * Math.tan(halfAngleRadians);
    if (index === 0 || index === lastIndex) return nominalWidth;

    const previous = centerline[index - 1]!;
    const current = centerline[index]!;
    const next = centerline[index + 1]!;
    const incoming = normalizeVector(
      [current[0] - previous[0], current[1] - previous[1]],
      [1, 0],
    );
    const outgoing = normalizeVector(
      [next[0] - current[0], next[1] - current[1]],
      incoming,
    );
    const turnRadians = Math.acos(clamp(
      incoming[0] * outgoing[0] + incoming[1] * outgoing[1],
      -1,
      1,
    ));
    if (turnRadians < 1e-6) return nominalWidth;

    const incomingLength = Math.hypot(current[0] - previous[0], current[1] - previous[1]);
    const outgoingLength = Math.hypot(next[0] - current[0], next[1] - current[1]);
    const localRadius = Math.min(incomingLength, outgoingLength) / turnRadians;
    return Math.min(nominalWidth, localRadius * 0.65);
  });

  limitWidthSlope(widths, centerline, 0, 1, lastIndex + 1);
  limitWidthSlope(widths, centerline, lastIndex, -1, -1);
  return widths;
}

function limitWidthSlope(
  widths: number[],
  centerline: ReadonlyArray<readonly [number, number]>,
  startIndex: number,
  step: 1 | -1,
  endExclusive: number,
): void {
  for (let index = startIndex + step; index !== endExclusive; index += step) {
    const previousIndex = index - step;
    const current = centerline[index]!;
    const previous = centerline[previousIndex]!;
    const segmentLength = Math.hypot(current[0] - previous[0], current[1] - previous[1]);
    widths[index] = Math.min(widths[index]!, widths[previousIndex]! + segmentLength * 0.8);
  }
}

function normalizedUpstream(
  uMetersPerSecond: number,
  vMetersPerSecond: number,
  fallback: readonly [number, number],
): readonly [number, number] {
  return normalizeVector([-uMetersPerSecond, -vMetersPerSecond], fallback);
}

function normalizeVector(
  vector: readonly [number, number],
  fallback: readonly [number, number],
): readonly [number, number] {
  const length = Math.hypot(vector[0], vector[1]);
  if (!Number.isFinite(length) || length < 1e-9) return fallback;
  return [vector[0] / length, vector[1] / length];
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
