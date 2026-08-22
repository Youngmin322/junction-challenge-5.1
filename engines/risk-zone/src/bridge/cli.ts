/**
 * stdin/stdout bridge that lets the Python MCP service call calculateRiskZone().
 *
 * The bridge owns no science. It converts one JSON request into the public
 * engine input, runs the published entry point, and returns raw particle
 * trajectories plus native gate connectivity. Grid-cell bookkeeping stays in
 * the Python DomainGrid so the two runtimes cannot drift apart on cell math.
 */
import { calculateRiskZone } from '../index.js';
import type {
  MonitoringGate,
  PublicCurrentRecord,
  PublicBathymetryPoint,
  SimulationResult,
} from '../index.js';

export const BRIDGE_VERSION = 'risk-zone-bridge-v1';
export const ENGINE_VERSION = 'risk-zone-connectivity-v1';

interface BridgeSeed {
  seed_id: string;
  lon: number;
  lat: number;
  reference_time: string;
}

interface BridgeZone {
  zone_id: string;
  lon: number;
  lat: number;
}

export interface BridgeRequest {
  request_version: string;
  seeds: BridgeSeed[];
  field: { profile_id: string; u_ms: number; v_ms: number; issued_at: string; valid_at: string };
  horizons_h: number[];
  domain: {
    domain_id: string;
    lon_min: number;
    lon_max: number;
    lat_min: number;
    lat_max: number;
    spacing_deg: number;
  };
  zones: BridgeZone[];
  ensemble: {
    size: number;
    position_uncertainty_m: number;
    depth_m: number;
    confidence: number;
    species: string;
  };
  navigability: {
    mode: 'synthetic_flat';
    flat_depth_m: number;
    minimum_water_depth_m: number;
    lookup_radius_m: number;
    land_polygons: [number, number][][][];
  };
  /**
   * bearing_deg is optional. When it is null the gate is laid perpendicular to
   * the field vector, which is the only orientation that actually intercepts
   * the modelled approach instead of sitting alongside it.
   */
  gate: {
    width_m: number;
    bearing_deg: number | null;
    min_depth_m: number;
    max_depth_m: number;
  };
  config: {
    time_step_minutes: number;
    snapshot_interval_minutes: number;
    region_cell_size_m: number;
    random_seed: number;
  };
}

/**
 * A constant synthetic field still has to be expressed as dated records because
 * the engine refuses to extrapolate outside the bracketing valid times.
 */
function buildCurrents(request: BridgeRequest, seed: BridgeSeed): PublicCurrentRecord[] {
  const { domain, field, ensemble } = request;
  const start = new Date(seed.reference_time);
  const maximumHours = Math.max(...request.horizons_h);
  const end = new Date(start.valueOf() + maximumHours * 3_600_000);
  const corners: [number, number][] = [
    [domain.lon_min, domain.lat_min],
    [domain.lon_min, domain.lat_max],
    [domain.lon_max, domain.lat_min],
    [domain.lon_max, domain.lat_max],
    [(domain.lon_min + domain.lon_max) / 2, (domain.lat_min + domain.lat_max) / 2],
  ];
  const records: PublicCurrentRecord[] = [];
  for (const validAt of [start, end]) {
    for (const [longitude, latitude] of corners) {
      records.push({
        issuedAt: field.issued_at,
        validAt: validAt.toISOString(),
        longitude,
        latitude,
        depthMeters: ensemble.depth_m,
        uMetersPerSecond: field.u_ms,
        vMetersPerSecond: field.v_ms,
      });
    }
  }
  return records;
}

/**
 * Bathymetry points cover the synthetic domain only. Outside the covered area
 * depthAt() returns null and the engine terminates the particle for missing
 * coverage instead of guessing a depth.
 */
function buildBathymetry(request: BridgeRequest): PublicBathymetryPoint[] {
  const { domain, navigability } = request;
  const points: PublicBathymetryPoint[] = [];
  const columns = Math.round((domain.lon_max - domain.lon_min) / domain.spacing_deg);
  const rows = Math.round((domain.lat_max - domain.lat_min) / domain.spacing_deg);
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      points.push({
        longitude: domain.lon_min + column * domain.spacing_deg,
        latitude: domain.lat_min + row * domain.spacing_deg,
        depthMeters: navigability.flat_depth_m,
      });
    }
  }
  return points;
}

export function gateBearingDegrees(request: BridgeRequest): number {
  if (request.gate.bearing_deg !== null && request.gate.bearing_deg !== undefined) {
    return request.gate.bearing_deg;
  }
  const { u_ms, v_ms } = request.field;
  if (u_ms === 0 && v_ms === 0) return 0;
  const travelBearing = (Math.atan2(u_ms, v_ms) * 180) / Math.PI;
  return (travelBearing + 90 + 360) % 360;
}

function buildGate(request: BridgeRequest, zone: BridgeZone): MonitoringGate {
  return {
    kind: 'center',
    center: [zone.lon, zone.lat],
    widthMeters: request.gate.width_m,
    bearingDegrees: gateBearingDegrees(request),
    minDepthMeters: request.gate.min_depth_m,
    maxDepthMeters: request.gate.max_depth_m,
  };
}

