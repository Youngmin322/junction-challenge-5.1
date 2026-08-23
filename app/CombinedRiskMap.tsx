'use client';

import { useEffect, useMemo, useRef } from 'react';
import {
  LngLatBounds,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
  type Map as MapInstance,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Feature, FeatureCollection, LineString, Point, Polygon } from 'geojson';
import { buildCurrentOrientedFanEnvelope } from '../packages/risk-zone/demo/src/map-data.js';
import { getDemoScenario } from '../packages/risk-zone/demo/src/scenarios.js';
import type { Position } from '../packages/risk-zone/src/risk-zone/types.js';

const scenario = getDemoScenario('hanul-approach');
const mapStyleUrl = 'https://demotiles.maplibre.org/style.json';
const observedAt = new Date(scenario.input.seed.observedAt);
const intakePosition = scenario.intakePosition;
const seedPosition = scenario.input.seed.geometry.kind === 'point'
  ? scenario.input.seed.geometry.position
  : scenario.input.seed.geometry.rings[0][0]!;

const emptyCollection = <GeometryType extends Point | LineString | Polygon>(): FeatureCollection<GeometryType> => ({
  type: 'FeatureCollection',
  features: [],
});

function source(map: MapInstance, id: string): GeoJSONSource {
  return map.getSource(id) as GeoJSONSource;
}

function toPoint(position: Position, properties: Record<string, string>): Feature<Point> {
  return { type: 'Feature', properties, geometry: { type: 'Point', coordinates: position } };
}

function buildDensityLayer(): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [toPoint(seedPosition, { label: '해파리 밀집 관측' })],
  };
}

function buildGateLayer(): FeatureCollection<LineString> {
  const gate = scenario.input.gate;
  if (gate.kind !== 'endpoints') return emptyCollection<LineString>();
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: { label: '가상 감시선' },
      geometry: { type: 'LineString', coordinates: [gate.start, gate.end] },
    }],
  };
}

function buildIntakeLayer(): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [
      toPoint(scenario.sitePosition, { kind: 'site', label: '한울원전' }),
      toPoint(intakePosition, { kind: 'intake', label: '취수구 감시지점' }),
    ],
  };
}

function buildWatchCells(): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [
      toPoint([129.405, 37.12], { label: '온양' }),
      toPoint([129.415, 37.102], { label: '덕천' }),
      toPoint([129.407, 37.084], { label: '나곡 · 6/25' }),
    ],
  };
}

function projectToOverlay([longitude, latitude]: Position): string {
  const x = ((longitude - 129.25) / 0.5) * 100;
  const y = (1 - (latitude - 36.98) / 0.24) * 100;
  return `${x},${y}`;
}

function bandColor(priority: string): string {
  if (priority === 'immediate-monitoring') return '#7f1d1d';
  if (priority === 'near-intake') return '#e11d48';
  if (priority === 'approach-corridor') return '#fb7185';
  return '#fed7aa';
}

function buildRiskBands(hours: number): FeatureCollection<Polygon> {
  const validAt = new Date(observedAt.valueOf() + hours * 3_600_000);
  const current = scenario.input.offshoreFlow.velocityAt({
    position: intakePosition,
    depthMeters: scenario.input.seed.depthMeters,
    validAt,
  });
  if (!current) return emptyCollection<Polygon>();
  return buildCurrentOrientedFanEnvelope({
    intakePosition,
    uMetersPerSecond: current.uMetersPerSecond,
    vMetersPerSecond: current.vMetersPerSecond,
    sampleVelocityAt: (position) => {
      const sample = scenario.input.offshoreFlow.velocityAt({
        position,
        depthMeters: scenario.input.seed.depthMeters,
        validAt,
      });
      return sample ? {
        uMetersPerSecond: sample.uMetersPerSecond,
        vMetersPerSecond: sample.vMetersPerSecond,
      } : null;
    },
  });
}

