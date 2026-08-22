import { effectiveVelocityAt } from './flow-field.js';
import { createLocalProjection, segmentsIntersect } from './geo.js';
import { buildConnectivityRegions } from './regions.js';
import { materializeParticles } from './seed.js';
import { validateSimulationInput } from './validation.js';
import { CONDITIONAL_CONNECTIVITY_DISCLAIMER } from '../index.js';
import type {
  MonitoringGate,
  MutableParticle,
  ParticleStatus,
  Position,
  SimulationDiagnostic,
  SimulationInput,
  SimulationResult,
} from './types.js';

const TERMINAL_STATUSES = new Set<ParticleStatus>([
  'blocked-land',
  'blocked-shallow-water',
  'outside-navigability-coverage',
  'outside-flow-coverage',
]);

export function simulateConditionalConnectivity(input: SimulationInput): SimulationResult {
  const config = validateSimulationInput(input);
  const startAt = new Date(input.seed.observedAt);
  const anchor = anchorForSeed(input.seed.geometry);
  const projection = createLocalProjection(anchor);
  const gate = normalizeGate(input.gate, projection);
  const particles = materializeParticles(input.seed, config.randomSeed);
  const diagnostics: SimulationDiagnostic[] = [];
  const snapshots = [] as SimulationResult['snapshots'];
  const statusAtHorizon = new Map<number, ParticleStatus[]>();
  const horizonMinutes = config.horizonsHours.map((hours) => hours * 60);
  const horizonMinuteSet = new Set(horizonMinutes);
  const maximumMinutes = Math.max(...horizonMinutes);
  let noLiveDiagnosticRecorded = false;

  for (let elapsedMinutes = config.timeStepMinutes; elapsedMinutes <= maximumMinutes; elapsedMinutes += config.timeStepMinutes) {
    const currentAt = new Date(startAt.valueOf() + (elapsedMinutes - config.timeStepMinutes) * 60_000);
    const midpointAt = new Date(currentAt.valueOf() + (config.timeStepMinutes * 60_000) / 2);
    const nextAt = new Date(startAt.valueOf() + elapsedMinutes * 60_000);

    for (const particle of particles) {
      if (!isLive(particle.status)) continue;
      const currentPosition = particle.coordinates.at(-1)!;
      const initialVelocity = effectiveVelocityAt(
        { position: currentPosition, depthMeters: particle.depthMeters, validAt: currentAt },
        input.offshoreFlow,
        input.nearshorePolicy,
      );
      if (!initialVelocity) {
        terminateForMissingFlow(particle, currentAt, diagnostics);
        continue;
      }

      const midpoint = advance(
        currentPosition,
        initialVelocity.uMetersPerSecond,
        initialVelocity.vMetersPerSecond,
        config.timeStepMinutes / 2,
        projection,
      );
      const midpointVelocity = effectiveVelocityAt(
        { position: midpoint, depthMeters: particle.depthMeters, validAt: midpointAt },
        input.offshoreFlow,
        input.nearshorePolicy,
      );
      if (!midpointVelocity) {
        terminateForMissingFlow(particle, midpointAt, diagnostics);
        continue;
      }

      const nextPosition = advance(
        currentPosition,
        midpointVelocity.uMetersPerSecond,
        midpointVelocity.vMetersPerSecond,
        config.timeStepMinutes,
        projection,
      );
      const traversal = input.navigability.canTraverse({
        from: currentPosition,
        to: nextPosition,
        particleDepthMeters: particle.depthMeters,
        at: nextAt,
      });
      if (!traversal.passable) {
        const status = navigationStatus(traversal.reason);
        particle.status = status;
        diagnostics.push({
          code: 'navigability-rejection',
          particleId: particle.id,
          validAt: nextAt.toISOString(),
          message: `Particle movement rejected because of ${traversal.reason ?? 'unclassified coverage'}.`,
        });
        continue;
      }

      particle.coordinates.push(nextPosition);
      if (
        particle.firstGateArrivalAt === null &&
        particle.depthMeters >= input.gate.minDepthMeters &&
        particle.depthMeters <= input.gate.maxDepthMeters &&
        segmentsIntersect(currentPosition, nextPosition, gate.start, gate.end)
      ) {
        particle.firstGateArrivalAt = nextAt;
        particle.status = 'gate-reached';
      }
    }

    const liveParticles = particles.filter((particle) => isLive(particle.status));
    if (liveParticles.length === 0 && !noLiveDiagnosticRecorded) {
      diagnostics.push({
        code: 'no-live-particles',
        validAt: nextAt.toISOString(),
        message: 'No particle remains in flow and navigability coverage.',
      });
      noLiveDiagnosticRecorded = true;
    }

    if (
      elapsedMinutes % config.snapshotIntervalMinutes === 0 ||
      horizonMinuteSet.has(elapsedMinutes)
    ) {
      snapshots.push({
        validAt: nextAt.toISOString(),
        regions: buildConnectivityRegions(
          liveParticles.map((particle) => particle.coordinates.at(-1)!),
          anchor,
          config.regionCellSizeMeters,
        ),
        representedParticleCount: liveParticles.length,
      });
    }
    if (horizonMinuteSet.has(elapsedMinutes)) {
      statusAtHorizon.set(elapsedMinutes, particles.map((particle) => particle.status));
    }
  }

  return {
    classification: 'conditional-connectivity-not-blockage-probability',
    disclaimer: CONDITIONAL_CONNECTIVITY_DISCLAIMER,
    inputSummary: {
      observedAt: input.seed.observedAt,
      species: input.seed.species,
      depthMeters: input.seed.depthMeters,
      confidence: input.seed.confidence,
      ensembleSize: input.seed.ensembleSize,
      horizonHours: [...config.horizonsHours],
    },
    horizonSummaries: config.horizonsHours.map((horizonHours) => {
      const elapsedMinutes = horizonHours * 60;
      const arrivedMinutes = particles
        .flatMap((particle) => {
          if (!particle.firstGateArrivalAt) return [];
          const minutes = (particle.firstGateArrivalAt.valueOf() - startAt.valueOf()) / 60_000;
          return minutes <= elapsedMinutes ? [minutes] : [];
        });
      return {
        horizonHours,
        conditionalGateConnectionFraction: arrivedMinutes.length / particles.length,
        firstGateCrossingCount: arrivedMinutes.length,
        etaMinutes: {
          p10: nearestRankPercentile(arrivedMinutes, 10),
          p50: nearestRankPercentile(arrivedMinutes, 50),
          p90: nearestRankPercentile(arrivedMinutes, 90),
        },
        particleStatusCounts: countStatuses(statusAtHorizon.get(elapsedMinutes) ?? []),
      };
    }),
    snapshots,
    particleTrajectories: particles.map((particle) => ({
      id: particle.id,
      status: particle.status,
      firstGateArrivalAt: particle.firstGateArrivalAt?.toISOString() ?? null,
      coordinates: particle.coordinates,
    })),
    diagnostics,
  };
}

