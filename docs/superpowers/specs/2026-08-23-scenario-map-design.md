# Conditional Connectivity Scenario Map — Design

## Goal

Add a browser-based, map-first demonstration on top of the existing TypeScript conditional-connectivity engine. It must make a dummy scenario visually understandable: an observed organism cluster is seeded, time-varying currents move an ensemble, coast/shallow-water constraints stop invalid movement, and the map colours every traversed cell by its earliest simulated arrival time.

The demonstration is not an operational forecast or a blockage-risk product. Every visible result must state that it is a scenario result under supplied inputs, not a probability of organism abundance, blockage, or facility risk.

## User-visible behaviour

The demo starts on a map of a fictional intake-adjacent coast with a selected scenario. It offers three named scenarios:

1. **Eastward spread** — a steady offshore flow carries the cluster east-northeast.
2. **Tidal turn** — the vector turns after four hours, visibly bending the plume.
3. **Coastal interception** — part of the ensemble meets a non-navigable land/shallow area and terminates.

For each run, the map renders, in this order: base map, fictional coastline/restricted-water outline, first-arrival cells, current arrows, trajectory lines, seed marker, and an optional dashed monitoring gate. A scenario selector and a 0–48 hour slider let a viewer change the scenario and hide cells first reached after the selected time.

### Earliest-arrival bands

The map must not stack a 24-hour translucent region over a 2-hour region. Instead, the engine creates one feature per occupied cell and assigns its `earliestArrivalMinutes` only once. The cell colour has mutually exclusive bands:

- `within-2h`: 0–120 minutes, dark red;
- `within-4h`: 121–240 minutes, red;
- `within-24h`: 241–1,440 minutes, light red/orange;
- `within-48h`: 1,441–2,880 minutes, pale red.

The legend spells out “earliest simulated arrival” and does not call the colour a danger level or probability. The current slider filters by `earliestArrivalMinutes`; it does not rerun or reinterpret the simulation.

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

`SimulationResult` gains `earliestArrivalBands`, produced after trajectories are finalised. It uses the largest configured horizon as its maximum. Custom horizons are legal, but a cell after 48 hours has no display band and is excluded by the default demo configuration.

## Data-provider boundary

The map never knows whether currents came from dummy JSON or an actual service. It consumes `SimulationInput`, whose `offshoreFlow`, optional `nearshorePolicy`, and `navigability` are already mockable interfaces.

- `demo/src/scenarios.ts` supplies `FlowFieldProvider` and `NavigabilityProvider` implementations constructed from fixed arrays and fictional coast polygons.
- A future ROMS/nearshore adapter converts raw API rows into the existing `PublicRiskZoneInput` / `calculateRiskZone` entry point, then passes the produced result to the same map renderer.
- Map features are stable GeoJSON with properties above, so a REST endpoint or a local scenario can both replace a source through `GeoJSONSource.setData`.

No API credential, HTTP fetch, or real-data claim is introduced in this change.

## Browser application

Create a small Vite + TypeScript app under `demo/` and use MapLibre GL JS. The Vite build imports the existing source engine directly. A configurable `mapStyleUrl` defaults to MapLibre's public demonstration style for the hackathon demo; deployment can replace it with an approved provider style without changing calculation code.

The MapLibre source IDs are `coast`, `arrival-bands`, `current-arrows`, `trajectories`, `seed`, and `gate`. The renderer receives only a serializable `ScenarioRenderData` object, which makes replacement with real simulation output a data-mapping task rather than a UI rewrite.

## Validation

Tests must prove that first arrival wins when trajectories revisit a cell, a line segment populates intermediate cells, earliest-arrival bands receive the correct boundaries, and coordinates beyond the configured maximum horizon are omitted. Existing engine tests must remain passing.

`npm run demo:build` must compile the browser app, while `npm test` and `npm run build` continue to validate the engine. A `demo/README.md` documents local startup, the three fictional scenarios, the output semantics, and the exact real-data replacement boundary. The concurrent uncommitted README/example/public-data work is intentionally not modified by this map feature.
