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
import type { Position, VelocitySample } from '../../src/risk-zone/types.js';
import {
  buildCurrentOrientedFanEnvelope,
  traceUpstreamCurrentCenterline,
} from './map-data.js';
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

timeline.addEventListener('input', () => renderScenario(true));

function renderScenario(fitViewport: boolean): void {
  const selectedHours = Number(timeline.value);
  const current = representativeCurrentAt(selectedScenario, selectedHours);
  const approachBands = current
    ? buildCurrentOrientedFanEnvelope({
      intakePosition: selectedScenario.intakePosition,
      uMetersPerSecond: current.uMetersPerSecond,
      vMetersPerSecond: current.vMetersPerSecond,
      sampleVelocityAt: (position) => currentVectorAt(selectedScenario, selectedHours, position),
    })
    : emptyCollection<Polygon>();

  timelineValue.textContent = `${selectedHours}시간`;
  scenarioDescription.textContent = selectedScenario.description;
  mapContext.textContent = selectedScenario.mapContext === 'real-site'
    ? '울진 동해안 · 한울원전 위치 맥락'
    : '설명용 가상 해안 · 가상 시설';
  disclaimer.textContent = selectedScenario.mapContext === 'real-site'
    ? `한울원전 위치만 실제 지도 맥락입니다. ${result.disclaimer}`
    : result.disclaimer;

  source(map, 'coast').setData(selectedScenario.coast);
  source(map, 'approach-bands').setData(approachBands);
  source(map, 'current-arrows').setData(current
    ? buildCurrentArrows(selectedScenario, selectedHours, current)
    : emptyCollection<LineString>());
  source(map, 'seed').setData(buildSeed(selectedScenario));
  source(map, 'gate').setData(buildGate(selectedScenario));
  source(map, 'intake').setData(buildIntakeMarkers(selectedScenario));
  updateStatus(current, approachBands.features.length > 0);

  if (fitViewport) fitScenario(map, selectedScenario, approachBands);
}

function updateStatus(current: VelocitySample | null, hasCompleteCoverage: boolean): void {
  if (!current || !hasCompleteCoverage) {
    pathStatus.textContent = '선택 시점의 해류 데이터 범위가 부족합니다';
    pathStatus.dataset.connected = 'false';
    connectionValue.textContent = '데이터 없음';
    etaValue.textContent = '—';
    return;
  }
  const speed = Math.hypot(current.uMetersPerSecond, current.vMetersPerSecond);
  const bearing = normalizeDegrees(
    (Math.atan2(current.uMetersPerSecond, current.vMetersPerSecond) * 180) / Math.PI,
  );

  pathStatus.textContent = '전체 곡선 접근영역 표시 중';
  pathStatus.dataset.connected = 'true';
  connectionValue.textContent = `${compassDirection(bearing)} ${Math.round(bearing)}°`;
  etaValue.textContent = `${speed.toFixed(2)} m/s`;
}

function addSourcesAndLayers(target: Map): void {
  target.addSource('coast', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('approach-bands', { type: 'geojson', data: emptyCollection<Polygon>() });
  target.addSource('current-arrows', { type: 'geojson', data: emptyCollection<LineString>() });
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
  representativeCurrent: VelocitySample,
): FeatureCollection<LineString> {
  const centerline = traceUpstreamCurrentCenterline({
    intakePosition: scenario.intakePosition,
    uMetersPerSecond: representativeCurrent.uMetersPerSecond,
    vMetersPerSecond: representativeCurrent.vMetersPerSecond,
    sampleVelocityAt: (position) => currentVectorAt(scenario, selectedHours, position),
  });
  if (!centerline.coverageComplete || centerline.positions.length < 2) {
    return emptyCollection<LineString>();
  }
  const projection = createLocalProjection(scenario.intakePosition);
  const localCenterline = centerline.positions.map((position) => projection.toLocal(position));
  const lastIndex = localCenterline.length - 1;
  const features: Array<Feature<LineString>> = [];

  for (const fraction of [0.18, 0.4, 0.62, 0.84]) {
    const index = Math.round(lastIndex * fraction);
    const center = localCenterline[index]!;
    const previous = localCenterline[Math.max(0, index - 1)]!;
    const next = localCenterline[Math.min(lastIndex, index + 1)]!;
    const tangentLength = Math.hypot(next[0] - previous[0], next[1] - previous[1]) || 1;
    const normalX = -(next[1] - previous[1]) / tangentLength;
    const normalY = (next[0] - previous[0]) / tangentLength;
    const halfWidth = centerline.envelopeLengthMeters * fraction * Math.tan(
      (centerline.halfAngleDegrees * Math.PI) / 180,
    );
    for (const lateralFraction of [-0.38, 0.38]) {
      const position = projection.toGeographic([
        center[0] + normalX * halfWidth * lateralFraction,
        center[1] + normalY * halfWidth * lateralFraction,
      ]);
      const velocity = scenario.input.offshoreFlow.velocityAt({
        position,
        depthMeters: scenario.input.seed.depthMeters,
        validAt: selectedValidAt(scenario, selectedHours),
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

function representativeCurrentAt(
  scenario: DemoScenario,
  selectedHours: number,
): VelocitySample | null {
  const validAt = selectedValidAt(scenario, selectedHours);
  return scenario.input.offshoreFlow.velocityAt({
    position: scenario.intakePosition,
    depthMeters: scenario.input.seed.depthMeters,
    validAt,
  });
}

function currentVectorAt(
  scenario: DemoScenario,
  selectedHours: number,
  position: Position,
): Pick<VelocitySample, 'uMetersPerSecond' | 'vMetersPerSecond'> | null {
  const sample = scenario.input.offshoreFlow.velocityAt({
    position,
    depthMeters: scenario.input.seed.depthMeters,
    validAt: selectedValidAt(scenario, selectedHours),
  });
  return sample ? {
    uMetersPerSecond: sample.uMetersPerSecond,
    vMetersPerSecond: sample.vMetersPerSecond,
  } : null;
}

function selectedValidAt(scenario: DemoScenario, selectedHours: number): Date {
  return new Date(
    new Date(scenario.input.seed.observedAt).valueOf() + selectedHours * 3_600_000,
  );
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

function fitScenario(
  target: Map,
  scenario: DemoScenario,
  approachBands: FeatureCollection<Polygon>,
): void {
  const seed = seedPosition(scenario);
  const bounds = new LngLatBounds(toMapPosition(seed), toMapPosition(seed));
  bounds.extend(toMapPosition(scenario.sitePosition));
  bounds.extend(toMapPosition(scenario.intakePosition));
  for (const feature of approachBands.features) {
    for (const ring of feature.geometry.coordinates) {
      for (const [longitude, latitude] of ring) {
        if (longitude !== undefined && latitude !== undefined) {
          bounds.extend([longitude, latitude]);
        }
      }
    }
  }
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

function compassDirection(bearingDegrees: number): string {
  const labels = ['북향', '북동향', '동향', '남동향', '남향', '남서향', '서향', '북서향'];
  return labels[Math.round(bearingDegrees / 45) % labels.length]!;
}

function normalizeDegrees(value: number): number {
  return ((value % 360) + 360) % 360;
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