function runOne(request: BridgeRequest, seed: BridgeSeed, zone: BridgeZone): SimulationResult {
  return calculateRiskZone({
    observation: {
      observedAt: seed.reference_time,
      species: request.ensemble.species,
      geometry: { kind: 'point', position: [seed.lon, seed.lat] },
      depthMeters: request.ensemble.depth_m,
      confidence: request.ensemble.confidence,
      ensembleSize: request.ensemble.size,
      positionUncertaintyMeters: request.ensemble.position_uncertainty_m,
    },
    offshoreCurrents: buildCurrents(request, seed),
    coast: {
      landPolygons: request.navigability.land_polygons,
      bathymetryPoints: buildBathymetry(request),
      minimumWaterDepthMeters: request.navigability.minimum_water_depth_m,
      maximumBathymetryLookupMeters: request.navigability.lookup_radius_m,
    },
    gate: buildGate(request, zone),
    config: {
      horizonsHours: [...request.horizons_h].sort((left, right) => left - right),
      timeStepMinutes: request.config.time_step_minutes,
      snapshotIntervalMinutes: request.config.snapshot_interval_minutes,
      regionCellSizeMeters: request.config.region_cell_size_m,
      randomSeed: request.config.random_seed,
    },
  });
}

export function runBridge(request: BridgeRequest): Record<string, unknown> {
  if (request.request_version !== BRIDGE_VERSION) {
    throw new Error(`unsupported request_version: ${request.request_version}`);
  }
  if (request.seeds.length === 0) throw new Error('seeds must not be empty');
  if (request.zones.length === 0) throw new Error('zones must not be empty');

  const sortedSeeds = [...request.seeds].sort((left, right) =>
    left.seed_id < right.seed_id ? -1 : left.seed_id > right.seed_id ? 1 : 0,
  );
  const horizons = [...request.horizons_h].sort((left, right) => left - right);

  const seedResults = sortedSeeds.map((seed) => {
    const byZone = new Map<string, SimulationResult>();
    for (const zone of request.zones) byZone.set(zone.zone_id, runOne(request, seed, zone));
    // Every gate run replays the same particles from the same randomSeed, so the
    // geometry below is gate-independent. Only arrival bookkeeping differs.
    const geometryRun = byZone.get(request.zones[0]!.zone_id)!;
    return { seed, byZone, geometryRun };
  });

  const particles = seedResults.flatMap(({ seed, geometryRun }) =>
    geometryRun.particleTrajectories.map((trajectory) => ({
      seed_id: seed.seed_id,
      particle_id: trajectory.id,
      status: trajectory.status,
      coordinates: trajectory.coordinates.map(([longitude, latitude]) => [longitude, latitude]),
    })),
  );

  const gates: Record<string, unknown> = {};
  for (const zone of request.zones) {
    let previousHorizon = 0;
    let firstCrossingWindow: { from_h: number; to_h: number; basis: string } | null = null;
    const perHorizon = horizons.map((horizonHours) => {
      let connected = 0;
      let total = 0;
      const statusCounts: Record<string, number> = {};
      for (const { byZone } of seedResults) {
        const summary = byZone
          .get(zone.zone_id)!
          .horizonSummaries.find((item) => item.horizonHours === horizonHours);
        if (!summary) throw new Error(`missing horizon summary for ${horizonHours}h`);
        connected += summary.firstGateCrossingCount;
        total += request.ensemble.size;
        for (const [status, count] of Object.entries(summary.particleStatusCounts)) {
          statusCounts[status] = (statusCounts[status] ?? 0) + count;
        }
      }
      // Percentiles of the simulated crossing minutes are deliberately not
      // reported. Under a synthetic constant field they would read as a
      // precise ETA, which the product contract forbids. The horizon bracket
      // below carries the same meaning as intersect_zone's window.
      if (connected > 0 && firstCrossingWindow === null) {
        firstCrossingWindow = {
          from_h: previousHorizon,
          to_h: horizonHours,
          basis: 'requested_horizon_bracket',
        };
      }
      previousHorizon = horizonHours;
      return {
        horizon_h: horizonHours,
        connected_members: connected,
        members_total: total,
        display_string: `${connected} of ${total}`,
        particle_status_counts: statusCounts,
      };
    });
    gates[zone.zone_id] = {
      by_horizon: perHorizon,
      first_crossing_window: firstCrossingWindow,
      unavailable_reason:
        firstCrossingWindow === null ? 'no_crossing_within_horizons' : null,
    };
  }

  const first = seedResults[0]!.geometryRun;
  return {
    engine_version: ENGINE_VERSION,
    bridge_version: BRIDGE_VERSION,
    gate_bearing_deg: gateBearingDegrees(request),
    gate_width_m: request.gate.width_m,
    classification: first.classification,
    disclaimer: first.disclaimer,
    time_step_minutes: request.config.time_step_minutes,
    horizons_h: horizons,
    ensemble_size_per_seed: request.ensemble.size,
    particles,
    gates,
    diagnostics: seedResults.flatMap(({ seed, geometryRun }) =>
      geometryRun.diagnostics.map((diagnostic) => ({ seed_id: seed.seed_id, ...diagnostic })),
    ),
  };
}
