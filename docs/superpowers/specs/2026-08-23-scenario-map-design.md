# Conditional Connectivity Scenario Map — Design

## Goal

Add a browser-based, map-first demonstration on top of the existing TypeScript conditional-connectivity engine. It must make a dummy scenario visually understandable: an observed organism cluster is seeded offshore of the Hanul nuclear power site in Uljin, and a current-oriented fan shows the complete conditional approach direction around the intake. Particle outputs remain available for later analytical use, but the primary display is a stable four-band fan rather than a cumulative trajectory filter.

The demonstration is not an operational forecast or a blockage-risk product. Every visible result must state that it is a scenario result under supplied inputs, not a probability of organism abundance, blockage, or facility risk.

## User-visible behaviour

The demo starts on a map centered between the Hanul site and an offshore observation seed. The Hanul reference location is `[129.38301, 37.0931]` in GeoJSON longitude/latitude order. The coordinate is real map context, while every organism observation, current vector, depth assumption, trajectory, and resulting area remains explicitly synthetic. Existing fictional scenarios remain available, and a new default scenario is added:

1. **Hanul approach** — a converging westward synthetic current carries the offshore cluster toward the intake monitoring point.

The existing three explanatory scenarios remain available:

1. **Eastward spread** — a steady offshore flow carries the cluster east-northeast.
2. **Tidal turn** — the vector turns after four hours, visibly bending the plume.
3. **Coastal interception** — part of the ensemble meets a non-navigable land/shallow area and terminates.

For each run, the map renders, in this order: base map, optional fictional constraint outline, current-oriented approach fan, current arrows, seed marker, monitoring gate, and Hanul intake marker. A scenario selector and a 0–48 hour slider let a viewer select the synthetic current at that time. All four fan bands remain visible at every slider value.

### Current-oriented fan display

Time, shape, and colour have independent meanings:

- the slider samples the scenario flow provider at the selected hour and never hides a fan band;
- the fan opens upstream from the current vector and rotates around the intake as direction changes;
- faster currents create a longer, directionally narrower fan, while slower currents create a shorter, wider fan;
- the fill colour uses four relative length intervals, so the intake end remains darkest and every colour remains visible as the shape changes;
- the map and legend use text as well as colour, so colour is not the only carrier of meaning.

The display ratios are mutually exclusive:

- `immediate-monitoring`: 0–12% of the envelope length, deepest crimson;
- `near-intake`: 12–30%, red;
- `approach-corridor`: 30–65%, coral;
- `far-offshore`: 65–100%, pale peach.

These are demonstration monitoring bands, not calibrated safety limits. They describe relative position inside the synthetic current-oriented envelope, not physical probability.

### Earliest-arrival bands

The map must not stack a 24-hour translucent region over a 2-hour region. Instead, the engine creates one feature per occupied cell and assigns its `earliestArrivalMinutes` only once. The arrival time remains available for filtering and inspection through mutually exclusive bands:

- `within-2h`: 0–120 minutes, dark red;
- `within-4h`: 121–240 minutes, red;
- `within-24h`: 241–1,440 minutes, light red/orange;
- `within-48h`: 1,441–2,880 minutes, pale red.

The visible colour legend spells out “conditional approach priority” and does not call the colour a danger level or probability. Earliest-arrival cells remain an engine output for later analysis, but the browser slider does not filter them.

## Approach-priority post-processing

Add a pure `buildApproachPriorityBands` post-processor. It consumes the existing arrival-cell GeoJSON and returns the same polygons with distance and monitoring-band properties:

```ts
function buildApproachPriorityBands(args: {
  arrivalBands: FeatureCollection<Polygon, EarliestArrivalCellProperties>;
  intakePosition: Position;
  thresholdsMeters?: { immediate: number; near: number; corridor: number };
}): FeatureCollection<Polygon, ApproachPriorityCellProperties>;
```

