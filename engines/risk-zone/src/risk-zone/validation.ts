import type {
  MonitoringGate,
  PolygonSeedGeometry,
  Position,
  RequiredSimulationConfig,
  SimulationInput,
} from './types.js';

const DEFAULT_CONFIG: RequiredSimulationConfig = {
  horizonsHours: [2, 4, 24, 48],
  timeStepMinutes: 15,
  snapshotIntervalMinutes: 60,
  regionCellSizeMeters: 1_000,
  randomSeed: 1,
};

export class RiskZoneValidationError extends Error {
  constructor(
    public readonly field: string,
    message: string,
  ) {
    super(`${field}: ${message}`);
    this.name = 'RiskZoneValidationError';
  }
}

export function validateSimulationInput(input: SimulationInput): RequiredSimulationConfig {
  if (!input || typeof input !== 'object') {
    throw new RiskZoneValidationError('input', 'must be an object');
  }

  validateSeed(input.seed);
  validateProvider(input.offshoreFlow, 'offshoreFlow');
  validateProvider(input.navigability, 'navigability', 'canTraverse');
  validateGate(input.gate);
  validateNearshorePolicy(input.nearshorePolicy);

  const config: RequiredSimulationConfig = {
    horizonsHours: [...(input.config?.horizonsHours ?? DEFAULT_CONFIG.horizonsHours)],
    timeStepMinutes: input.config?.timeStepMinutes ?? DEFAULT_CONFIG.timeStepMinutes,
    snapshotIntervalMinutes:
      input.config?.snapshotIntervalMinutes ?? DEFAULT_CONFIG.snapshotIntervalMinutes,
    regionCellSizeMeters:
      input.config?.regionCellSizeMeters ?? DEFAULT_CONFIG.regionCellSizeMeters,
    randomSeed: input.config?.randomSeed ?? DEFAULT_CONFIG.randomSeed,
  };

  if (!Number.isInteger(config.timeStepMinutes) || config.timeStepMinutes <= 0) {
    throw new RiskZoneValidationError('config.timeStepMinutes', 'must be a positive integer');
  }
  if (
    !Number.isInteger(config.snapshotIntervalMinutes) ||
    config.snapshotIntervalMinutes <= 0 ||
    config.snapshotIntervalMinutes % config.timeStepMinutes !== 0
  ) {
    throw new RiskZoneValidationError(
      'config.snapshotIntervalMinutes',
      'must be a positive multiple of config.timeStepMinutes',
    );
  }
  if (!Number.isFinite(config.regionCellSizeMeters) || config.regionCellSizeMeters <= 0) {
    throw new RiskZoneValidationError('config.regionCellSizeMeters', 'must be positive');
  }
  if (!Number.isInteger(config.randomSeed)) {
    throw new RiskZoneValidationError('config.randomSeed', 'must be an integer');
  }
  if (config.horizonsHours.length === 0) {
    throw new RiskZoneValidationError('config.horizonsHours', 'must not be empty');
  }

  let previous = 0;
  for (const horizonHours of config.horizonsHours) {
    if (!Number.isFinite(horizonHours) || horizonHours <= previous) {
      throw new RiskZoneValidationError(
        'config.horizonsHours',
        'must be strictly increasing positive values',
      );
    }
    const horizonMinutes = horizonHours * 60;
    if (!Number.isInteger(horizonMinutes) || horizonMinutes % config.timeStepMinutes !== 0) {
      throw new RiskZoneValidationError(
        'config.timeStepMinutes',
        'must divide every configured horizon',
      );
    }
    previous = horizonHours;
  }

  return config;
}

