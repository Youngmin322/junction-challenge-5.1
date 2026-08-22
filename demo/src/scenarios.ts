import type { FeatureCollection, Polygon, Position as GeoJsonPosition } from 'geojson';
import { pointInPolygon } from '../../src/risk-zone/geo.js';
import type {
  FlowFieldProvider,
  NavigabilityProvider,
  Position,
  SimulationInput,
  VelocitySample,
} from '../../src/risk-zone/types.js';

const observedAt = '2026-08-23T00:00:00.000Z';
const seedPosition: Position = [129.15, 37.15];

export interface DemoScenario {
  id: 'eastward-spread' | 'tidal-turn' | 'coastal-interception';
  name: string;
  description: string;
  isFictional: true;
  input: SimulationInput;
  coast: FeatureCollection<Polygon>;
}

interface FlowVector {
  startsAtHours: number;
  uMetersPerSecond: number;
  vMetersPerSecond: number;
}

const fictionalCoast: FeatureCollection<Polygon> = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { kind: 'fictional-land', label: '가상 해안선' },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [129.08, 37.08],
          [129.08, 37.24],
          [129.125, 37.24],
          [129.125, 37.20],
          [129.11, 37.18],
          [129.125, 37.15],
          [129.125, 37.08],
          [129.08, 37.08],
        ]],
      },
    },
    {
      type: 'Feature',
      properties: { kind: 'fictional-shallow-water', label: '가상 얕은 수역' },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [129.17, 37.10],
          [129.20, 37.10],
          [129.20, 37.13],
          [129.17, 37.13],
          [129.17, 37.10],
        ]],
      },
    },
  ],
};

const landRings = fictionalCoast.features
  .filter((feature) => feature.properties?.kind === 'fictional-land')
  .map((feature) => toPositionRing(feature.geometry.coordinates[0]!));
const shallowRings = fictionalCoast.features
  .filter((feature) => feature.properties?.kind === 'fictional-shallow-water')
  .map((feature) => toPositionRing(feature.geometry.coordinates[0]!));

export const demoScenarios: DemoScenario[] = [
  createScenario({
    id: 'eastward-spread',
    name: '동쪽 확산',
    description: '일정한 동북동 흐름을 따라 군집이 바다 쪽으로 퍼지는 가상 시나리오입니다.',
    flow: [{ startsAtHours: 0, uMetersPerSecond: 0.18, vMetersPerSecond: 0.06 }],
    navigability: openWater(),
  }),
  createScenario({
    id: 'tidal-turn',
    name: '조류 반전',
    description: '4시간 뒤 흐름이 남동쪽으로 바뀌며 이동 영역이 휘는 가상 시나리오입니다.',
    flow: [
      { startsAtHours: 0, uMetersPerSecond: 0.2, vMetersPerSecond: 0.08 },
      { startsAtHours: 4, uMetersPerSecond: 0.04, vMetersPerSecond: -0.16 },
    ],
    navigability: openWater(),
  }),
  createScenario({
    id: 'coastal-interception',
    name: '해안 차단',
    description: '일부 이동 경로가 가상 해안선과 얕은 수역에 닿아 멈추는 가상 시나리오입니다.',
    flow: [
      { startsAtHours: 0, uMetersPerSecond: -0.12, vMetersPerSecond: -0.04 },
      { startsAtHours: 4, uMetersPerSecond: 0.1, vMetersPerSecond: -0.02 },
    ],
    navigability: fictionalNavigability(),
  }),
];

export function getDemoScenario(id: DemoScenario['id']): DemoScenario {
  const scenario = demoScenarios.find((candidate) => candidate.id === id);
  if (!scenario) throw new Error(`Unknown demo scenario: ${id}`);
  return scenario;
}

function createScenario(args: {
  id: DemoScenario['id'];
  name: string;
  description: string;
  flow: FlowVector[];
  navigability: NavigabilityProvider;
}): DemoScenario {
  return {
    id: args.id,
    name: args.name,
    description: args.description,
    isFictional: true,
    coast: fictionalCoast,
    input: {
      seed: {
        observedAt,
        species: 'fictional-jellyfish-cluster',
        geometry: { kind: 'point', position: seedPosition },
        depthMeters: 1,
        confidence: 0.75,
        ensembleSize: 48,
        positionUncertaintyMeters: 650,
      },
      offshoreFlow: scheduledFlow(args.flow),
      navigability: args.navigability,
      gate: {
        kind: 'endpoints',
        start: [129.31, 37.08],
        end: [129.31, 37.23],
        minDepthMeters: 0,
        maxDepthMeters: 5,
      },
      config: {
        horizonsHours: [2, 4, 24, 48],
        timeStepMinutes: 15,
        snapshotIntervalMinutes: 60,
        regionCellSizeMeters: 500,
        randomSeed: 20260823,
      },
    },
  };
}

function scheduledFlow(schedule: readonly FlowVector[]): FlowFieldProvider {
  const ordered = [...schedule].sort((left, right) => left.startsAtHours - right.startsAtHours);
  return {
    velocityAt: ({ validAt }): VelocitySample => {
      const elapsedHours = (validAt.valueOf() - new Date(observedAt).valueOf()) / 3_600_000;
      const vector = flowVectorAt(ordered, elapsedHours);
      return {
        uMetersPerSecond: vector.uMetersPerSecond,
        vMetersPerSecond: vector.vMetersPerSecond,
        sourceTime: new Date(observedAt),
        validAt,
      };
    },
  };
}

function flowVectorAt(schedule: readonly FlowVector[], elapsedHours: number): FlowVector {
  for (let index = schedule.length - 1; index >= 0; index -= 1) {
    const candidate = schedule[index]!;
    if (candidate.startsAtHours <= elapsedHours) return candidate;
  }
  return schedule[0]!;
}

function openWater(): NavigabilityProvider {
  return { canTraverse: () => ({ passable: true }) };
}

function toPositionRing(coordinates: readonly GeoJsonPosition[]): Position[] {
  return coordinates.map((coordinate): Position => {
    const [longitude, latitude] = coordinate;
    if (longitude === undefined || latitude === undefined) {
      throw new Error('A fictional coast coordinate must include longitude and latitude.');
    }
    return [longitude, latitude];
  });
}

function fictionalNavigability(): NavigabilityProvider {
  return {
    canTraverse: ({ to }) => {
      if (landRings.some((ring) => pointInPolygon(to, [ring]))) {
        return { passable: false, reason: 'land' };
      }
      if (shallowRings.some((ring) => pointInPolygon(to, [ring]))) {
        return { passable: false, reason: 'shallow-water' };
      }
      return { passable: true };
    },
  };
}
