import type { FeatureCollection, Polygon, Position as GeoJsonPosition } from 'geojson';
import { createLocalProjection, pointInPolygon } from '../../src/risk-zone/geo.js';
import type {
  FlowFieldProvider,
  NavigabilityProvider,
  Position,
  SimulationInput,
  VelocitySample,
} from '../../src/risk-zone/types.js';

const observedAt = '2026-08-23T00:00:00.000Z';
const fictionalSeedPosition: Position = [129.15, 37.15];

export const HANUL_SITE_POSITION: Position = [129.38301, 37.0931];
export const HANUL_INTAKE_POSITION: Position = [129.397, 37.0931];
export const HANUL_OFFSHORE_SEED_POSITION: Position = [129.56, 37.105];

export interface DemoScenario {
  id: 'hanul-approach' | 'eastward-spread' | 'tidal-turn' | 'coastal-interception';
  name: string;
  description: string;
  isFictional: true;
  dataMode: 'synthetic';
  mapContext: 'real-site' | 'fictional-site';
  sitePosition: Position;
  intakePosition: Position;
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

const noSyntheticConstraints: FeatureCollection<Polygon> = {
  type: 'FeatureCollection',
  features: [],
};

export const demoScenarios: DemoScenario[] = [
  createHanulScenario(),
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
    dataMode: 'synthetic',
    mapContext: 'fictional-site',
    sitePosition: [129.305, 37.155],
    intakePosition: [129.31, 37.155],
    coast: fictionalCoast,
    input: {
      seed: {
        observedAt,
        species: 'fictional-jellyfish-cluster',
        geometry: { kind: 'point', position: fictionalSeedPosition },
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

function createHanulScenario(): DemoScenario {
  return {
    id: 'hanul-approach',
    name: '한울원전 접근 흐름',
    description: '울진 한울원전 동쪽 해상에서 관측된 더미 군집이 합성 해류를 따라 취수구 감시선으로 접근하는 시나리오입니다.',
    isFictional: true,
    dataMode: 'synthetic',
    mapContext: 'real-site',
    sitePosition: HANUL_SITE_POSITION,
    intakePosition: HANUL_INTAKE_POSITION,
    coast: noSyntheticConstraints,
    input: {
      seed: {
        observedAt,
        species: 'synthetic-jellyfish-cluster',
        geometry: { kind: 'point', position: HANUL_OFFSHORE_SEED_POSITION },
        depthMeters: 1,
        confidence: 0.72,
        ensembleSize: 72,
        positionUncertaintyMeters: 1_100,
      },
      offshoreFlow: targetSeekingFlow(HANUL_SITE_POSITION),
      navigability: hanulDemoNavigability(),
      gate: {
        kind: 'endpoints',
        start: [HANUL_INTAKE_POSITION[0], 37.078],
        end: [HANUL_INTAKE_POSITION[0], 37.108],
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

function targetSeekingFlow(target: Position): FlowFieldProvider {
  return {
    velocityAt: ({ position, validAt }): VelocitySample => {
      const [towardTargetX, towardTargetY] = createLocalProjection(position).toLocal(target);
      const distance = Math.hypot(towardTargetX, towardTargetY);
      const elapsedHours = (validAt.valueOf() - new Date(observedAt).valueOf()) / 3_600_000;
      if (distance < 250) {
        return {
          uMetersPerSecond: -0.08,
          vMetersPerSecond: 0,
          sourceTime: new Date(observedAt),
          validAt,
        };
      }

      const phase = (elapsedHours / 24) * Math.PI;
      const speed = 0.24 + 0.1 * Math.sin(phase);
      const [offshoreDistance, alongshoreDistance] = createLocalProjection(target).toLocal(position);
      const crossCurrent = 0.11 * Math.sin(
        phase + offshoreDistance / 2_500 + alongshoreDistance / 5_000,
      );
      const eastUnit = towardTargetX / distance;
      const northUnit = towardTargetY / distance;
      return {
        uMetersPerSecond: speed * eastUnit - crossCurrent * northUnit,
        vMetersPerSecond: speed * northUnit + crossCurrent * eastUnit,
        sourceTime: new Date(observedAt),
        validAt,
      };
    },
  };
}

function hanulDemoNavigability(): NavigabilityProvider {
  return {
    canTraverse: ({ to }) => to[0] < 129.381
      ? { passable: false, reason: 'land' }
      : { passable: true },
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
