import type { Position } from './types.js';

const EARTH_RADIUS_METERS = 6_371_000;
const DEGREES_TO_RADIANS = Math.PI / 180;

export type LocalPosition = readonly [xMeters: number, yMeters: number];

export interface LocalProjection {
  toLocal(position: Position): LocalPosition;
  toGeographic(position: LocalPosition): Position;
}

export function createLocalProjection(anchor: Position): LocalProjection {
  const [anchorLongitude, anchorLatitude] = anchor;
  const anchorLatitudeRadians = anchorLatitude * DEGREES_TO_RADIANS;
  const longitudeScale = EARTH_RADIUS_METERS * Math.cos(anchorLatitudeRadians) * DEGREES_TO_RADIANS;
  const latitudeScale = EARTH_RADIUS_METERS * DEGREES_TO_RADIANS;

  return {
    toLocal([longitude, latitude]) {
      return [(longitude - anchorLongitude) * longitudeScale, (latitude - anchorLatitude) * latitudeScale];
    },
    toGeographic([xMeters, yMeters]) {
      return [anchorLongitude + xMeters / longitudeScale, anchorLatitude + yMeters / latitudeScale];
    },
  };
}

export function distanceMeters(from: Position, to: Position): number {
  const projection = createLocalProjection(from);
  const [x, y] = projection.toLocal(to);
  return Math.hypot(x, y);
}

export function pointInPolygon(point: Position, rings: readonly (readonly Position[])[]): boolean {
  const exterior = rings[0];
  if (!exterior || !pointInRing(point, exterior)) return false;
  return !rings.slice(1).some((hole) => pointInRing(point, hole));
}

export function segmentsIntersect(
  firstStart: readonly [number, number],
  firstEnd: readonly [number, number],
  secondStart: readonly [number, number],
  secondEnd: readonly [number, number],
): boolean {
  const firstOrientationStart = orientation(firstStart, firstEnd, secondStart);
  const firstOrientationEnd = orientation(firstStart, firstEnd, secondEnd);
  const secondOrientationStart = orientation(secondStart, secondEnd, firstStart);
  const secondOrientationEnd = orientation(secondStart, secondEnd, firstEnd);

  if (
    firstOrientationStart !== firstOrientationEnd &&
    secondOrientationStart !== secondOrientationEnd
  ) {
    return true;
  }

  return (
    (firstOrientationStart === 0 && pointOnSegment(secondStart, firstStart, firstEnd)) ||
    (firstOrientationEnd === 0 && pointOnSegment(secondEnd, firstStart, firstEnd)) ||
    (secondOrientationStart === 0 && pointOnSegment(firstStart, secondStart, secondEnd)) ||
    (secondOrientationEnd === 0 && pointOnSegment(firstEnd, secondStart, secondEnd))
  );
}

function pointInRing(point: Position, ring: readonly Position[]): boolean {
  let inside = false;
  for (let index = 0, previousIndex = ring.length - 1; index < ring.length; previousIndex = index++) {
    const current = ring[index];
    const previous = ring[previousIndex];
    if (pointOnSegment(point, previous, current)) return true;

    const crossesLatitude = (current[1] > point[1]) !== (previous[1] > point[1]);
    if (!crossesLatitude) continue;
    const intersectionLongitude =
      ((previous[0] - current[0]) * (point[1] - current[1])) / (previous[1] - current[1]) +
      current[0];
    if (point[0] < intersectionLongitude) inside = !inside;
  }
  return inside;
}

function orientation(
  first: readonly [number, number],
  second: readonly [number, number],
  third: readonly [number, number],
): -1 | 0 | 1 {
  const cross =
    (second[0] - first[0]) * (third[1] - first[1]) -
    (second[1] - first[1]) * (third[0] - first[0]);
  if (Math.abs(cross) < Number.EPSILON) return 0;
  return cross > 0 ? 1 : -1;
}

function pointOnSegment(
  point: readonly [number, number],
  start: readonly [number, number],
  end: readonly [number, number],
): boolean {
  if (orientation(start, end, point) !== 0) return false;
  return (
    point[0] >= Math.min(start[0], end[0]) &&
    point[0] <= Math.max(start[0], end[0]) &&
    point[1] >= Math.min(start[1], end[1]) &&
    point[1] <= Math.max(start[1], end[1])
  );
}
