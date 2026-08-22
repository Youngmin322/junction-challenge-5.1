import {
  GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  setWorkerUrl,
  type Map,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Feature, FeatureCollection, LineString, Point, Polygon } from 'geojson';
import { createLocalProjection } from '../../src/risk-zone/geo.js';
import { simulateConditionalConnectivity } from '../../src/risk-zone/simulation.js';
import type { Position, SimulationResult } from '../../src/risk-zone/types.js';
import { filterArrivalBands } from './map-data.js';
import { demoScenarios, getDemoScenario, type DemoScenario } from './scenarios.js';
import './style.css';

const mapStyleUrl = 'https://demotiles.maplibre.org/style.json';
const scenarioSelect = document.querySelector<HTMLSelectElement>('#scenario-select')!;
const timeline = document.querySelector<HTMLInputElement>('#timeline')!;
const timelineValue = document.querySelector<HTMLElement>('#timeline-value')!;
const scenarioDescription = document.querySelector<HTMLElement>('#scenario-description')!;
const disclaimer = document.querySelector<HTMLElement>('#disclaimer')!;

for (const scenario of demoScenarios) {
  const option = new Option(scenario.name, scenario.id);
  scenarioSelect.add(option);
}

let selectedScenario = getDemoScenario('eastward-spread');
let result = simulateConditionalConnectivity(selectedScenario.input);
setWorkerUrl(workerUrl);
const map = new MapLibreMap({
  container: 'map',
  style: mapStyleUrl,
  center: toMapPosition(seedPosition(selectedScenario)),
  zoom: 10.5,
});

map.addControl(new NavigationControl(), 'top-right');
map.on('load', () => {
  addSourcesAndLayers(map);
  renderScenario();
});

scenarioSelect.addEventListener('change', () => {
  selectedScenario = getDemoScenario(scenarioSelect.value as DemoScenario['id']);
  result = simulateConditionalConnectivity(selectedScenario.input);
  renderScenario();
});

timeline.addEventListener('input', renderScenario);

function renderScenario(): void {
  const maximumMinutes = Number(timeline.value) * 60;
  timelineValue.textContent = `${timeline.value}시간 이내`;
  scenarioDescription.textContent = selectedScenario.description;
  disclaimer.textContent = result.disclaimer;

  source(map, 'coast').setData(selectedScenario.coast);
  source(map, 'arrival-bands').setData(filterArrivalBands(result.earliestArrivalBands, maximumMinutes));
  source(map, 'current-arrows').setData(buildCurrentArrows(selectedScenario));
  source(map, 'trajectories').setData(buildTrajectories(result));
  source(map, 'seed').setData(buildSeed(selectedScenario));
  source(map, 'gate').setData(buildGate(selectedScenario));
  map.jumpTo({
    center: toMapPosition(seedPosition(selectedScenario)),
    zoom: 10.5,
  });
}

