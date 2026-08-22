import type { FeatureCollection, GeoJsonProperties, Geometry } from 'geojson';

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
