/**
 * Required wording for every result produced by the conditional-connectivity
 * engine. It prevents callers from presenting a simulated connection share as
 * a real-world blockage probability.
 */
export const CONDITIONAL_CONNECTIVITY_DISCLAIMER =
  'This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.';

export * from './risk-zone/types.js';
export { RiskZoneValidationError, validateSimulationInput } from './risk-zone/validation.js';
export {
  createLocalProjection,
  distanceMeters,
  pointInPolygon,
  segmentsIntersect,
} from './risk-zone/geo.js';
export { effectiveVelocityAt, GriddedFlowFieldProvider } from './risk-zone/flow-field.js';
export { materializeParticles } from './risk-zone/seed.js';
export { CoastAndBathymetryProvider } from './risk-zone/navigability.js';
export type { BathymetrySampler, CoastAndBathymetryOptions } from './risk-zone/navigability.js';
export { buildConnectivityRegions } from './risk-zone/regions.js';
export {
  approachPriorityForDistance,
  buildApproachPriorityBands,
  DEFAULT_APPROACH_PRIORITY_THRESHOLDS,
} from './risk-zone/approach-priority.js';
export type {
  ApproachPriority,
  ApproachPriorityCellProperties,
  ApproachPriorityThresholds,
  BuildApproachPriorityBandsInput,
} from './risk-zone/approach-priority.js';
export { nearestRankPercentile, simulateConditionalConnectivity } from './risk-zone/simulation.js';
export { calculateRiskZone, normalizePublicCurrentRecord } from './risk-zone/public-data.js';
export type {
  PublicBathymetryPoint,
  PublicCoastData,
  PublicCurrentRecord,
  PublicNearshoreData,
  PublicRiskZoneInput,
} from './risk-zone/public-data.js';