export function nearestRankPercentile(
  values: readonly number[],
  percentile: 10 | 50 | 90,
): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil((percentile / 100) * sorted.length) - 1];
}

function anchorForSeed(geometry: SimulationInput['seed']['geometry']): Position {
  return geometry.kind === 'point' ? geometry.position : geometry.rings[0][0];
}

function normalizeGate(
  gate: MonitoringGate,
  projection: ReturnType<typeof createLocalProjection>,
): { start: Position; end: Position } {
  if (gate.kind === 'endpoints') return { start: gate.start, end: gate.end };
  const center = projection.toLocal(gate.center);
  const lineBearingRadians = (gate.bearingDegrees * Math.PI) / 180;
  const halfWidth = gate.widthMeters / 2;
  const offsetX = Math.sin(lineBearingRadians) * halfWidth;
  const offsetY = Math.cos(lineBearingRadians) * halfWidth;
  return {
    start: projection.toGeographic([center[0] - offsetX, center[1] - offsetY]),
    end: projection.toGeographic([center[0] + offsetX, center[1] + offsetY]),
  };
}

function advance(
  position: Position,
  uMetersPerSecond: number,
  vMetersPerSecond: number,
  minutes: number,
  projection: ReturnType<typeof createLocalProjection>,
): Position {
  const local = projection.toLocal(position);
  const durationSeconds = minutes * 60;
  return projection.toGeographic([
    local[0] + uMetersPerSecond * durationSeconds,
    local[1] + vMetersPerSecond * durationSeconds,
  ]);
}

function isLive(status: ParticleStatus): boolean {
  return !TERMINAL_STATUSES.has(status);
}

function terminateForMissingFlow(
  particle: MutableParticle,
  validAt: Date,
  diagnostics: SimulationDiagnostic[],
): void {
  particle.status = 'outside-flow-coverage';
  diagnostics.push({
    code: 'flow-coverage-miss',
    particleId: particle.id,
    validAt: validAt.toISOString(),
    message: 'No current vector covered this particle position, depth, and time.',
  });
}

function navigationStatus(reason: string | undefined): ParticleStatus {
  if (reason === 'land') return 'blocked-land';
  if (reason === 'shallow-water') return 'blocked-shallow-water';
  return 'outside-navigability-coverage';
}

function countStatuses(statuses: readonly ParticleStatus[]): Record<ParticleStatus, number> {
  const counts: Record<ParticleStatus, number> = {
    active: 0,
    'gate-reached': 0,
    'blocked-land': 0,
    'blocked-shallow-water': 0,
    'outside-navigability-coverage': 0,
    'outside-flow-coverage': 0,
  };
  for (const status of statuses) counts[status] += 1;
  return counts;
}
