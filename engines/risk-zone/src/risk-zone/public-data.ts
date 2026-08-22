import { GriddedFlowFieldProvider } from './flow-field.js';
import { distanceMeters } from './geo.js';
import { CoastAndBathymetryProvider } from './navigability.js';
import { simulateConditionalConnectivity } from './simulation.js';
import { RiskZoneValidationError } from './validation.js';
import type {
  GriddedFlowSample,
  MonitoringGate,
  NearshoreFlowPolicy,
  ObservationSeed,
  PolygonSeedGeometry,
  Position,
  SimulationConfig,
  SimulationResult,
} from './types.js';

/** A row after downloading an offshore or nearshore current dataset. */
export interface PublicCurrentRecord {
  issuedAt: string;
  validAt: string;
  longitude: number;
  latitude: number;
  depthMeters: number;
  uMetersPerSecond?: number;
  vMetersPerSecond?: number;
  speedMetersPerSecond?: number;
  directionDegrees?: number;
  directionConvention?: 'toward' | 'from';
}

/** A nearest-neighbour bathymetry record after downloading a depth dataset. */
export interface PublicBathymetryPoint {
  longitude: number;
  latitude: number;
  depthMeters: number;
}

export interface PublicCoastData {
  landPolygons: Position[][][];
  bathymetryPoints: PublicBathymetryPoint[];
  minimumWaterDepthMeters: number;
  sampleSpacingMeters?: number;
  maximumBathymetryLookupMeters?: number;
}

export interface PublicNearshoreData {
  zone: PolygonSeedGeometry;
  currents: PublicCurrentRecord[];
  /** Defaults to replace so independently modelled tide is never double counted. */
  mode?: 'replace' | 'residualAdd';
  /** Required when mode is residualAdd. */
  isResidual?: boolean;
}

/**
 * The only input shape a map, API route, or hackathon prototype needs.
 * It contains normalized public-data rows, not provider implementations.
 */
export interface PublicRiskZoneInput {
  observation: ObservationSeed;
  offshoreCurrents: PublicCurrentRecord[];
  nearshore?: PublicNearshoreData;
  coast: PublicCoastData;
  gate: MonitoringGate;
  config?: SimulationConfig;
}

/**
 * Converts public current records to the engine's u/v format. Direction uses
 * a compass bearing: 0° north, 90° east. A from-direction is reversed first.
 */
export function normalizePublicCurrentRecord(record: PublicCurrentRecord): GriddedFlowSample {
  const validAt = requiredDate(record.validAt, 'current.validAt');
  const sourceTime = requiredDate(record.issuedAt, 'current.issuedAt');
  validateFinite(record.longitude, 'current.longitude');
  validateFinite(record.latitude, 'current.latitude');
  validateFinite(record.depthMeters, 'current.depthMeters');

  const directVelocity =
    typeof record.uMetersPerSecond === 'number' && typeof record.vMetersPerSecond === 'number';
  let uMetersPerSecond: number;
  let vMetersPerSecond: number;

  if (directVelocity) {
    uMetersPerSecond = record.uMetersPerSecond!;
    vMetersPerSecond = record.vMetersPerSecond!;
  } else {
    if (
      typeof record.speedMetersPerSecond !== 'number' ||
      typeof record.directionDegrees !== 'number' ||
      !record.directionConvention
    ) {
      throw new RiskZoneValidationError(
        'current',
        'needs both u/v or speed, direction, and directionConvention',
      );
    }
    validateFinite(record.speedMetersPerSecond, 'current.speedMetersPerSecond');
    validateFinite(record.directionDegrees, 'current.directionDegrees');
    const travelBearing =
      record.directionDegrees + (record.directionConvention === 'from' ? 180 : 0);
    const radians = (travelBearing * Math.PI) / 180;
    uMetersPerSecond = record.speedMetersPerSecond * Math.sin(radians);
    vMetersPerSecond = record.speedMetersPerSecond * Math.cos(radians);
  }
  validateFinite(uMetersPerSecond, 'current.uMetersPerSecond');
  validateFinite(vMetersPerSecond, 'current.vMetersPerSecond');

  return {
    position: [record.longitude, record.latitude],
    depthMeters: record.depthMeters,
    sourceTime,
    validAt,
    uMetersPerSecond,
    vMetersPerSecond,
  };
}

/**
 * Builds the internal current and coast providers from ordinary public-data
 * rows, then calculates the same conditional connectivity result.
 */
export function calculateRiskZone(input: PublicRiskZoneInput): SimulationResult {
  const offshoreFlow = new GriddedFlowFieldProvider(
    input.offshoreCurrents.map(normalizePublicCurrentRecord),
  );
  const nearshorePolicy = input.nearshore
    ? createNearshorePolicy(input.nearshore)
    : undefined;
  const maximumBathymetryLookupMeters =
    input.coast.maximumBathymetryLookupMeters ?? 5_000;
  const navigability = new CoastAndBathymetryProvider({
    landPolygons: input.coast.landPolygons,
    bathymetry: {
      depthAt(position) {
        const closest = input.coast.bathymetryPoints.reduce<
          { point: PublicBathymetryPoint; distance: number } | undefined
        >((current, point) => {
          const distance = distanceMeters(position, [point.longitude, point.latitude]);
          return !current || distance < current.distance ? { point, distance } : current;
        }, undefined);
        if (!closest || closest.distance > maximumBathymetryLookupMeters) return null;
        return closest.point.depthMeters;
      },
    },
    minimumWaterDepthMeters: input.coast.minimumWaterDepthMeters,
    sampleSpacingMeters: input.coast.sampleSpacingMeters ?? 1_000,
  });

  return simulateConditionalConnectivity({
    seed: input.observation,
    offshoreFlow,
    nearshorePolicy,
    navigability,
    gate: input.gate,
    config: input.config,
  });
}

function createNearshorePolicy(nearshore: PublicNearshoreData): NearshoreFlowPolicy {
  const provider = new GriddedFlowFieldProvider(
    nearshore.currents.map(normalizePublicCurrentRecord),
  );
  if (nearshore.mode === 'residualAdd') {
    if (nearshore.isResidual !== true) {
      throw new RiskZoneValidationError(
        'nearshore.isResidual',
        'must be true when mode is residualAdd',
      );
    }
    return { zone: nearshore.zone, mode: 'residualAdd', isResidual: true, provider };
  }
  return { zone: nearshore.zone, mode: 'replace', provider };
}

function requiredDate(value: string, field: string): Date {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    throw new RiskZoneValidationError(field, 'must be an ISO-8601 timestamp');
  }
  return date;
}

function validateFinite(value: number, field: string): void {
  if (!Number.isFinite(value)) {
    throw new RiskZoneValidationError(field, 'must be finite');
  }
}