The cell center is computed from the polygon boundary and measured to `intakePosition` with the existing local geographic distance helper. Every output feature retains `cellId`, `earliestArrivalMinutes`, `arrivalBand`, and `simulatedParticleVisits`, then adds `distanceToIntakeMeters` and one of `immediate-monitoring`, `near-intake`, `approach-corridor`, or `far-offshore` as `approachPriority`. Threshold validation requires positive, strictly increasing metre values.

## Engine addition

The current engine already returns each particle's coordinate sequence in 15-minute steps. Add `buildEarliestArrivalBands` as a pure post-processing function:

```ts
function buildEarliestArrivalBands(args: {
  trajectories: readonly ParticleTrajectory[];
  anchor: Position;
  timeStepMinutes: number;
  cellSizeMeters: number;
  maximumArrivalMinutes: number;
}): FeatureCollection<Polygon>;
```

For every successive position in every trajectory, calculate elapsed minutes from its coordinate index. Ignore positions after `maximumArrivalMinutes`. Rasterize the movement segment to cells with spacing no greater than half a cell width so a fast 15-minute step cannot skip a visible cell. For a cell seen more than once, retain the smallest arrival value. Emit each cell as one GeoJSON polygon with:

```ts
{
  cellId: string;
  earliestArrivalMinutes: number;
  arrivalBand: 'within-2h' | 'within-4h' | 'within-24h' | 'within-48h';
  simulatedParticleVisits: number;
}
```

`SimulationResult` gains `earliestArrivalBands`, produced after trajectories are finalised. It uses the largest configured horizon as its maximum. Custom horizons are legal, but a cell after 48 hours has no display band and is excluded by the default configuration. This output remains available for analytical consumers even though the browser's primary display uses the current-oriented fan.

## Data-provider boundary

The map never knows whether currents came from dummy JSON or an actual service. It consumes `SimulationInput`, whose `offshoreFlow`, optional `nearshorePolicy`, and `navigability` are already mockable interfaces.

- `demo/src/scenarios.ts` supplies `FlowFieldProvider` and `NavigabilityProvider` implementations constructed from deterministic synthetic functions and optional fictional coast polygons. The default Hanul provider returns a velocity aimed generally from the requested offshore point toward the intake monitoring point, with a small deterministic cross-current so the corridor remains visibly spread.
- A future ROMS/nearshore adapter converts raw API rows into the existing `PublicRiskZoneInput` / `calculateRiskZone` entry point, then passes the produced result to the same map renderer.
- Map features are stable GeoJSON with properties above, so a REST endpoint or a local scenario can both replace a source through `GeoJSONSource.setData`.

No API credential, HTTP fetch, or real-data claim is introduced in this change.

## Browser application

Create a small Vite + TypeScript app under `demo/` and use MapLibre GL JS. The Vite build imports the existing source engine directly. A configurable `mapStyleUrl` defaults to MapLibre's public demonstration style for the hackathon demo; deployment can replace it with an approved provider style without changing calculation code.

The MapLibre source IDs are `coast`, `approach-bands`, `current-arrows`, `seed`, `gate`, and `intake`. The renderer receives only serializable GeoJSON plus scenario metadata, which makes replacement with real flow data a data-mapping task rather than a UI rewrite.

The desktop layout is map-first with a dark operations sidebar. The sidebar contains the scenario selector, timeline, four-band approach legend, a concise path status, and the mandatory scenario disclaimer. On narrow screens it moves below the map without horizontal scrolling. Controls retain visible labels, keyboard focus, at least 44 px touch height, and colour-independent text descriptions.

## Validation

Tests must prove that first arrival wins when trajectories revisit a cell, a line segment populates intermediate cells, earliest-arrival bands receive the correct boundaries, coordinates beyond the configured maximum horizon are omitted, approach thresholds assign exact boundary distances correctly, all four fan bands remain present, fan direction rotates upstream, faster currents lengthen and narrow the fan, and the Hanul synthetic current changes enough over time to visibly rotate and resize it. Existing engine tests must remain passing.

`npm run demo:build` must compile the browser app, while `npm test` and `npm run build` continue to validate the engine. A `demo/README.md` documents local startup, all available scenarios, the output semantics, the real Hanul location context, and the exact real-data replacement boundary.
