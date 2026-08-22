import type { FeatureCollection, MultiPolygon } from 'geojson';

export type Position = readonly [longitude: number, latitude: number];

export interface PointSeedGeometry {
  kind: 'point';
  position: Position;
}

export interface PolygonSeedGeometry {
  kind: 'polygon';
  /** The first ring is exterior; any following rings are exclusions. */
  rings: Position[][];
}

export interface ObservationSeed {
  observedAt: string;
  species: string;
  geometry: PointSeedGeometry | PolygonSeedGeometry;
  depthMeters: number;
  confidence: number;
  ensembleSize: number;
  positionUncertaintyMeters: number;
}

export interface VelocityRequest {
  position: Position;
  depthMeters: number;
  validAt: Date;
}

export interface VelocitySample {
  uMetersPerSecond: number;
  vMetersPerSecond: number;
  sourceTime: Date;
  validAt: Date;
}

export interface FlowFieldProvider {
  velocityAt(request: VelocityRequest): VelocitySample | null;
}

export type NearshoreFlowPolicy =
  | {
      zone: PolygonSeedGeometry;
      mode: 'replace';
      provider: FlowFieldProvider;
    }
  | {
      zone: PolygonSeedGeometry;
      mode: 'residualAdd';
      isResidual: true;
      provider: FlowFieldProvider;
    };

export type TraversalRejectionReason = 'land' | 'shallow-water' | 'outside-coverage';

export interface TraversalResult {
  passable: boolean;
  reason?: TraversalRejectionReason;
}

export interface NavigabilityProvider {
  canTraverse(request: {
    from: Position;
    to: Position;
    particleDepthMeters: number;
    at: Date;
  }): TraversalResult;
}

export interface EndpointMonitoringGate {
  kind: 'endpoints';
  start: Position;
  end: Position;
  minDepthMeters: number;
  maxDepthMeters: number;
}

export interface CenterMonitoringGate {
  kind: 'center';
  center: Position;
  widthMeters: number;
  bearingDegrees: number;
  minDepthMeters: number;
  maxDepthMeters: number;
}

export type MonitoringGate = EndpointMonitoringGate | CenterMonitoringGate;

export interface SimulationConfig {
  horizonsHours?: number[];
  timeStepMinutes?: number;
  snapshotIntervalMinutes?: number;
  regionCellSizeMeters?: number;
  randomSeed?: number;
}

export interface RequiredSimulationConfig {
  horizonsHours: number[];
  timeStepMinutes: number;
  snapshotIntervalMinutes: number;
  regionCellSizeMeters: number;
  randomSeed: number;
}

export interface SimulationInput {
  seed: ObservationSeed;
  offshoreFlow: FlowFieldProvider;
  nearshorePolicy?: NearshoreFlowPolicy;
  navigability: NavigabilityProvider;
  gate: MonitoringGate;
  config?: SimulationConfig;
}

export type ParticleStatus =
  | 'active'
  | 'gate-reached'
  | 'blocked-land'
  | 'blocked-shallow-water'
  | 'outside-navigability-coverage'
  | 'outside-flow-coverage';

export interface ParticleTrajectory {
  id: string;
  status: ParticleStatus;
  firstGateArrivalAt: string | null;
  coordinates: Position[];
}

export interface HorizonSummary {
  horizonHours: number;
  conditionalGateConnectionFraction: number;
  firstGateCrossingCount: number;
  etaMinutes: { p10: number | null; p50: number | null; p90: number | null };
  particleStatusCounts: Record<ParticleStatus, number>;
}

export interface SimulationSnapshot {
  validAt: string;
  regions: FeatureCollection<MultiPolygon>;
  representedParticleCount: number;
}

export type SimulationDiagnosticCode =
  | 'flow-coverage-miss'
  | 'navigability-rejection'
  | 'no-live-particles';

export interface SimulationDiagnostic {
  code: SimulationDiagnosticCode;
  particleId?: string;
  validAt: string;
  message: string;
}

export interface SimulationResult {
  classification: 'conditional-connectivity-not-blockage-probability';
  disclaimer: string;
  inputSummary: {
    observedAt: string;
    species: string;
    depthMeters: number;
    confidence: number;
    ensembleSize: number;
    horizonHours: number[];
  };
  horizonSummaries: HorizonSummary[];
  snapshots: SimulationSnapshot[];
  particleTrajectories: ParticleTrajectory[];
  diagnostics: SimulationDiagnostic[];
}
