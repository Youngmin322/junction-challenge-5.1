# Conditional Connectivity Scenario Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a MapLibre demonstration that renders synthetic conditional-connectivity travel cells as mutually exclusive 2/4/24/48-hour earliest-arrival bands while preserving direct replacement with real-data-backed engine inputs.

**Architecture:** Add a pure earliest-arrival GeoJSON post-processor to the existing engine, then build a Vite map application that consumes `SimulationResult`. Synthetic `FlowFieldProvider` and `NavigabilityProvider` implementations live only in the demo; a future real adapter retains the same input and GeoJSON contracts.

**Tech Stack:** Node.js 24+, TypeScript, Vitest, Vite, MapLibre GL JS, GeoJSON.

**Spec:** `docs/superpowers/specs/2026-08-23-scenario-map-design.md`

## Global Constraints

- Preserve and do not stage the existing uncommitted README, example, public-data adapter, and public-data test changes.
- Coordinates are `[longitude, latitude]`; output remains conditional connectivity, never a risk probability.
- Each first-arrival cell has exactly one band: `within-2h`, `within-4h`, `within-24h`, or `within-48h`.
- Calculation modules make no HTTP requests and retain no API credentials.
- Each production behaviour begins with a focused failing Vitest assertion.

---

### Task 1: Add earliest-arrival GeoJSON bands

**Files:**
- Create: `src/risk-zone/arrival-bands.ts`
- Modify: `src/risk-zone/types.ts`, `src/risk-zone/simulation.ts`, `src/index.ts`
- Create: `test/risk-zone/arrival-bands.test.ts`

**Interfaces:**
- Produces: `ArrivalBand`, `EarliestArrivalCellProperties`, `arrivalBandForMinutes(minutes)`, `buildEarliestArrivalBands(args)`, and `SimulationResult.earliestArrivalBands`.

- [ ] **Step 1: Write the failing tests**

```ts
it('keeps the earliest visit to a revisited cell', () => {
  const bands = buildEarliestArrivalBands({
    trajectories: [{ id: 'p-1', status: 'active', firstGateArrivalAt: null,
      coordinates: [[129, 37], [129.01, 37], [129, 37]] }],
    anchor: [129, 37], timeStepMinutes: 60, cellSizeMeters: 2_000,
    maximumArrivalMinutes: 2_880,
  });
  expect(bands.features[0].properties?.earliestArrivalMinutes).toBe(0);
});

it('assigns inclusive time-band boundaries', () => {
  expect(arrivalBandForMinutes(120)).toBe('within-2h');
  expect(arrivalBandForMinutes(121)).toBe('within-4h');
  expect(arrivalBandForMinutes(1_440)).toBe('within-24h');
});
```

Also assert that a long segment creates intermediate cells and any arrival after 2,880 minutes is omitted.

- [ ] **Step 2: Verify red**

Run: `npm test -- test/risk-zone/arrival-bands.test.ts`

Expected: import failure because the arrival-band symbols do not exist.

- [ ] **Step 3: Write the minimum implementation**

```ts
export function arrivalBandForMinutes(minutes: number): ArrivalBand | null {
  if (minutes <= 120) return 'within-2h';
  if (minutes <= 240) return 'within-4h';
  if (minutes <= 1_440) return 'within-24h';
  if (minutes <= 2_880) return 'within-48h';
  return null;
}
```

Project each trajectory segment to local metres, sample at half-cell spacing, and retain the lowest elapsed minute and visit count for each cell. Emit one closed GeoJSON polygon per unique cell. Compute the collection in `simulateConditionalConnectivity` from final trajectories.

- [ ] **Step 4: Verify green and commit**

Run: `npm test -- test/risk-zone/arrival-bands.test.ts && npm run build`

Expected: test passes and TypeScript exits 0. Commit only `arrival-bands.ts`, the specified engine types, simulation export, and the test with message `feat: expose earliest arrival map bands`.

### Task 2: Define synthetic scenario inputs

**Files:**
- Create: `demo/src/scenarios.ts`
- Create: `test/demo/scenarios.test.ts`

**Interfaces:**
- Produces: `DemoScenario`, `demoScenarios`, and `getDemoScenario(id)`.

- [ ] **Step 1: Write the failing scenario test**

