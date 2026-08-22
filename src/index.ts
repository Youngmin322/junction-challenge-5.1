/**
 * Required wording for every result produced by the conditional-connectivity
 * engine. It prevents callers from presenting a simulated connection share as
 * a real-world blockage probability.
 */
export const CONDITIONAL_CONNECTIVITY_DISCLAIMER =
  'This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.';

export * from './risk-zone/types.js';
export { RiskZoneValidationError, validateSimulationInput } from './risk-zone/validation.js';
