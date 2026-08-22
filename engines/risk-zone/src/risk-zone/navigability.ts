import { createLocalProjection, distanceMeters, pointInPolygon } from './geo.js';
import type { NavigabilityProvider, Position, TraversalResult } from './types.js';

export interface BathymetrySampler {
  depthAt(position: Position, at: Date): number | null;
}

export interface CoastAndBathymetryOptions {
  /** Each polygon is an exterior ring followed by any interior exclusion rings. */
  landPolygons: Position[][][];
  bathymetry: BathymetrySampler;
  minimumWaterDepthMeters: number;
  sampleSpacingMeters: number;
}

/**
 * Rejects an entire movement segment when it enters land, shallow water, or
 * unavailable bathymetry coverage. This avoids passing across narrow land
 * features between particle time steps.
 */
export class CoastAndBathymetryProvider implements NavigabilityProvider {
  constructor(private readonly options: CoastAndBathymetryOptions) {}

  canTraverse(request: {
    from: Position;
    to: Position;
    particleDepthMeters: number;
    at: Date;
  }): TraversalResult {
    const projection = createLocalProjection(request.from);
    const destination = projection.toLocal(request.to);
    const numberOfSegments = Math.max(
      1,
      Math.ceil(distanceMeters(request.from, request.to) / this.options.sampleSpacingMeters),
    );

    for (let index = 0; index <= numberOfSegments; index += 1) {
      const fraction = index / numberOfSegments;
      const position = projection.toGeographic([
        destination[0] * fraction,
        destination[1] * fraction,
      ]);
      if (this.options.landPolygons.some((polygon) => pointInPolygon(position, polygon))) {
        return { passable: false, reason: 'land' };
      }
      const depth = this.options.bathymetry.depthAt(position, request.at);
      if (depth === null) return { passable: false, reason: 'outside-coverage' };
      if (depth < this.options.minimumWaterDepthMeters) {
        return { passable: false, reason: 'shallow-water' };
      }
    }
    return { passable: true };
  }
}
