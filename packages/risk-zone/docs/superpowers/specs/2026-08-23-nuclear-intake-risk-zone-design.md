# Nuclear Intake Conditional Connectivity Region — Design

## Purpose and scope

Build a small, deterministic TypeScript domain library that estimates whether an **already observed** marine-organism cluster can connect to a nuclear-power-plant intake monitoring gate under supplied ocean-current and navigability assumptions. It is an MVP calculation engine, not a live data service or a prediction model for organism abundance.

The library will propagate a forward particle ensemble from each observation and return snapshots through 2, 4, 24, and 48 hours. It will report gate-crossing share, first-arrival ETA percentiles, and water-constrained occupied regions that a map client can render as GeoJSON.

The output must never be described as a real-world intake-blockage probability. A gate-crossing share is the fraction of this calculation's simulated particles that reached the gate under the provided seed, flow, tide-composition, and terrain assumptions. A region is a **conditional connectivity region**, not a forecast of a blockage event.

Out of scope for this MVP:

- authentication, API key storage, polling, caching, or calls to public ocean-data APIs;
- organism behavior, population growth, water-temperature suitability, windage, or wave/Stokes drift;
- a map UI, alert dispatch, intake operation state, or a blockage-risk score;
- statistical calibration of the observation confidence or simulation uncertainty.

## Chosen approach

Three implementation shapes were considered:

1. A map-specific front-end feature would entangle physics-like calculations with UI state and would be hard to validate without a map application.
2. A web API first would add deployment and data-credential concerns before there is a caller.
3. A standalone TypeScript library exposes a narrow input/output contract, lets a later map or API reuse the same deterministic engine, and can be tested with synthetic flow fields.

The third approach is selected. The repository currently contains only a README, so it establishes a minimal Node + TypeScript package and test setup without imposing an application framework.

## Public data contracts

All coordinates use GeoJSON ordering: longitude first, then latitude. All timestamps are ISO-8601 UTC strings. Horizontal velocity uses metres per second, where `u` is eastward and `v` is northward. Depth is positive metres below the surface.

### 1. Marine-organism cluster observation (`ObservationSeed`)

Required fields:

- `observedAt`: source observation time;
- `species`: user-provided species label;
- `geometry`: either one observation point or a polygon enclosing an observed cluster;
- `depthMeters`: observed depth or an explicit assumed depth;
- `confidence`: number in `[0, 1]`, retained as provenance and used only to document input confidence;
- `ensembleSize`: number of particles to initialize;
- `positionUncertaintyMeters`: non-negative spatial spread applied only to point seeds.

Point observations use a deterministic, seedable radial perturbation around the observation coordinate. Polygon observations use deterministic stratified samples inside the supplied polygon; samples outside the polygon are rejected and re-drawn from the next pseudo-random value. Every particle starts at `observedAt` and at `depthMeters`. The engine will preserve `species`, depth, confidence, and source geometry in its result metadata but will not infer organism behavior from them.

### 2. Time-varying offshore current (`FlowFieldProvider`)

The core engine depends on this mockable interface rather than a public API:

```ts
interface FlowFieldProvider {
  velocityAt(request: {
    position: Position;
    depthMeters: number;
    validAt: Date;
  }): VelocitySample | null;
}

interface VelocitySample {
  uMetersPerSecond: number;
  vMetersPerSecond: number;
  sourceTime: Date;
  validAt: Date;
}
```

`null` means that the forecast has no valid coverage for the requested location, depth, or time; it never means a zero current. A later `RomsFlowFieldProvider` can translate ROMS records containing forecast-issued time, valid time, longitude, latitude, direction/speed or `u/v` into this interface. The adapter, rather than the simulation, owns unit, coordinate, and direction-convention conversion.

For local fixtures and early testing, `GriddedFlowFieldProvider` will accept timestamped points containing `u/v` and linearly interpolate in time. Its spatial lookup will use the nearest available grid point in the MVP, with the chosen grid point recorded in diagnostics. Bilinear spatial interpolation is a later enhancement, not an implied behavior.