function addLayers(map: MapInstance): void {
  map.addSource('risk-bands', { type: 'geojson', data: emptyCollection<Polygon>() });
  map.addSource('density', { type: 'geojson', data: buildDensityLayer() });
  map.addSource('gate', { type: 'geojson', data: buildGateLayer() });
  map.addSource('intake', { type: 'geojson', data: buildIntakeLayer() });
  map.addSource('watch-cells', { type: 'geojson', data: buildWatchCells() });

  map.addLayer({
    id: 'risk-bands-fill', type: 'fill', source: 'risk-bands',
    paint: {
      'fill-color': ['match', ['get', 'approachPriority'],
        'immediate-monitoring', '#7f1d1d',
        'near-intake', '#e11d48',
        'approach-corridor', '#fb7185',
        '#fed7aa'],
      'fill-opacity': 0.72,
    },
  });
  map.addLayer({
    id: 'risk-bands-outline', type: 'line', source: 'risk-bands',
    paint: { 'line-color': '#fff7ed', 'line-width': 1, 'line-opacity': 0.85 },
  });
  map.addLayer({
    id: 'density-halo', type: 'circle', source: 'density',
    paint: {
      'circle-color': '#a78bfa',
      'circle-radius': 30,
      'circle-opacity': 0.2,
      'circle-stroke-color': '#c4b5fd',
      'circle-stroke-width': 2,
      'circle-stroke-opacity': 0.95,
    },
  });
  map.addLayer({
    id: 'density-point', type: 'circle', source: 'density',
    paint: { 'circle-color': '#7c3aed', 'circle-radius': 7, 'circle-stroke-color': '#f5f3ff', 'circle-stroke-width': 2 },
  });
  map.addLayer({
    id: 'density-label', type: 'symbol', source: 'density',
    layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, 2.2] },
    paint: { 'text-color': '#f5f3ff', 'text-halo-color': '#172033', 'text-halo-width': 2 },
  });
  map.addLayer({
    id: 'gate-line', type: 'line', source: 'gate',
    paint: { 'line-color': '#fbbf24', 'line-width': 2.5, 'line-dasharray': [1.5, 1.5] },
  });
  map.addLayer({
    id: 'watch-cells', type: 'circle', source: 'watch-cells',
    paint: { 'circle-color': '#2dd4bf', 'circle-radius': 6, 'circle-stroke-color': '#ecfeff', 'circle-stroke-width': 2 },
  });
  map.addLayer({
    id: 'watch-cell-labels', type: 'symbol', source: 'watch-cells',
    layout: { 'text-field': ['get', 'label'], 'text-size': 11, 'text-offset': [0, 1.4] },
    paint: { 'text-color': '#ccfbf1', 'text-halo-color': '#172033', 'text-halo-width': 2 },
  });
  map.addLayer({
    id: 'site-point', type: 'circle', source: 'intake', filter: ['==', ['get', 'kind'], 'site'],
    paint: { 'circle-color': '#111827', 'circle-radius': 7, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 },
  });
  map.addLayer({
    id: 'intake-point', type: 'circle', source: 'intake', filter: ['==', ['get', 'kind'], 'intake'],
    paint: { 'circle-color': '#dc2626', 'circle-radius': 8, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 },
  });
  map.addLayer({
    id: 'intake-labels', type: 'symbol', source: 'intake',
    layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-offset': [0, -1.5] },
    paint: { 'text-color': '#f8fafc', 'text-halo-color': '#172033', 'text-halo-width': 2 },
  });
}

function fitToScenario(map: MapInstance, bands: FeatureCollection<Polygon>): void {
  const bounds = new LngLatBounds(seedPosition, seedPosition);
  bounds.extend(scenario.sitePosition);
  bounds.extend(intakePosition);
  for (const feature of bands.features) {
    for (const ring of feature.geometry.coordinates) {
      for (const position of ring) bounds.extend(position);
    }
  }
  map.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 11.5 });
}

export function CombinedRiskMap({ selectedHorizon }: { selectedHorizon: 3 | 6 | 12 }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapInstance | null>(null);
  const riskBands = useMemo(() => buildRiskBands(selectedHorizon), [selectedHorizon]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;
    const map = new MapLibreMap({
      container: containerRef.current,
      style: mapStyleUrl,
      center: [129.47, 37.1],
      zoom: 9.5,
    });
    setWorkerUrl(workerUrl);
    mapRef.current = map;
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => {
      addLayers(map);
      source(map, 'risk-bands').setData(riskBands);
      fitToScenario(map, riskBands);
    });
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [riskBands]);

  return (
    <div className="combined-risk-map-wrap" aria-label="해파리 밀집 관측과 Risk Zone 통합 지도">
      <div className="combined-risk-map" ref={containerRef} />
      <svg className="combined-risk-map-overlay" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="통합 Risk Zone 데이터 레이어">
        {riskBands.features.map((feature, index) => (
          <polygon
            fill={bandColor(feature.properties?.approachPriority ?? '')}
            fillOpacity=".7"
            key={`risk-band-${index}`}
            points={feature.geometry.coordinates[0].map(projectToOverlay).join(' ')}
            stroke="#fff7ed"
            strokeOpacity=".85"
            strokeWidth=".18"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <circle cx={projectToOverlay(seedPosition).split(',')[0]} cy={projectToOverlay(seedPosition).split(',')[1]} fill="#7c3aed" fillOpacity=".25" r="3.4" stroke="#ddd6fe" strokeWidth=".22" vectorEffect="non-scaling-stroke" />
        <circle cx={projectToOverlay(seedPosition).split(',')[0]} cy={projectToOverlay(seedPosition).split(',')[1]} fill="#7c3aed" r=".9" stroke="#f5f3ff" strokeWidth=".2" vectorEffect="non-scaling-stroke" />
        {buildGateLayer().features.map((feature) => (
          <polyline fill="none" key="gate-overlay" points={feature.geometry.coordinates.map(projectToOverlay).join(' ')} stroke="#fbbf24" strokeDasharray="1.2 1.2" strokeWidth=".28" vectorEffect="non-scaling-stroke" />
        ))}
        {buildWatchCells().features.map((feature, index) => (
          <circle cx={projectToOverlay(feature.geometry.coordinates as Position).split(',')[0]} cy={projectToOverlay(feature.geometry.coordinates as Position).split(',')[1]} fill="#2dd4bf" key={`watch-cell-${index}`} r=".8" stroke="#ecfeff" strokeWidth=".2" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
    </div>
  );
}