function validateSeed(seed: SimulationInput['seed']): void {
  const observedAt = new Date(seed?.observedAt);
  if (Number.isNaN(observedAt.valueOf())) {
    throw new RiskZoneValidationError('seed.observedAt', 'must be an ISO-8601 timestamp');
  }
  if (typeof seed.species !== 'string' || seed.species.trim() === '') {
    throw new RiskZoneValidationError('seed.species', 'must be a non-empty string');
  }
  if (!Number.isFinite(seed.depthMeters) || seed.depthMeters < 0) {
    throw new RiskZoneValidationError('seed.depthMeters', 'must be a non-negative number');
  }
  if (!Number.isFinite(seed.confidence) || seed.confidence < 0 || seed.confidence > 1) {
    throw new RiskZoneValidationError('seed.confidence', 'must be between 0 and 1');
  }
  if (!Number.isInteger(seed.ensembleSize) || seed.ensembleSize <= 0) {
    throw new RiskZoneValidationError('seed.ensembleSize', 'must be a positive integer');
  }
  if (!Number.isFinite(seed.positionUncertaintyMeters) || seed.positionUncertaintyMeters < 0) {
    throw new RiskZoneValidationError('seed.positionUncertaintyMeters', 'must be non-negative');
  }

  if (seed.geometry.kind === 'point') {
    validatePosition(seed.geometry.position, 'seed.geometry.position');
    return;
  }
  validatePolygon(seed.geometry, 'seed.geometry');
}

function validateNearshorePolicy(policy: SimulationInput['nearshorePolicy']): void {
  if (!policy) return;
  validatePolygon(policy.zone, 'nearshorePolicy.zone');
  validateProvider(policy.provider, 'nearshorePolicy.provider');
  if (policy.mode === 'residualAdd' && policy.isResidual !== true) {
    throw new RiskZoneValidationError(
      'nearshorePolicy.isResidual',
      'must be true for residualAdd',
    );
  }
}

function validateProvider(
  provider: unknown,
  field: string,
  method = 'velocityAt',
): void {
  if (!provider || typeof provider !== 'object' || typeof (provider as Record<string, unknown>)[method] !== 'function') {
    throw new RiskZoneValidationError(field, `must implement ${method}()`);
  }
}

function validateGate(gate: MonitoringGate): void {
  if (!Number.isFinite(gate.minDepthMeters) || gate.minDepthMeters < 0) {
    throw new RiskZoneValidationError('gate.minDepthMeters', 'must be non-negative');
  }
  if (!Number.isFinite(gate.maxDepthMeters) || gate.maxDepthMeters < gate.minDepthMeters) {
    throw new RiskZoneValidationError('gate.minDepthMeters', 'must not exceed gate.maxDepthMeters');
  }
  if (gate.kind === 'endpoints') {
    validatePosition(gate.start, 'gate.start');
    validatePosition(gate.end, 'gate.end');
    if (gate.start[0] === gate.end[0] && gate.start[1] === gate.end[1]) {
      throw new RiskZoneValidationError('gate', 'endpoints must be distinct');
    }
    return;
  }
  validatePosition(gate.center, 'gate.center');
  if (!Number.isFinite(gate.widthMeters) || gate.widthMeters <= 0) {
    throw new RiskZoneValidationError('gate.widthMeters', 'must be positive');
  }
  if (!Number.isFinite(gate.bearingDegrees)) {
    throw new RiskZoneValidationError('gate.bearingDegrees', 'must be finite');
  }
}

function validatePolygon(polygon: PolygonSeedGeometry, field: string): void {
  if (!Array.isArray(polygon.rings) || polygon.rings.length === 0) {
    throw new RiskZoneValidationError(`${field}.rings`, 'must contain an exterior ring');
  }
  for (const [ringIndex, ring] of polygon.rings.entries()) {
    if (!Array.isArray(ring) || ring.length < 4) {
      throw new RiskZoneValidationError(`${field}.rings[${ringIndex}]`, 'must have at least four positions');
    }
    ring.forEach((position, positionIndex) =>
      validatePosition(position, `${field}.rings[${ringIndex}][${positionIndex}]`),
    );
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      throw new RiskZoneValidationError(`${field}.rings[${ringIndex}]`, 'must be closed');
    }
  }
}

function validatePosition(position: Position, field: string): void {
  if (
    !Array.isArray(position) ||
    position.length !== 2 ||
    !Number.isFinite(position[0]) ||
    !Number.isFinite(position[1]) ||
    position[0] < -180 ||
    position[0] > 180 ||
    position[1] < -90 ||
    position[1] > 90
  ) {
    throw new RiskZoneValidationError(field, 'must be a valid [longitude, latitude] coordinate');
  }
}
