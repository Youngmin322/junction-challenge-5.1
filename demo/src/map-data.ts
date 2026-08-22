import type { FeatureCollection, GeoJsonProperties, Geometry, Polygon } from 'geojson';
import {
  buildApproachPriorityBands,
  type ApproachPriorityCellProperties,
} from '../../src/risk-zone/approach-priority.js';
import type { EarliestArrivalCellProperties, Position } from '../../src/risk-zone/types.js';

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