```ts
it('provides three named fictional scenarios with a 48-hour simulation', () => {
  expect(demoScenarios.map((scenario) => scenario.id)).toEqual([
    'eastward-spread', 'tidal-turn', 'coastal-interception',
  ]);
  for (const scenario of demoScenarios) {
    expect(scenario.input.config?.horizonsHours).toEqual([2, 4, 24, 48]);
    expect(scenario.isFictional).toBe(true);
  }
});
```

Also test that the tidal flow changes from zero to six hours and that each scenario exposes fictional coast geometry.

- [ ] **Step 2: Verify red**

Run: `npm test -- test/demo/scenarios.test.ts`

Expected: import failure because the scenario module is absent.

- [ ] **Step 3: Implement deterministic factories**

```ts
export interface DemoScenario {
  id: 'eastward-spread' | 'tidal-turn' | 'coastal-interception';
  name: string;
  description: string;
  isFictional: true;
  input: SimulationInput;
  coast: FeatureCollection<Polygon | MultiPolygon>;
}
```

Seed all scenarios near fictional `[129.15, 37.15]`; use 48 particles, 15-minute steps, 500-metre cells, fixed vectors by elapsed hour, and a synchronous fictional coast/shallow-water provider. Do not import the concurrent public-data wrapper.

- [ ] **Step 4: Verify green**

Run: `npm test -- test/demo/scenarios.test.ts && npm run build`

Expected: all three deterministic scenario inputs are valid.

### Task 3: Build the MapLibre demo page

**Files:**
- Modify: `package.json`, `package-lock.json`, `tsconfig.json`
- Create: `demo/index.html`, `demo/vite.config.ts`, `demo/src/main.ts`, `demo/src/style.css`

**Interfaces:**
- Consumes: `demoScenarios`, `simulateConditionalConnectivity`, and `SimulationResult.earliestArrivalBands`.
- Produces: `npm run demo` and `npm run demo:build`.

- [ ] **Step 1: Add the dependencies and scripts**

Run: `npm install maplibre-gl && npm install --save-dev vite`

Add `demo` and `demo:build` scripts with `demo/vite.config.ts`, and add `demo` to `tsconfig.json` includes.

- [ ] **Step 2: Implement layers, control, and filtering**

```ts
map.addSource('arrival-bands', { type: 'geojson', data: result.earliestArrivalBands });
map.addLayer({
  id: 'arrival-bands-fill', type: 'fill', source: 'arrival-bands',
  paint: { 'fill-color': ['match', ['get', 'arrivalBand'],
    'within-2h', '#9d0208', 'within-4h', '#dc2f02',
    'within-24h', '#f48c06', '#ffddd2'], 'fill-opacity': 0.68 },
});
```

Create a scenario selector, 0–48 hour range input, visible band legend, and persistent fictional-scenario/non-probability notice. On selection change, use `GeoJSONSource.setData`; on time change, filter `arrival-bands-fill` with `earliestArrivalMinutes`.

- [ ] **Step 3: Verify the browser build and commit**

Run: `npm run demo:build`

Expected: Vite exits 0 and writes `dist/demo`. Commit only package, config, and demo app files with message `feat: add conditional connectivity scenario map`.

### Task 4: Document and fully verify

**Files:**
- Create: `demo/README.md`
- Modify: `docs/superpowers/specs/2026-08-23-scenario-map-design.md`
- Modify: `docs/superpowers/plans/2026-08-23-scenario-map.md`

**Interfaces:**
- Produces: local startup instructions and a final verification record.

- [ ] **Step 1: Document the real-data replacement boundary**

Explain `npm run demo`, the three fictional scenarios, arrival-band semantics, and that only `offshoreFlow`, `nearshorePolicy`, and `navigability` are replaced with real adapters while map rendering stays the same.

- [ ] **Step 2: Run full verification**

Run: `npm test && npm run build && npm run demo:build && git diff --check`

Expected: all tests and builds pass with no whitespace errors.

- [ ] **Step 3: Confirm concurrent work preservation and commit docs**

Run: `git diff -- README.md examples/conditional-connectivity.ts src/index.ts src/risk-zone/public-data.ts test/risk-zone/public-data.test.ts`

Expected: only pre-existing concurrent edits appear. Commit only demo documentation and these design/plan files with message `docs: explain scenario map demo`.