function addSourcesAndLayers(target: Map): void {
  target.addSource('coast', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('arrival-bands', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('current-arrows', { type: 'geojson', data: emptyCollection<LineString>() });
  target.addSource('trajectories', { type: 'geojson', data: emptyCollection<LineString>() });
  target.addSource('seed', { type: 'geojson', data: emptyCollection<Point>() });
  target.addSource('gate', { type: 'geojson', data: emptyCollection<LineString>() });

  target.addLayer({
    id: 'coast-fill', type: 'fill', source: 'coast',
    paint: { 'fill-color': '#475569', 'fill-opacity': 0.48 },
  });
  target.addLayer({
    id: 'coast-outline', type: 'line', source: 'coast',
    paint: { 'line-color': '#1e293b', 'line-width': 1.5 },
  });
  target.addLayer({
    id: 'arrival-bands-fill', type: 'fill', source: 'arrival-bands',
    paint: {
      'fill-color': ['match', ['get', 'arrivalBand'],
        'within-2h', '#991b1b',
        'within-4h', '#dc2626',
        'within-24h', '#f97316',
        '#fecaca'],
      'fill-opacity': 0.68,
    },
  });
  target.addLayer({
    id: 'arrival-bands-outline', type: 'line', source: 'arrival-bands',
    paint: { 'line-color': '#ffffff', 'line-width': 0.35, 'line-opacity': 0.6 },
  });
  target.addLayer({
    id: 'current-arrows-line', type: 'line', source: 'current-arrows',
    paint: { 'line-color': '#075985', 'line-width': 2.5, 'line-opacity': 0.88 },
  });
  target.addLayer({
    id: 'trajectories-line', type: 'line', source: 'trajectories',
    paint: { 'line-color': '#7f1d1d', 'line-width': 1.2, 'line-opacity': 0.48 },
  });
  target.addLayer({
    id: 'gate-line', type: 'line', source: 'gate',
    paint: { 'line-color': '#0f172a', 'line-width': 2, 'line-dasharray': [2, 2] },
  });
  target.addLayer({
    id: 'seed-circle', type: 'circle', source: 'seed',
    paint: {
      'circle-color': '#0f172a',
      'circle-radius': 6,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
    },
  });
}

function buildCurrentArrows(scenario: DemoScenario): FeatureCollection<LineString> {
  const origin = seedPosition(scenario);
  const projection = createLocalProjection(origin);
  const requestedAt = new Date(scenario.input.seed.observedAt);
  const features: Array<Feature<LineString>> = [];
  for (const offset of [[-1_200, 1_000], [0, 1_000], [1_200, 1_000], [-600, -200], [600, -200]]) {
    const position = projection.toGeographic([offset[0], offset[1]]);
    const velocity = scenario.input.offshoreFlow.velocityAt({
      position,
      depthMeters: scenario.input.seed.depthMeters,
      validAt: requestedAt,
    });
    if (!velocity) continue;
    const end = projection.toGeographic([
      offset[0] + velocity.uMetersPerSecond * 3_000,
      offset[1] + velocity.vMetersPerSecond * 3_000,
    ]);
    features.push({
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'LineString',
        coordinates: [toGeoJsonPosition(position), toGeoJsonPosition(end)],
      },
    });
  }
  return { type: 'FeatureCollection', features };
}

function buildTrajectories(simulation: SimulationResult): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: simulation.particleTrajectories
      .filter((trajectory) => trajectory.coordinates.length > 1)
      .map((trajectory) => ({
        type: 'Feature' as const,
        properties: { particleId: trajectory.id, status: trajectory.status },
        geometry: {
          type: 'LineString' as const,
          coordinates: trajectory.coordinates.map(toGeoJsonPosition),
        },
      })),
  };
}

function buildSeed(scenario: DemoScenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: { label: '관측 군집' },
      geometry: { type: 'Point', coordinates: toGeoJsonPosition(seedPosition(scenario)) },
    }],
  };
}

function buildGate(scenario: DemoScenario): FeatureCollection<LineString> {
  const { gate } = scenario.input;
  if (gate.kind !== 'endpoints') return emptyCollection<LineString>();
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: { label: '선택적 감시선' },
      geometry: {
        type: 'LineString',
        coordinates: [toGeoJsonPosition(gate.start), toGeoJsonPosition(gate.end)],
      },
    }],
  };
}

function seedPosition(scenario: DemoScenario): Position {
  return scenario.input.seed.geometry.kind === 'point'
    ? scenario.input.seed.geometry.position
    : scenario.input.seed.geometry.rings[0][0]!;
}

function toMapPosition(position: Position): [number, number] {
  return [position[0], position[1]];
}

function toGeoJsonPosition(position: Position): [number, number] {
  return [position[0], position[1]];
}

function source(target: Map, id: string): GeoJSONSource {
  return target.getSource(id) as GeoJSONSource;
}

function emptyCollection<GeometryType extends import('geojson').Geometry>(): FeatureCollection<GeometryType> {
  return { type: 'FeatureCollection', features: [] };
}
