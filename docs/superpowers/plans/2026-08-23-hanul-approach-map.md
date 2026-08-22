# Hanul Synthetic Approach Map Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the browser demo open on a synthetic offshore organism-cluster scenario that flows toward the Hanul nuclear intake area, with traversed cells becoming darker as they approach the intake and time remaining independently filterable.

**Architecture:** Keep the particle engine and provider contracts unchanged. Add one pure post-processor that decorates existing earliest-arrival GeoJSON cells with distance-to-intake priority, add a deterministic Hanul scenario behind the existing `FlowFieldProvider`/`NavigabilityProvider` boundaries, then render those serializable layers in the current Vite + MapLibre app.

**Tech Stack:** TypeScript, Vitest, Vite, MapLibre GL JS, GeoJSON.

---

### Task 1: Add intake-approach priority post-processing

**Files:**
- Create: `src/risk-zone/approach-priority.ts`
- Modify: `src/index.ts`
- Create: `test/risk-zone/approach-priority.test.ts`

**Steps:**
1. Write failing tests for the exact 2 km, 5 km, and 12 km boundaries, property preservation, and invalid threshold rejection.
2. Run `npm test -- test/risk-zone/approach-priority.test.ts` and confirm the missing-module/behavior failure.
3. Implement `buildApproachPriorityBands`, the public types, default thresholds, and package exports using the existing distance helper.
4. Re-run the focused test and confirm it passes.

### Task 2: Add the synthetic Hanul approach scenario

**Files:**
- Modify: `demo/src/scenarios.ts`
- Modify: `test/demo/scenarios.test.ts`

**Steps:**
1. Extend the scenario tests first to require `hanul-approach` as the first/default scenario, real map context coordinates, a seed east of the site, and a current vector whose dot product points toward the site.
2. Run `npm test -- test/demo/scenarios.test.ts` and confirm the new assertions fail.
3. Add the Hanul constants, intake metadata, empty real-basemap constraint overlay, deterministic target-seeking current provider, and a west-of-gate target so particles cross the intake gate.
4. Keep the three existing fictional scenarios and make their intake metadata explicit.
5. Re-run the focused tests and confirm they pass.

### Task 3: Render independent time and approach semantics in the web app

**Files:**
- Modify: `demo/src/map-data.ts`
- Modify: `test/demo/map-data.test.ts`
- Modify: `demo/src/main.ts`
- Modify: `demo/index.html`
- Modify: `demo/src/style.css`
- Modify: `demo/README.md`
- Modify: `README.md`

**Steps:**
1. Add a failing map-data test proving that approach properties are added without replacing `earliestArrivalMinutes`, and that timeline filtering still works.
2. Run `npm test -- test/demo/map-data.test.ts` and confirm the new behavior is missing.
3. Add the map-data preparation helper, then rerun the focused test.
4. Change the MapLibre source to `approach-bands`, colour by the four distance priorities, add the intake marker, point current arrows at the selected timeline time, and fit the viewport around seed/intake/gate.
5. Replace the page with a map-first dark operations layout containing labelled scenario/timeline controls, text-and-colour approach legend, path status, and explicit synthetic-data/non-probability wording.
6. Document local startup, dummy-versus-real semantics, and the provider replacement boundary in both READMEs.
7. Run `npm test`, `npm run build`, and `npm run demo:build`.
8. Start the local demo, inspect the Hanul scenario in a real browser at desktop and narrow widths, and fix visible usability defects.

### Task 4: Final verification and branch handoff

**Files:**
- Verify only unless a defect is found.

**Steps:**
1. Run the UI/UX accessibility validation query required by the selected design skill.
2. Run `npm test`, `npm run build`, and `npm run demo:build` again from a clean state.
3. Review `git diff` and `git status` without touching unrelated untracked user files.
4. Commit the implementation on `feat/nuclear-intake-risk-zone` and push the branch to `origin` so it is visible on GitHub.