### 3. Nearshore tide/current correction (`NearshoreFlowPolicy`)

Nearshore tidal reversals are represented separately so the intake zone can use a better-resolved field without accidentally double-counting tide. It contains a geographic polygon, a `FlowFieldProvider`, and one of two explicitly named policies:

- `replace`: inside the polygon, use the nearshore provider instead of the offshore provider;
- `residualAdd`: add the nearshore velocity only when the adapter documents it as a residual not already included in the offshore field.

The default is no correction. There is no implicit sum of ROMS and numerical-tide data. A later numerical-tide adapter maps its valid-time direction/speed and tide-reversal data into the provider; a reversal is expressed by its resulting velocity, not by a second special movement rule.

### 4. Bathymetry and coastline (`NavigabilityProvider`)

The simulation asks a mockable provider whether a segment can be traversed:

```ts
interface NavigabilityProvider {
  canTraverse(request: {
    from: Position;
    to: Position;
    particleDepthMeters: number;
    at: Date;
  }): TraversalResult;
}

interface TraversalResult {
  passable: boolean;
  reason?: 'land' | 'shallow-water' | 'outside-coverage';
}
```

`CoastAndBathymetryProvider` will combine a supplied land GeoJSON polygon/multipolygon with sampled bathymetry. A segment is passable only if neither endpoint nor the segment crosses land and all bathymetry samples meet `minimumWaterDepthMeters`. The sample spacing is configured in metres. This avoids a particle passing through a narrow peninsula between time steps. An unavailable bathymetry sample returns `outside-coverage`, not a permissive result.

### 5. Virtual monitoring gate (`MonitoringGate`)

The gate is a finite line segment in a local geographic plane, described by either two endpoints or a centre, width, and bearing. It also declares an inclusive `minDepthMeters` / `maxDepthMeters` interval. The engine records a gate arrival when a live particle's water-passable movement segment intersects the gate segment and its depth is in that interval. A particle can contribute only its first arrival time to ETA statistics.

The gate is a monitoring boundary supplied by the team; its crossing does not assert that the particle reached a real intake or caused an operational impact.

## Calculation pipeline

1. Validate every input, including valid polygon shape, non-empty horizons, positive ensemble size and time step, non-negative spatial uncertainty, supported flow policy, increasing depth range, and UTC-parseable timestamps.
2. Materialize deterministic particles from the observation geometry with a caller-provided random seed. Give each a stable ID, source position, depth, status `active`, and a first-arrival time of `null`.
3. For every `timeStepMinutes` interval through the largest requested horizon, get the effective velocity: offshore velocity outside a correction zone, or the configured nearshore policy inside it.
4. Advance the active particle by a midpoint (RK2) step in a local equirectangular metre projection centered on the seed. This uses velocity at the current point to form a midpoint, then velocity at that midpoint to form the actual move. Convert the result back to longitude/latitude. The default time step is 15 minutes; it must evenly divide each requested horizon.
5. Call `canTraverse` on the full movement segment before accepting it. On a non-passable result, mark the particle terminal as `blocked-land`, `blocked-shallow-water`, or `outside-navigability-coverage`; do not slide it along the obstacle or allow a later gate crossing.
6. For each accepted movement segment, check the monitoring-gate intersection and depth interval. Record only the first crossing. A particle remains eligible to be included in later occupied-region snapshots after it crosses, so the result distinguishes passage through a monitoring boundary from removal from the sea.
7. At every configured snapshot interval and every requested horizon, turn positions of active or gate-reached particles into a water-constrained grid. Occupied cells use a configurable cell size (default 1 km), and 8-neighbor contiguous cells form one `ConnectivityRegion`. Convert each grouped cell boundary to a GeoJSON polygon or multipolygon. Terminal blocked and missing-flow particles are excluded.
8. At 2, 4, 24, and 48 hours, calculate gate share and ETA metrics. `conditionalGateConnectionFraction` is `firstGateCrossingsByHorizon / ensembleSize`. From first-arrival times no later than the horizon, calculate nearest-rank p10, p50, and p90 in elapsed minutes. When there are no arrivals, all three ETA values are `null`.

