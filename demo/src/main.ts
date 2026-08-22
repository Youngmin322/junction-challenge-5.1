import {
  GeoJSONSource,
  LngLatBounds,
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
import { filterArrivalBands, prepareApproachBands } from './map-data.js';
import { demoScenarios, getDemoScenario, type DemoScenario } from './scenarios.js';
import './style.css';

const mapStyleUrl = 'https://demotiles.maplibre.org/style.json';
const scenarioSelect = element<HTMLSelectElement>('#scenario-select');
const timeline = element<HTMLInputElement>('#timeline');
const timelineValue = element<HTMLElement>('#timeline-value');
const scenarioDescription = element<HTMLElement>('#scenario-description');
const disclaimer = element<HTMLElement>('#disclaimer');
const pathStatus = element<HTMLElement>('#path-status');
const connectionValue = element<HTMLElement>('#connection-value');
const etaValue = element<HTMLElement>('#eta-value');
const mapContext = element<HTMLElement>('#map-context');
const mapLoading = element<HTMLElement>('#map-loading');

for (const scenario of demoScenarios) {
  scenarioSelect.add(new Option(scenario.name, scenario.id));
}

let selectedScenario = getDemoScenario('hanul-approach');
let result = simulateConditionalConnectivity(selectedScenario.input);
setWorkerUrl(workerUrl);
const map = new MapLibreMap({
  container: 'map',
  style: mapStyleUrl,
  center: midpoint(seedPosition(selectedScenario), selectedScenario.intakePosition),
  zoom: 10.6,
});

map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
map.on('load', () => {
  addSourcesAndLayers(map);
  renderScenario(true);
  mapLoading.hidden = true;
});

scenarioSelect.addEventListener('change', () => {
  selectedScenario = getDemoScenario(scenarioSelect.value as DemoScenario['id']);
  result = simulateConditionalConnectivity(selectedScenario.input);
  renderScenario(true);
});

timeline.addEventListener('input', () => renderScenario(false));

function renderScenario(fitViewport: boolean): void {
  const selectedHours = Number(timeline.value);
  const maximumMinutes = selectedHours * 60;
  const approachBands = prepareApproachBands(
    result.earliestArrivalBands,
    selectedScenario.intakePosition,
  );

  timelineValue.textContent = `${selectedHours}시간`;
  scenarioDescription.textContent = selectedScenario.description;
  mapContext.textContent = selectedScenario.mapContext === 'real-site'
    ? '울진 동해안 · 한울원전 위치 맥락'
    : '설명용 가상 해안 · 가상 시설';
  disclaimer.textContent = selectedScenario.mapContext === 'real-site'
    ? `한울원전 위치만 실제 지도 맥락입니다. ${result.disclaimer}`
    : result.disclaimer;

  source(map, 'coast').setData(selectedScenario.coast);
  source(map, 'approach-bands').setData(filterArrivalBands(approachBands, maximumMinutes));
  source(map, 'current-arrows').setData(buildCurrentArrows(selectedScenario, selectedHours));
  source(map, 'trajectories').setData(buildTrajectories(
    result,
    maximumMinutes,
    selectedScenario.input.config?.timeStepMinutes ?? 15,
  ));
  source(map, 'seed').setData(buildSeed(selectedScenario));
  source(map, 'gate').setData(buildGate(selectedScenario));
  source(map, 'intake').setData(buildIntakeMarkers(selectedScenario));
  updateStatus(maximumMinutes);

  if (fitViewport) fitScenario(map, selectedScenario);
}

function updateStatus(maximumMinutes: number): void {
  const simulationStart = new Date(selectedScenario.input.seed.observedAt).valueOf();
  const arrivalMinutes = result.particleTrajectories.flatMap((trajectory) => {
    if (!trajectory.firstGateArrivalAt) return [];
    return [(new Date(trajectory.firstGateArrivalAt).valueOf() - simulationStart) / 60_000];
  });
  const reachedCount = arrivalMinutes.filter((minutes) => minutes <= maximumMinutes).length;
  const total = result.particleTrajectories.length;
  const finalSummary = result.horizonSummaries.at(-1);

  pathStatus.textContent = reachedCount > 0
    ? '감시선 연결 경로 확인됨'
    : '선택 시간에는 아직 감시선 연결 전';
  pathStatus.dataset.connected = String(reachedCount > 0);
  connectionValue.textContent = `${reachedCount} / ${total}`;
  etaValue.textContent = finalSummary?.etaMinutes.p50 === null || finalSummary?.etaMinutes.p50 === undefined
    ? '도달 없음'
    : `${formatMinutes(finalSummary.etaMinutes.p50)} (p50)`;
}

function addSourcesAndLayers(target: Map): void {
  target.addSource('coast', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('approach-bands', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('current-arrows', { type: 'geojson', data: emptyCollection<LineString>() });
  target.addSource('trajectories', { type: 'geojson', data: emptyCollection<LineString>() });
  target.addSource('seed', { type: 'geojson', data: emptyCollection<Point>() });
  target.addSource('gate', { type: 'geojson', data: emptyCollection<LineString>() });
  target.addSource('intake', { type: 'geojson', data: emptyCollection<Point>() });

  target.addLayer({
    id: 'coast-fill', type: 'fill', source: 'coast',
    paint: { 'fill-color': '#475569', 'fill-opacity': 0.5 },
  });
  target.addLayer({
    id: 'coast-outline', type: 'line', source: 'coast',
    paint: { 'line-color': '#0f172a', 'line-width': 1.5 },
  });
  target.addLayer({
    id: 'approach-bands-fill', type: 'fill', source: 'approach-bands',
    paint: {
      'fill-color': ['match', ['get', 'approachPriority'],
        'immediate-monitoring', '#7f1d1d',
        'near-intake', '#e11d48',
        'approach-corridor', '#fb7185',
        '#fed7aa'],
      'fill-opacity': 0.76,
    },
  });
  target.addLayer({
    id: 'approach-bands-outline', type: 'line', source: 'approach-bands',
    paint: { 'line-color': '#fff7ed', 'line-width': 0.45, 'line-opacity': 0.46 },
  });
  target.addLayer({
    id: 'trajectories-line', type: 'line', source: 'trajectories',
    paint: { 'line-color': '#881337', 'line-width': 1.05, 'line-opacity': 0.34 },
  });
  target.addLayer({
    id: 'current-arrows-line', type: 'line', source: 'current-arrows',
    paint: { 'line-color': '#0284c7', 'line-width': 3, 'line-opacity': 0.9 },
  });
  target.addLayer({
    id: 'current-arrowheads', type: 'symbol', source: 'current-arrows',
    layout: {
      'symbol-placement': 'line',
      'symbol-spacing': 70,
      'text-field': '›',
      'text-size': 20,
      'text-keep-upright': false,
    },
    paint: { 'text-color': '#0369a1', 'text-halo-color': '#e0f2fe', 'text-halo-width': 1 },
  });
  target.addLayer({
    id: 'gate-line', type: 'line', source: 'gate',
    paint: { 'line-color': '#0f172a', 'line-width': 3, 'line-dasharray': [1.5, 1.5] },
  });
  target.addLayer({
    id: 'site-circle', type: 'circle', source: 'intake',
    filter: ['==', ['get', 'kind'], 'site'],
    paint: {
      'circle-color': '#111827',
      'circle-radius': 8,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
    },
  });
  target.addLayer({
    id: 'intake-circle', type: 'circle', source: 'intake',
    filter: ['==', ['get', 'kind'], 'intake'],
    paint: {
      'circle-color': '#7f1d1d',
      'circle-radius': 7,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 3,
    },
  });
  target.addLayer({
    id: 'site-label', type: 'symbol', source: 'intake',
    filter: ['==', ['get', 'kind'], 'site'],
    layout: {
      'text-field': ['get', 'label'],
      'text-size': 13,
      'text-offset': [-0.7, 0.4],
      'text-anchor': 'right',
    },
    paint: {
      'text-color': '#111827',
      'text-halo-color': '#ffffff',
      'text-halo-width': 1.5,
    },
  });
  target.addLayer({
    id: 'intake-label', type: 'symbol', source: 'intake',
    filter: ['==', ['get', 'kind'], 'intake'],
    layout: {
      'text-field': ['get', 'label'],
      'text-size': 13,
      'text-offset': [0.7, 0.4],
      'text-anchor': 'left',
    },
    paint: {
      'text-color': '#111827',
      'text-halo-color': '#ffffff',
      'text-halo-width': 1.5,
    },
  });
  target.addLayer({
    id: 'seed-circle', type: 'circle', source: 'seed',
    paint: {
      'circle-color': '#0369a1',
      'circle-radius': 7,
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 3,
    },
  });
}

function buildCurrentArrows(
  scenario: DemoScenario,
  selectedHours: number,
): FeatureCollection<LineString> {
  const seed = seedPosition(scenario);
  const seedProjection = createLocalProjection(seed);
  const [intakeX, intakeY] = seedProjection.toLocal(scenario.intakePosition);
  const requestedAt = new Date(
    new Date(scenario.input.seed.observedAt).valueOf() + selectedHours * 3_600_000,
  );
  const features: Array<Feature<LineString>> = [];

  for (const fraction of [0.08, 0.3, 0.52, 0.74]) {
    for (const perpendicularOffset of [-650, 650]) {
      const distance = Math.hypot(intakeX, intakeY) || 1;
      const position = seedProjection.toGeographic([
        intakeX * fraction - (intakeY / distance) * perpendicularOffset,
        intakeY * fraction + (intakeX / distance) * perpendicularOffset,
      ]);
      const velocity = scenario.input.offshoreFlow.velocityAt({
        position,
        depthMeters: scenario.input.seed.depthMeters,
        validAt: requestedAt,
      });
      if (!velocity) continue;
      const end = createLocalProjection(position).toGeographic([
        velocity.uMetersPerSecond * 4_800,
        velocity.vMetersPerSecond * 4_800,
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
  }
  return { type: 'FeatureCollection', features };
}

function buildTrajectories(
  simulation: SimulationResult,
  maximumMinutes: number,
  timeStepMinutes: number,
): FeatureCollection<LineString> {
  const maximumCoordinateCount = Math.floor(maximumMinutes / timeStepMinutes) + 1;
  return {
    type: 'FeatureCollection',
    features: simulation.particleTrajectories
      .map((trajectory) => ({
        trajectory,
        coordinates: trajectory.coordinates.slice(0, maximumCoordinateCount),
      }))
      .filter(({ coordinates }) => coordinates.length > 1)
      .map(({ trajectory, coordinates }) => ({
        type: 'Feature' as const,
        properties: { particleId: trajectory.id, status: trajectory.status },
        geometry: {
          type: 'LineString' as const,
          coordinates: coordinates.map(toGeoJsonPosition),
        },
      })),
  };
}

function buildSeed(scenario: DemoScenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: { label: '더미 관측 군집' },
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
      properties: { label: '가상 취수구 감시선' },
      geometry: {
        type: 'LineString',
        coordinates: [toGeoJsonPosition(gate.start), toGeoJsonPosition(gate.end)],
      },
    }],
  };
}

function buildIntakeMarkers(scenario: DemoScenario): FeatureCollection<Point> {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { kind: 'site', label: scenario.mapContext === 'real-site' ? '한울원전' : '가상 원전' },
        geometry: { type: 'Point', coordinates: toGeoJsonPosition(scenario.sitePosition) },
      },
      {
        type: 'Feature',
        properties: { kind: 'intake', label: '취수구 감시지점' },
        geometry: { type: 'Point', coordinates: toGeoJsonPosition(scenario.intakePosition) },
      },
    ],
  };
}

