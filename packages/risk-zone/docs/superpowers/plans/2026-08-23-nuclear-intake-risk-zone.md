# Nuclear Intake Conditional Connectivity Region Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build a deterministic TypeScript engine that computes water-constrained, conditional particle-connectivity regions and intake-monitoring-gate arrival summaries for observed marine-organism clusters.

**Architecture:** A public simulation accepts a cluster seed, mockable offshore and nearshore flow providers, a mockable navigability provider, and a virtual monitoring gate. Focused modules materialize particles, select and integrate current vectors, reject non-navigable motion, form occupied-grid GeoJSON regions, and summarize first gate arrivals. The engine has no HTTP or API-key behavior; source-specific adapters map external data into its provider interfaces.

**Tech Stack:** Node.js 24+, TypeScript 5.9, Vitest 3, ESM, GeoJSON type declarations.

**Spec:** docs/superpowers/specs/2026-08-23-nuclear-intake-risk-zone-design.md

## Global Constraints

- Coordinates are [longitude, latitude]; timestamps are ISO-8601 UTC strings; horizontal velocity is eastward/northward metres per second; depth is positive downwards in metres.
- The default horizons are exactly [2, 4, 24, 48] hours, but callers may configure a strictly increasing positive list.
- A result always sets classification to conditional-connectivity-not-blockage-probability and contains the exact disclaimer from the spec.
- conditionalGateConnectionFraction is a simulated first-gate-arrival share, never a blockage probability, organism-abundance estimate, or facility-risk score.
- FlowFieldProvider and NavigabilityProvider are synchronous, deterministic, and mockable; production simulation code must not call a network service.
- NearshoreFlowPolicy has no implicit current summation. residualAdd is legal only with isResidual: true; replace is the default safe composition choice.
- An invalid input throws RiskZoneValidationError; unavailable flow or navigation coverage terminates that particle and must be observable in diagnostics.
- Each behavior is developed test first: add a focused failing Vitest assertion, run it, write the minimum implementation, and rerun the focused test before progressing.

---

## File structure

