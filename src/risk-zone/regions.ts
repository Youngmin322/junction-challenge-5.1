import type { Feature, FeatureCollection, MultiPolygon } from 'geojson';
import { createLocalProjection } from './geo.js';
import type { Position } from './types.js';

interface OccupiedCell {
  x: number;
  y: number;
  particleCount: number;
}

/**
 * Converts particle locations to a set of occupied local-metre cells. Eight
 * connected cells become one GeoJSON feature while individual cell boundaries
 * stay visible for an honest MVP representation of the sampled region.
 */
export function buildConnectivityRegions(
  positions: readonly Position[],
  anchor: Position,
  cellSizeMeters: number,
): FeatureCollection<MultiPolygon> {
  const projection = createLocalProjection(anchor);
  const cells = new Map<string, OccupiedCell>();

  for (const position of positions) {
    const [xMeters, yMeters] = projection.toLocal(position);
    const x = Math.floor(xMeters / cellSizeMeters);
    const y = Math.floor(yMeters / cellSizeMeters);
    const key = cellKey(x, y);
    const existing = cells.get(key);
    if (existing) {
      existing.particleCount += 1;
    } else {
      cells.set(key, { x, y, particleCount: 1 });
    }
  }

  const remaining = new Set(cells.keys());
  const features: Feature<MultiPolygon>[] = [];
  while (remaining.size > 0) {
    const firstKey = remaining.values().next().value as string;
    const connected = collectConnectedCells(firstKey, cells, remaining);
    const coordinates = connected.map((cell) => [cellBoundary(cell, cellSizeMeters, projection)]);
    features.push({
      type: 'Feature',
      properties: {
        occupiedCellCount: connected.length,
        representedParticleCount: connected.reduce((total, cell) => total + cell.particleCount, 0),
      },
      geometry: { type: 'MultiPolygon', coordinates },
    });
  }

  return { type: 'FeatureCollection', features };
}

function collectConnectedCells(
  firstKey: string,
  cells: ReadonlyMap<string, OccupiedCell>,
  remaining: Set<string>,
): OccupiedCell[] {
  const connected: OccupiedCell[] = [];
  const pending = [firstKey];
  remaining.delete(firstKey);

  while (pending.length > 0) {
    const key = pending.pop()!;
    const cell = cells.get(key)!;
    connected.push(cell);
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        if (offsetX === 0 && offsetY === 0) continue;
        const neighborKey = cellKey(cell.x + offsetX, cell.y + offsetY);
        if (remaining.delete(neighborKey)) pending.push(neighborKey);
      }
    }
  }
  return connected;
}

function cellBoundary(
  cell: OccupiedCell,
  cellSizeMeters: number,
  projection: ReturnType<typeof createLocalProjection>,
): number[][] {
  const minimumX = cell.x * cellSizeMeters;
  const minimumY = cell.y * cellSizeMeters;
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