function fitScenario(target: Map, scenario: DemoScenario): void {
  const seed = seedPosition(scenario);
  const bounds = new LngLatBounds(toMapPosition(seed), toMapPosition(seed));
  bounds.extend(toMapPosition(scenario.sitePosition));
  bounds.extend(toMapPosition(scenario.intakePosition));
  const gate = scenario.input.gate;
  if (gate.kind === 'endpoints') {
    bounds.extend(toMapPosition(gate.start));
    bounds.extend(toMapPosition(gate.end));
  }
  target.fitBounds(bounds, { padding: 70, duration: 0, maxZoom: 11.8 });
}

function seedPosition(scenario: DemoScenario): Position {
  return scenario.input.seed.geometry.kind === 'point'
    ? scenario.input.seed.geometry.position
    : scenario.input.seed.geometry.rings[0][0]!;
}

function midpoint(first: Position, second: Position): [number, number] {
  return [(first[0] + second[0]) / 2, (first[1] + second[1]) / 2];
}

function formatMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return remainder === 0 ? `${hours}시간` : `${hours}시간 ${remainder}분`;
}

function element<ElementType extends Element>(selector: string): ElementType {
  const match = document.querySelector<ElementType>(selector);
  if (!match) throw new Error(`Missing demo element: ${selector}`);
  return match;
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