~~~
package.json                                package scripts and development dependencies
tsconfig.json                               strict ESM compiler configuration
src/index.ts                                supported public exports
src/risk-zone/types.ts                      all public contracts and constants
src/risk-zone/validation.ts                 input validation and domain error class
src/risk-zone/geo.ts                        local-metre projection and geometry predicates
src/risk-zone/flow-field.ts                 grid fixture provider and nearshore composition
src/risk-zone/seed.ts                       deterministic point/polygon particle sampling
src/risk-zone/navigability.ts               coast/bathymetry traversal provider
src/risk-zone/regions.ts                    occupied cell grouping and GeoJSON conversion
src/risk-zone/simulation.ts                 RK2 propagation, gate arrivals, and summaries
test/risk-zone/*.test.ts                    isolated module and end-to-end tests
examples/conditional-connectivity.ts        executable mocked-data example
README.md                                   installation, data mapping, and safety wording
~~~

## Task 1: Create TypeScript test harness, contracts, and validation

**Files:**
- Create: package.json
- Create: tsconfig.json
- Create: src/index.ts
- Create: src/risk-zone/types.ts
- Create: src/risk-zone/validation.ts
- Create: test/risk-zone/fixtures.ts
- Test: test/risk-zone/validation.test.ts

**Interfaces:**
- Produces Position, ObservationSeed, FlowFieldProvider, NavigabilityProvider, MonitoringGate, SimulationInput, SimulationResult, ParticleStatus, and CONDITIONAL_CONNECTIVITY_DISCLAIMER.
- Produces RiskZoneValidationError with field: string and validateSimulationInput(input: SimulationInput): RequiredSimulationConfig.
- Reserves simulateConditionalConnectivity(input: SimulationInput): SimulationResult for Task 6.

- [ ] **Step 1: Add the smallest runnable project configuration**

Create package.json with ESM mode, scripts build: tsc -p tsconfig.json, test: vitest run, test:watch: vitest, and example: tsx examples/conditional-connectivity.ts. Add typescript, vitest, tsx, @types/node, and @types/geojson as development dependencies. Create strict tsconfig.json with target and module set to ES2022, moduleResolution set to Bundler, noEmit true, and include values src, test, examples. Run npm install to create package-lock.json.

- [ ] **Step 2: Create shared test fixtures with exact public shapes**

Create test/risk-zone/fixtures.ts after types.ts exists. It exports makeInput, pointSeed, polygonSeed, endpointsGate, constantFlow, openWater, landOnFirstStep, noCoverage, sample, requestAt, and atZero. Its implementation uses only the public contracts:

~~~ts
export const atZero = new Date('2026-01-01T00:00:00Z');
export const pointSeed = (patch = {}): ObservationSeed => ({
  observedAt: atZero.toISOString(), species: 'jellyfish',
  geometry: { kind: 'point', position: [129, 37] },
  depthMeters: 1, confidence: 0.8, ensembleSize: 1,
  positionUncertaintyMeters: 0, ...patch,
});
export const constantFlow = (u = 1, v = 0): FlowFieldProvider => ({
  velocityAt: ({ validAt }) => ({
    uMetersPerSecond: u, vMetersPerSecond: v,
    sourceTime: atZero, validAt,
  }),
});
export const openWater: NavigabilityProvider = {
  canTraverse: () => ({ passable: true }),
};
export const noCoverage: FlowFieldProvider = { velocityAt: () => null };
export const makeInput = (patch: Partial<SimulationInput> = {}): SimulationInput => ({
  seed: pointSeed(), offshoreFlow: constantFlow(), navigability: openWater,
  gate: endpointsGate(), config: { horizonsHours: [2], timeStepMinutes: 15,
    snapshotIntervalMinutes: 60, regionCellSizeMeters: 1_000, randomSeed: 1 },
  ...patch,
});
~~~

polygonSeed returns a closed 0.02 degree square around [129, 37] and spreads its patch after the default geometry. endpointsGate returns an endpoint-form MonitoringGate whose default is a vertical segment far east of the seed and depth range [0, 10]. landOnFirstStep is a NavigabilityProvider returning passable false with reason land. sample creates a GriddedFlowSample; requestAt creates a VelocityRequest at [129, 37], depth 1, and its supplied valid time. The fixture also exports verticalGateAtEastwardDistance(distanceMeters), implemented by createLocalProjection([129, 37]).toGeographic([distanceMeters, -500]) and [distanceMeters, 500].

- [ ] **Step 3: Write failing contract and validation tests**

~~~ts
import { describe, expect, it } from 'vitest';
import {
  CONDITIONAL_CONNECTIVITY_DISCLAIMER,
  validateSimulationInput,
} from '../../src/index.js';

describe('risk-zone input contract', () => {
  it('exports the explicit non-blockage disclaimer', () => {
    expect(CONDITIONAL_CONNECTIVITY_DISCLAIMER).toContain('not an estimate of organism abundance');
    expect(CONDITIONAL_CONNECTIVITY_DISCLAIMER).toContain('intake blockage probability');
  });

  it('rejects a horizon that is not divisible by the time step', () => {
    expect(() => validateSimulationInput(makeInput({
      config: { horizonsHours: [2], timeStepMinutes: 17 },
    }))).toThrow(/config.timeStepMinutes/);
  });
});
~~~

Add focused assertions for confidence outside [0, 1], zero ensemble size, malformed UTC time, unclosed polygon, reversed gate depth range, a snapshot interval that does not divide the step, and residualAdd without isResidual: true.

- [ ] **Step 4: Run the test to confirm the public symbols are absent**

Run: npm test -- test/risk-zone/validation.test.ts

Expected: the runner reports that the imported symbols do not exist.

- [ ] **Step 5: Implement public contracts, default configuration, and validation**

~~~ts
export const CONDITIONAL_CONNECTIVITY_DISCLAIMER =
  'This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.';

export type Position = readonly [longitude: number, latitude: number];
export type ParticleStatus =
  | 'active'
  | 'gate-reached'
  | 'blocked-land'
  | 'blocked-shallow-water'
  | 'outside-navigability-coverage'
  | 'outside-flow-coverage';

export class RiskZoneValidationError extends Error {
  constructor(public readonly field: string, message: string) {
    super(message);
    this.name = 'RiskZoneValidationError';
  }
}
~~~

Define point and polygon observation geometries, velocity requests, nearshore policies, traversal results, gates, diagnostics, particle trajectories, snapshots, summaries, and result types. validateSimulationInput must return immutable defaults of horizonsHours [2, 4, 24, 48], timeStepMinutes 15, snapshotIntervalMinutes 60, regionCellSizeMeters 1000, and randomSeed 1. Parse every timestamp using Date and reject an invalid date. Validate finite coordinate bounds and every test condition from Step 2 without mutating the input.

- [ ] **Step 6: Run focused tests and the type checker**

Run: npm test -- test/risk-zone/validation.test.ts && npm run build

Expected: all validation assertions pass and TypeScript reports zero errors.

- [ ] **Step 7: Commit the harness and contracts**

~~~bash
git add package.json package-lock.json tsconfig.json src/index.ts src/risk-zone/types.ts src/risk-zone/validation.ts test/risk-zone/fixtures.ts test/risk-zone/validation.test.ts
git commit -m "feat: define risk zone simulation contracts"
~~~

## Task 2: Implement geographic primitives and current-field selection

**Files:**
- Create: src/risk-zone/geo.ts
- Create: src/risk-zone/flow-field.ts
- Test: test/risk-zone/geo.test.ts
- Test: test/risk-zone/flow-field.test.ts

**Interfaces:**
- Consumes Position, VelocitySample, FlowFieldProvider, and NearshoreFlowPolicy.
- Produces createLocalProjection(anchor: Position), pointInPolygon, segmentsIntersect, GriddedFlowFieldProvider, and effectiveVelocityAt.

- [ ] **Step 1: Write failing geographic tests**

~~~ts
it('round-trips its local metre anchor', () => {
  const projection = createLocalProjection([129, 37]);
  expect(projection.toGeographic(projection.toLocal([129, 37]))).toEqual([129, 37]);
});

it('detects a movement segment crossing a gate', () => {
  expect(segmentsIntersect([0, 0], [10, 0], [5, -5], [5, 5])).toBe(true);
});
~~~

Add a point-inside-polygon assertion and non-intersecting collinear segment assertion.

- [ ] **Step 2: Run the geographic suite**

Run: npm test -- test/risk-zone/geo.test.ts

Expected: import failure naming the absent geographic exports.

- [ ] **Step 3: Implement the local projection and robust predicates**

Use Earth radius 6_371_000 metres. createLocalProjection uses an equirectangular projection centered at the anchor. pointInPolygon uses ray casting and regards a boundary point as inside. segmentsIntersect uses orientation tests plus on-segment checks. Functions have no I/O behavior.

- [ ] **Step 4: Run the geographic suite**

Run: npm test -- test/risk-zone/geo.test.ts

Expected: every geographic assertion passes.

- [ ] **Step 5: Write failing flow-field and nearshore-policy tests**

~~~ts
it('interpolates a gridded current in time at the nearest point', () => {
  const field = new GriddedFlowFieldProvider([
    sample('2026-01-01T00:00:00Z', [129, 37], 0, 0),
    sample('2026-01-01T01:00:00Z', [129, 37], 2, 4),
  ]);
  expect(field.velocityAt(requestAt('2026-01-01T00:30:00Z'))).toMatchObject({
    uMetersPerSecond: 1,
    vMetersPerSecond: 2,
  });
});

it('replaces offshore velocity inside a nearshore zone', () => {
  expect(effectiveVelocityAt(request, offshore, replacePolicy))
    .toMatchObject({ uMetersPerSecond: -1 });
});
~~~

Add assertions that a missing bracketing record returns null, a point outside the correction polygon uses offshore flow, and residualAdd works only with an isResidual: true fixture.

- [ ] **Step 6: Run the flow suite**

Run: npm test -- test/risk-zone/flow-field.test.ts

Expected: import failure naming GriddedFlowFieldProvider or effectiveVelocityAt.

- [ ] **Step 7: Implement grid lookup and explicit current composition**

GriddedFlowFieldProvider selects the nearest spatial point at or before and at or after the requested time, requires the same depth layer, and linearly interpolates u/v. effectiveVelocityAt returns offshore flow outside a correction polygon; inside it replaces or adds exactly according to the policy. When an essential sample is unavailable, return null instead of a synthetic vector.

- [ ] **Step 8: Verify both suites and commit**

Run: npm test -- test/risk-zone/geo.test.ts test/risk-zone/flow-field.test.ts && npm run build

Expected: both suites pass and strict TypeScript has zero errors.

~~~bash
git add src/risk-zone/geo.ts src/risk-zone/flow-field.ts test/risk-zone/geo.test.ts test/risk-zone/flow-field.test.ts
git commit -m "feat: add flow field and geographic primitives"
~~~

## Task 3: Materialize particles and enforce water constraints

**Files:**
- Create: src/risk-zone/seed.ts
- Create: src/risk-zone/navigability.ts
- Test: test/risk-zone/seed.test.ts
- Test: test/risk-zone/navigability.test.ts

**Interfaces:**
- Consumes ObservationSeed, Position, NavigabilityProvider, TraversalResult, and geo predicates.
- Produces materializeParticles(seed: ObservationSeed, randomSeed: number): MutableParticle[], CoastAndBathymetryProvider, and BathymetrySampler.

- [ ] **Step 1: Write failing deterministic-seed tests**

~~~ts
it('creates reproducible point particles from a fixed random seed', () => {
  const first = materializeParticles(pointSeed({ ensembleSize: 3, positionUncertaintyMeters: 40 }), 42);
  const second = materializeParticles(pointSeed({ ensembleSize: 3, positionUncertaintyMeters: 40 }), 42);
  expect(first).toEqual(second);
});

it('keeps polygon starts within the observed ring', () => {
  const seed = polygonSeed({ ensembleSize: 20 });
  const particles = materializeParticles(seed, 42);
  expect(particles.every((particle) => pointInPolygon(particle.coordinates[0], seed.geometry.rings))).toBe(true);
});
~~~

- [ ] **Step 2: Run the seed suite**

Run: npm test -- test/risk-zone/seed.test.ts

Expected: import failure naming materializeParticles.

- [ ] **Step 3: Implement deterministic point and polygon sampling**

Use a local mulberry32 generator. A point seed uses sqrt(random) radial sampling inside positionUncertaintyMeters; a zero-radius seed duplicates the source coordinate. A polygon seed samples its bounding box, accepts only exterior points outside holes, and raises RiskZoneValidationError for seed.geometry if it cannot produce ensembleSize particles within ensembleSize * 100 candidates. Name particles particle-1 through particle-n; set coordinates to one source point, status active, and firstGateArrivalAt null.

- [ ] **Step 4: Run the seed suite**

Run: npm test -- test/risk-zone/seed.test.ts

Expected: reproducible, in-boundary particles with stable identifiers.

- [ ] **Step 5: Write failing navigability tests**

~~~ts
it('rejects a segment that crosses land', () => {
  expect(provider.canTraverse({ from: [0, 0], to: [2, 0], particleDepthMeters: 1, at: atZero }))
    .toEqual({ passable: false, reason: 'land' });
});

it('rejects bathymetry shallower than the configured minimum', () => {
  expect(shallowProvider.canTraverse(request))
    .toEqual({ passable: false, reason: 'shallow-water' });
});
~~~

Add checks for null bathymetry yielding outside-coverage and a fully open segment yielding passable: true.

- [ ] **Step 6: Run the navigability suite**

Run: npm test -- test/risk-zone/navigability.test.ts

Expected: import failure naming CoastAndBathymetryProvider.

- [ ] **Step 7: Implement segment sampling and terrain rejection**

Define BathymetrySampler as depthAt(position: Position, at: Date): number | null. CoastAndBathymetryProvider accepts land rings, a sampler, minimumWaterDepthMeters, and sampleSpacingMeters. Interpolate samples along the full local-metre segment; reject land first, null depth as outside coverage, and lower-than-minimum depth as shallow water.

- [ ] **Step 8: Verify constraint suites and commit**

Run: npm test -- test/risk-zone/seed.test.ts test/risk-zone/navigability.test.ts && npm run build

Expected: all tests pass and TypeScript has zero errors.

~~~bash
git add src/risk-zone/seed.ts src/risk-zone/navigability.ts test/risk-zone/seed.test.ts test/risk-zone/navigability.test.ts
git commit -m "feat: add seed sampling and water constraints"
~~~

## Task 4: Build time-stamped GeoJSON conditional connectivity regions

**Files:**
- Create: src/risk-zone/regions.ts
- Test: test/risk-zone/regions.test.ts

**Interfaces:**
- Consumes live particle positions, Position, and createLocalProjection.
- Produces buildConnectivityRegions(positions: Position[], anchor: Position, cellSizeMeters: number): GeoJSON.FeatureCollection<GeoJSON.MultiPolygon>.

- [ ] **Step 1: Write failing region tests**

~~~ts
it('groups eight-neighbor occupied cells into one multipolygon feature', () => {
  const regions = buildConnectivityRegions([[129, 37], [129.005, 37.005]], [129, 37], 1_000);
  expect(regions.features).toHaveLength(1);
  expect(regions.features[0].geometry.type).toBe('MultiPolygon');
});

it('splits separated occupied cells into different features', () => {
  const regions = buildConnectivityRegions([[129, 37], [129.05, 37.05]], [129, 37], 1_000);
  expect(regions.features).toHaveLength(2);
});
~~~

Add assertions that no positions returns an empty feature collection and repeated positions create only one occupied cell.

- [ ] **Step 2: Run region tests**

Run: npm test -- test/risk-zone/regions.test.ts

Expected: import failure naming buildConnectivityRegions.

- [ ] **Step 3: Implement occupied-cell clustering and GeoJSON output**

Project positions to local metres and key each cell with floor(x / cellSizeMeters):floor(y / cellSizeMeters). Breadth-first search all eight neighbor offsets. Build each cell boundary as a closed geographic ring. Emit every connected component as one MultiPolygon feature containing one polygon per cell, with properties occupiedCellCount and representedParticleCount. Do not merge cell boundaries.

- [ ] **Step 4: Verify and commit**

Run: npm test -- test/risk-zone/regions.test.ts && npm run build

Expected: all region tests pass and TypeScript has zero errors.

~~~bash
git add src/risk-zone/regions.ts test/risk-zone/regions.test.ts
git commit -m "feat: build conditional connectivity regions"
~~~

## Task 5: Integrate forward motion, gate arrivals, ETA, and diagnostics

**Files:**
- Create: src/risk-zone/simulation.ts
- Modify: src/index.ts
- Test: test/risk-zone/simulation.test.ts

**Interfaces:**
- Consumes validateSimulationInput, materializeParticles, effectiveVelocityAt, createLocalProjection, segmentsIntersect, and buildConnectivityRegions.
- Produces simulateConditionalConnectivity(input: SimulationInput): SimulationResult and nearestRankPercentile(values: number[], percentile: 10 | 50 | 90): number | null.

- [ ] **Step 1: Write a failing forward-propagation test**

~~~ts
it('moves a point particle east and returns the default horizon summaries', () => {
  const result = simulateConditionalConnectivity(makeInput({
    seed: pointSeed({ ensembleSize: 1, positionUncertaintyMeters: 0 }),
    offshoreFlow: constantFlow(1, 0),
    navigability: openWater,
    gate: distantGate,
  }));

  expect(result.horizonSummaries.map((summary) => summary.horizonHours)).toEqual([2, 4, 24, 48]);
  expect(result.particleTrajectories[0].coordinates.at(-1)![0]).toBeGreaterThan(seedLongitude);
  expect(result.classification).toBe('conditional-connectivity-not-blockage-probability');
});
~~~

- [ ] **Step 2: Run the propagation test**

Run: npm test -- test/risk-zone/simulation.test.ts

Expected: import failure naming simulateConditionalConnectivity.

- [ ] **Step 3: Implement the RK2 forward loop and snapshots**

For each exact time step through the largest horizon, resolve effective velocity at the particle location, form a midpoint, resolve midpoint velocity, and advance by the midpoint vector. A null current changes status to outside-flow-coverage and appends a flow-coverage-miss diagnostic. A failed traversal changes status to the matching blocked status and appends a navigability-rejection diagnostic. Continue active and gate-reached particles. Insert a snapshot at every snapshot interval and every requested horizon with buildConnectivityRegions.

- [ ] **Step 4: Run the propagation test**

Run: npm test -- test/risk-zone/simulation.test.ts

Expected: the constant-flow test passes and contains every default-horizon snapshot.

- [ ] **Step 5: Write failing gate and ETA tests**

~~~ts
it('counts a first gate crossing and reports its ETA', () => {
  const result = simulateConditionalConnectivity(makeInput({
    gate: verticalGateAtEastwardDistance(3_600),
  }));
  const twoHour = result.horizonSummaries.find((summary) => summary.horizonHours === 2)!;
  expect(twoHour.conditionalGateConnectionFraction).toBe(1);
  expect(twoHour.etaMinutes).toEqual({ p10: 60, p50: 60, p90: 60 });
});

it('returns null ETA values when no particle reaches the gate', () => {
  expect(noArrivalSummary.etaMinutes).toEqual({ p10: null, p50: null, p90: null });
});
~~~

Add a three-particle fixture proving nearest-rank percentiles of [10, 40, 100] are 10, 40, and 100 for p10, p50, and p90. Add a depth-range mismatch test.

- [ ] **Step 6: Run gate and ETA tests**

Run: npm test -- test/risk-zone/simulation.test.ts

Expected: gate-share or ETA assertions fail before first-arrival logic exists.

- [ ] **Step 7: Implement first-arrival summaries**

For every accepted movement segment, normalize the gate to endpoints, call segmentsIntersect, and compare constant particle depth to the inclusive gate range. Set firstGateArrivalAt once, set status gate-reached, and retain movement. For each horizon, include first arrivals at or before that horizon; calculate share as arrivalCount divided by ensembleSize; calculate nearest rank with ceil((percentile / 100) * sorted.length) - 1; return null values for an empty list. Status counts are evaluated at the horizon.

- [ ] **Step 8: Write failing terminal-state and disclaimer tests**

~~~ts
it('excludes a land-blocked particle from later regions', () => {
  const result = simulateConditionalConnectivity(makeInput({ navigability: landAfterFirstStep }));
  expect(result.particleTrajectories[0].status).toBe('blocked-land');
  expect(result.snapshots.at(-1)!.representedParticleCount).toBe(0);
});

it('records missing flow coverage instead of assuming still water', () => {
  const result = simulateConditionalConnectivity(makeInput({ offshoreFlow: noCoverage }));
  expect(result.particleTrajectories[0].status).toBe('outside-flow-coverage');
  expect(result.diagnostics.some((entry) => entry.code === 'flow-coverage-miss')).toBe(true);
  expect(result.disclaimer).toBe(CONDITIONAL_CONNECTIVITY_DISCLAIMER);
});
~~~

- [ ] **Step 9: Run the terminal-state tests and add diagnostics**

Run: npm test -- test/risk-zone/simulation.test.ts

Expected before the terminal-state implementation: at least one terrain or missing-coverage assertion fails. Preserve a terminal particle's last coordinate, exclude terminal particles from subsequent regions, and emit diagnostics containing particleId, validAt, and code. Re-run until all simulation assertions pass.

- [ ] **Step 10: Verify complete engine behavior and commit**

Run: npm test && npm run build

Expected: every risk-zone suite passes and TypeScript reports zero errors.

~~~bash
git add src/index.ts src/risk-zone/simulation.ts test/risk-zone/simulation.test.ts
git commit -m "feat: simulate conditional intake connectivity"
~~~

## Task 6: Document the five external data contracts and provide a mock example

**Files:**
- Create: examples/conditional-connectivity.ts
- Modify: README.md
- Modify: src/index.ts
- Test: test/risk-zone/simulation.test.ts

**Interfaces:**
- Consumes only public root exports.
- Produces a serialized SimulationResult example and usage documentation for later source adapters.

- [ ] **Step 1: Write a failing package-root usage test**

~~~ts
it('exposes the simulation API and disclaimer at the package root', async () => {
  const api = await import('../../src/index.js');
  expect(typeof api.simulateConditionalConnectivity).toBe('function');
  expect(api.CONDITIONAL_CONNECTIVITY_DISCLAIMER).toContain('not an estimate');
});
~~~

- [ ] **Step 2: Run the public-export test**

Run: npm test -- test/risk-zone/simulation.test.ts

Expected: a package-root assertion fails until the public exports are complete.

- [ ] **Step 3: Write a mocked example and README instructions**

The example creates a point observation, constant FlowFieldProvider, open-water NavigabilityProvider, endpoint gate, then logs simulateConditionalConnectivity output. The README includes npm install, npm test, npm run build, npm run example, and a five-row mapping table:

| Required source data | Engine contract |
| --- | --- |
| Observation time, point/polygon, species, depth, confidence | ObservationSeed |
| Forecast issue time, valid time, longitude/latitude, u/v or direction/speed | FlowFieldProvider |
| Nearshore velocity and tide reversals | NearshoreFlowPolicy |
| Water depth and land boundary | NavigabilityProvider |
| Team-defined line, width/orientation, depth range | MonitoringGate |

Also state that current providers are never implicitly summed; residualAdd requires an explicitly residual field; the library performs no network fetch; and the mandatory result disclaimer is not optional.

- [ ] **Step 4: Add root exports and run user-facing verification**

Run: npm run example && npm test && npm run build

Expected: the example prints a SimulationResult whose classification is conditional-connectivity-not-blockage-probability; the full suite passes; the type checker has zero errors.

- [ ] **Step 5: Commit documentation and example**

~~~bash
git add README.md examples/conditional-connectivity.ts src/index.ts test/risk-zone/simulation.test.ts
git commit -m "docs: explain conditional connectivity data adapters"
~~~

## Plan self-review

- Spec coverage: Tasks 1 through 5 implement validated inputs, all five data boundaries, deterministic ensemble movement, nearshore-current rules, coastline/bathymetry rejection, monitoring-gate outcomes, ETA p10/p50/p90, timestamped GeoJSON regions, diagnostics, and the mandatory conditional-connectivity language. Task 6 documents the integration boundary and creates a runnable mock.
- Type consistency: SimulationInput, SimulationResult, FlowFieldProvider, NavigabilityProvider, MonitoringGate, ParticleStatus, and simulateConditionalConnectivity keep the exact names established in Task 1 throughout the plan.
- Scope: This plan deliberately excludes live API calls, a UI, weather and biological behavior, facility-state scoring, and operational alerts as stated in the approved spec.
