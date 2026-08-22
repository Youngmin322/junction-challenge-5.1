import { describe, expect, it } from 'vitest';
import { BRIDGE_VERSION, gateBearingDegrees, runBridge, type BridgeRequest } from '../../src/bridge/cli.js';

function request(overrides: Partial<BridgeRequest> = {}): BridgeRequest {
  return {
    request_version: BRIDGE_VERSION,
    seeds: [
      {
        seed_id: 'SEED-HANUL-DEMO-001',
        lon: 129.46,
        lat: 37.1,
        reference_time: '2026-08-23T00:00:00Z',
      },
    ],
    field: {
      profile_id: 'B2_current_only',
      u_ms: -0.12,
      v_ms: 0.04,
      issued_at: '2026-08-23T00:00:00Z',
      valid_at: '2026-08-23T00:00:00Z',
    },
    horizons_h: [3, 6, 12],
    domain: {
      domain_id: 'SYNTH_DOMAIN_HANUL_v1',
      lon_min: 129.36,
      lon_max: 129.48,
      lat_min: 36.99,
      lat_max: 37.14,
      spacing_deg: 0.01,
    },
    zones: [{ zone_id: 'DEMO_GATE_DEOKCHEON_v1', lon: 129.40416, lat: 37.1 }],
    ensemble: {
      size: 25,
      position_uncertainty_m: 500,
      depth_m: 1,
      confidence: 0.8,
      species: 'jellyfish',
    },
    navigability: {
      mode: 'synthetic_flat',
      flat_depth_m: 30,
      minimum_water_depth_m: 2,
      lookup_radius_m: 800,
      land_polygons: [],
    },
    gate: { width_m: 4000, bearing_deg: null, min_depth_m: 0, max_depth_m: 5 },
    config: {
      time_step_minutes: 15,
      snapshot_interval_minutes: 60,
      region_cell_size_m: 1000,
      random_seed: 12345,
    },
    ...overrides,
  };
}

describe('gateBearingDegrees', () => {
  it('lays the gate across the field instead of along it', () => {
    // The field travels at 288.43 degrees, so an intercepting gate sits at 18.43.
    expect(gateBearingDegrees(request())).toBeCloseTo(18.43, 2);
  });

  it('keeps an explicit bearing when one is supplied', () => {
    expect(gateBearingDegrees(request({ gate: { width_m: 4000, bearing_deg: 90, min_depth_m: 0, max_depth_m: 5 } }))).toBe(90);
  });

  it('falls back to north for a still field', () => {
    const still = request();
    expect(gateBearingDegrees({ ...still, field: { ...still.field, u_ms: 0, v_ms: 0 } })).toBe(0);
  });
});

describe('runBridge', () => {
  it('returns one trajectory per ensemble member', () => {
    const result = runBridge(request()) as Record<string, any>;
    expect(result.particles).toHaveLength(25);
    // 12 hours at a 15 minute step, plus the release position.
    expect(result.particles[0].coordinates).toHaveLength(49);
    expect(result.engine_version).toBe('risk-zone-connectivity-v1');
  });

  it('reports gate crossings as counts and a horizon bracket', () => {
    const result = runBridge(request()) as Record<string, any>;
    const gate = result.gates.DEMO_GATE_DEOKCHEON_v1;
    const twelveHour = gate.by_horizon.find((item: any) => item.horizon_h === 12);
    expect(twelveHour.connected_members).toBeGreaterThan(0);
    expect(twelveHour.display_string).toBe(`${twelveHour.connected_members} of 25`);
    expect(gate.first_crossing_window.basis).toBe('requested_horizon_bracket');
  });

  it('never reports an eta', () => {
    const serialized = JSON.stringify(runBridge(request()));
    expect(serialized).not.toContain('eta');
  });

  it('is deterministic for the same random seed', () => {
    expect(JSON.stringify(runBridge(request()))).toBe(JSON.stringify(runBridge(request())));
  });

  it('rejects an unknown request version', () => {
    expect(() => runBridge(request({ request_version: 'v0' }))).toThrow(/unsupported request_version/);
  });

  it('rejects an empty gate list', () => {
    expect(() => runBridge(request({ zones: [] }))).toThrow(/zones must not be empty/);
  });
});