The implementation will make the requested horizons configurable but default to `[2, 4, 24, 48]` hours. Snapshot intervals default to one hour and are inserted exactly at a horizon even if a caller's interval would otherwise omit it.

## Results and provenance

`simulateConditionalConnectivity` returns a serializable `SimulationResult`:

```ts
interface SimulationResult {
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
  horizonSummaries: Array<{
    horizonHours: number;
    conditionalGateConnectionFraction: number;
    firstGateCrossingCount: number;
    etaMinutes: { p10: number | null; p50: number | null; p90: number | null };
    particleStatusCounts: Record<ParticleStatus, number>;
  }>;
  snapshots: Array<{
    validAt: string;
    regions: GeoJSON.FeatureCollection<GeoJSON.MultiPolygon>;
    representedParticleCount: number;
  }>;
  particleTrajectories: Array<{
    id: string;
    status: ParticleStatus;
    firstGateArrivalAt: string | null;
    coordinates: Position[];
  }>;
  diagnostics: SimulationDiagnostic[];
}
```

The mandatory disclaimer will state: “This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.” UI and API callers can use the `classification` field to display this distinction reliably.

Diagnostics include flow-coverage misses, navigability rejections by reason, any horizon reached with no live particles, and the selected current policy. Missing data is visible to callers rather than converted to a false safe/unsafe result.

## Module layout

```text
src/
  index.ts                         public exports
  risk-zone/
    types.ts                       input, provider, and result contracts
    validation.ts                  input validation and domain errors
    geo.ts                         local projection, point-in-polygon, intersections
    flow-field.ts                  grid fixture provider and nearshore composition
    seed.ts                        deterministic point/polygon ensemble sampling
    navigability.ts                coastline and bathymetry provider
    regions.ts                     occupied-grid clustering and GeoJSON conversion
    simulation.ts                  forward RK2 propagation and summaries
test/
  risk-zone/*.test.ts              synthetic end-to-end and component tests
examples/
  conditional-connectivity.ts      executable mocked-data example
```

`types.ts` is the integration boundary for later data acquisition. No data-source credentials or HTTP dependencies appear in the engine. An application can call external APIs, map their raw responses into `FlowFieldProvider` / `NavigabilityProvider`, then invoke the pure simulation function.

## Failure behavior

- Invalid inputs throw a structured `RiskZoneValidationError` naming the offending field.
- No applicable flow sample terminally marks that particle as `outside-flow-coverage`; it does not fabricate movement.
- Non-passable terrain terminally marks the particle and carries its final coordinate for traceability.
- A non-intersecting gate is valid and returns zero connection fraction with null ETA percentiles.
- Invalid or unavailable navigation coverage is not interpreted as open water.
- The engine has no network side effects and does not silently fetch data.

## Test strategy and acceptance criteria

Tests will use small, fixed synthetic fields and a seeded ensemble, never an external ocean API.

1. A constant eastward flow advances a point seed by the expected local-plane distance at each requested horizon.
2. A segment crossing a gate produces the correct first crossing count, connection fraction, and first-arrival ETA.
3. Multiple controlled particle arrival times produce deterministic nearest-rank p10, p50, and p90 ETA values.
4. A land crossing and a shallow-water crossing stop a particle, exclude it from later regions, and are counted with distinct terminal statuses.
5. A missing flow sample ends a particle with `outside-flow-coverage` rather than zeroing its velocity.
6. A nearshore `replace` policy changes velocity inside its zone, while an absent policy leaves the offshore field unchanged. `residualAdd` is exercised only with an explicitly residual fixture.
7. A point seed and a polygon seed produce the requested count of reproducible in-boundary particles for the same random seed.
8. A region snapshot contains only occupied passable cells, splits disconnected cell groups, and uses `MultiPolygon` GeoJSON output.
9. Every result includes the conditional-connectivity classification and disclaimer verbatim.

The README will include package setup, a mock-provider example, a table mapping the five required real-data sources to input fields, and the explicit data-adapter boundary for later ROMS, tidal-current, bathymetry, coastline, and observation integrations.
