// src/risk-zone/validation.ts
var DEFAULT_CONFIG = {
  horizonsHours: [2, 4, 24, 48],
  timeStepMinutes: 15,
  snapshotIntervalMinutes: 60,
  regionCellSizeMeters: 1e3,
  randomSeed: 1
};
var RiskZoneValidationError = class extends Error {
  constructor(field, message) {
    super(`${field}: ${message}`);
    this.field = field;
    this.name = "RiskZoneValidationError";
  }
  field;
};
function validateSimulationInput(input) {
  if (!input || typeof input !== "object") {
    throw new RiskZoneValidationError("input", "must be an object");
  }
  validateSeed(input.seed);
  validateProvider(input.offshoreFlow, "offshoreFlow");
  validateProvider(input.navigability, "navigability", "canTraverse");
  validateGate(input.gate);
  validateNearshorePolicy(input.nearshorePolicy);
  const config = {
    horizonsHours: [...input.config?.horizonsHours ?? DEFAULT_CONFIG.horizonsHours],
    timeStepMinutes: input.config?.timeStepMinutes ?? DEFAULT_CONFIG.timeStepMinutes,
    snapshotIntervalMinutes: input.config?.snapshotIntervalMinutes ?? DEFAULT_CONFIG.snapshotIntervalMinutes,
    regionCellSizeMeters: input.config?.regionCellSizeMeters ?? DEFAULT_CONFIG.regionCellSizeMeters,
    randomSeed: input.config?.randomSeed ?? DEFAULT_CONFIG.randomSeed
  };
  if (!Number.isInteger(config.timeStepMinutes) || config.timeStepMinutes <= 0) {
    throw new RiskZoneValidationError("config.timeStepMinutes", "must be a positive integer");
  }
  if (!Number.isInteger(config.snapshotIntervalMinutes) || config.snapshotIntervalMinutes <= 0 || config.snapshotIntervalMinutes % config.timeStepMinutes !== 0) {
    throw new RiskZoneValidationError(
      "config.snapshotIntervalMinutes",
      "must be a positive multiple of config.timeStepMinutes"
    );
  }
  if (!Number.isFinite(config.regionCellSizeMeters) || config.regionCellSizeMeters <= 0) {
    throw new RiskZoneValidationError("config.regionCellSizeMeters", "must be positive");
  }
  if (!Number.isInteger(config.randomSeed)) {
    throw new RiskZoneValidationError("config.randomSeed", "must be an integer");
  }
  if (config.horizonsHours.length === 0) {
    throw new RiskZoneValidationError("config.horizonsHours", "must not be empty");
  }
  let previous = 0;
  for (const horizonHours of config.horizonsHours) {
    if (!Number.isFinite(horizonHours) || horizonHours <= previous) {
      throw new RiskZoneValidationError(
        "config.horizonsHours",
        "must be strictly increasing positive values"
      );
    }
    const horizonMinutes = horizonHours * 60;
    if (!Number.isInteger(horizonMinutes) || horizonMinutes % config.timeStepMinutes !== 0) {
      throw new RiskZoneValidationError(
        "config.timeStepMinutes",
        "must divide every configured horizon"
      );
    }
    previous = horizonHours;
  }
  return config;
}
function validateSeed(seed) {
  const observedAt = new Date(seed?.observedAt);
  if (Number.isNaN(observedAt.valueOf())) {
    throw new RiskZoneValidationError("seed.observedAt", "must be an ISO-8601 timestamp");
  }
  if (typeof seed.species !== "string" || seed.species.trim() === "") {
    throw new RiskZoneValidationError("seed.species", "must be a non-empty string");
  }
  if (!Number.isFinite(seed.depthMeters) || seed.depthMeters < 0) {
    throw new RiskZoneValidationError("seed.depthMeters", "must be a non-negative number");
  }
  if (!Number.isFinite(seed.confidence) || seed.confidence < 0 || seed.confidence > 1) {
    throw new RiskZoneValidationError("seed.confidence", "must be between 0 and 1");
  }
  if (!Number.isInteger(seed.ensembleSize) || seed.ensembleSize <= 0) {
    throw new RiskZoneValidationError("seed.ensembleSize", "must be a positive integer");
  }
  if (!Number.isFinite(seed.positionUncertaintyMeters) || seed.positionUncertaintyMeters < 0) {
    throw new RiskZoneValidationError("seed.positionUncertaintyMeters", "must be non-negative");
  }
  if (seed.geometry.kind === "point") {
    validatePosition(seed.geometry.position, "seed.geometry.position");
    return;
  }
  validatePolygon(seed.geometry, "seed.geometry");
}
function validateNearshorePolicy(policy) {
  if (!policy) return;
  validatePolygon(policy.zone, "nearshorePolicy.zone");
  validateProvider(policy.provider, "nearshorePolicy.provider");
  if (policy.mode === "residualAdd" && policy.isResidual !== true) {
    throw new RiskZoneValidationError(
      "nearshorePolicy.isResidual",
      "must be true for residualAdd"
    );
  }
}
function validateProvider(provider, field, method = "velocityAt") {
  if (!provider || typeof provider !== "object" || typeof provider[method] !== "function") {
    throw new RiskZoneValidationError(field, `must implement ${method}()`);
  }
}
function validateGate(gate) {
  if (!Number.isFinite(gate.minDepthMeters) || gate.minDepthMeters < 0) {
    throw new RiskZoneValidationError("gate.minDepthMeters", "must be non-negative");
  }
  if (!Number.isFinite(gate.maxDepthMeters) || gate.maxDepthMeters < gate.minDepthMeters) {
    throw new RiskZoneValidationError("gate.minDepthMeters", "must not exceed gate.maxDepthMeters");
  }
  if (gate.kind === "endpoints") {
    validatePosition(gate.start, "gate.start");
    validatePosition(gate.end, "gate.end");
    if (gate.start[0] === gate.end[0] && gate.start[1] === gate.end[1]) {
      throw new RiskZoneValidationError("gate", "endpoints must be distinct");
    }
    return;
  }
  validatePosition(gate.center, "gate.center");
  if (!Number.isFinite(gate.widthMeters) || gate.widthMeters <= 0) {
    throw new RiskZoneValidationError("gate.widthMeters", "must be positive");
  }
  if (!Number.isFinite(gate.bearingDegrees)) {
    throw new RiskZoneValidationError("gate.bearingDegrees", "must be finite");
  }
}
function validatePolygon(polygon, field) {
  if (!Array.isArray(polygon.rings) || polygon.rings.length === 0) {
    throw new RiskZoneValidationError(`${field}.rings`, "must contain an exterior ring");
  }
  for (const [ringIndex, ring] of polygon.rings.entries()) {
    if (!Array.isArray(ring) || ring.length < 4) {
      throw new RiskZoneValidationError(`${field}.rings[${ringIndex}]`, "must have at least four positions");
    }
    ring.forEach(
      (position, positionIndex) => validatePosition(position, `${field}.rings[${ringIndex}][${positionIndex}]`)
    );
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) {
      throw new RiskZoneValidationError(`${field}.rings[${ringIndex}]`, "must be closed");
    }
  }
}
function validatePosition(position, field) {
  if (!Array.isArray(position) || position.length !== 2 || !Number.isFinite(position[0]) || !Number.isFinite(position[1]) || position[0] < -180 || position[0] > 180 || position[1] < -90 || position[1] > 90) {
    throw new RiskZoneValidationError(field, "must be a valid [longitude, latitude] coordinate");
  }
}

// src/risk-zone/geo.ts
var EARTH_RADIUS_METERS = 6371e3;
var DEGREES_TO_RADIANS = Math.PI / 180;
function createLocalProjection(anchor) {
  const [anchorLongitude, anchorLatitude] = anchor;
  const anchorLatitudeRadians = anchorLatitude * DEGREES_TO_RADIANS;
  const longitudeScale = EARTH_RADIUS_METERS * Math.cos(anchorLatitudeRadians) * DEGREES_TO_RADIANS;
  const latitudeScale = EARTH_RADIUS_METERS * DEGREES_TO_RADIANS;
  return {
    toLocal([longitude, latitude]) {
      return [(longitude - anchorLongitude) * longitudeScale, (latitude - anchorLatitude) * latitudeScale];
    },
    toGeographic([xMeters, yMeters]) {
      return [anchorLongitude + xMeters / longitudeScale, anchorLatitude + yMeters / latitudeScale];
    }
  };
}
function distanceMeters(from, to) {
  const projection = createLocalProjection(from);
  const [x, y] = projection.toLocal(to);
  return Math.hypot(x, y);
}
function pointInPolygon(point, rings) {
  const exterior = rings[0];
  if (!exterior || !pointInRing(point, exterior)) return false;
  return !rings.slice(1).some((hole) => pointInRing(point, hole));
}
function segmentsIntersect(firstStart, firstEnd, secondStart, secondEnd) {
  const firstOrientationStart = orientation(firstStart, firstEnd, secondStart);
  const firstOrientationEnd = orientation(firstStart, firstEnd, secondEnd);
  const secondOrientationStart = orientation(secondStart, secondEnd, firstStart);
  const secondOrientationEnd = orientation(secondStart, secondEnd, firstEnd);
  if (firstOrientationStart !== firstOrientationEnd && secondOrientationStart !== secondOrientationEnd) {
    return true;
  }
  return firstOrientationStart === 0 && pointOnSegment(secondStart, firstStart, firstEnd) || firstOrientationEnd === 0 && pointOnSegment(secondEnd, firstStart, firstEnd) || secondOrientationStart === 0 && pointOnSegment(firstStart, secondStart, secondEnd) || secondOrientationEnd === 0 && pointOnSegment(firstEnd, secondStart, secondEnd);
}
function pointInRing(point, ring) {
  let inside = false;
  for (let index = 0, previousIndex = ring.length - 1; index < ring.length; previousIndex = index++) {
    const current = ring[index];
    const previous = ring[previousIndex];
    if (pointOnSegment(point, previous, current)) return true;
    const crossesLatitude = current[1] > point[1] !== previous[1] > point[1];
    if (!crossesLatitude) continue;
    const intersectionLongitude = (previous[0] - current[0]) * (point[1] - current[1]) / (previous[1] - current[1]) + current[0];
    if (point[0] < intersectionLongitude) inside = !inside;
  }
  return inside;
}
function orientation(first, second, third) {
  const cross = (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (third[0] - first[0]);
  if (Math.abs(cross) < Number.EPSILON) return 0;
  return cross > 0 ? 1 : -1;
}
function pointOnSegment(point, start, end) {
  if (orientation(start, end, point) !== 0) return false;
  return point[0] >= Math.min(start[0], end[0]) && point[0] <= Math.max(start[0], end[0]) && point[1] >= Math.min(start[1], end[1]) && point[1] <= Math.max(start[1], end[1]);
}

// src/risk-zone/flow-field.ts
var GriddedFlowFieldProvider = class {
  constructor(samples) {
    this.samples = samples;
  }
  samples;
  velocityAt(request) {
    const compatible = this.samples.filter((sample) => sample.depthMeters === request.depthMeters);
    if (compatible.length === 0) return null;
    const requestedTime = request.validAt.valueOf();
    const earlierTimes = compatible.map((sample) => sample.validAt.valueOf()).filter((time) => time <= requestedTime);
    const laterTimes = compatible.map((sample) => sample.validAt.valueOf()).filter((time) => time >= requestedTime);
    if (earlierTimes.length === 0 || laterTimes.length === 0) return null;
    const earlierTime = Math.max(...earlierTimes);
    const laterTime = Math.min(...laterTimes);
    const earlier = nearestSample(
      compatible.filter((sample) => sample.validAt.valueOf() === earlierTime),
      request
    );
    const later = nearestSample(
      compatible.filter((sample) => sample.validAt.valueOf() === laterTime),
      request
    );
    if (!earlier || !later) return null;
    const intervalMilliseconds = laterTime - earlierTime;
    const ratio = intervalMilliseconds === 0 ? 0 : (requestedTime - earlierTime) / intervalMilliseconds;
    return {
      uMetersPerSecond: interpolate(earlier.uMetersPerSecond, later.uMetersPerSecond, ratio),
      vMetersPerSecond: interpolate(earlier.vMetersPerSecond, later.vMetersPerSecond, ratio),
      sourceTime: earlier.sourceTime,
      validAt: request.validAt
    };
  }
};
function effectiveVelocityAt(request, offshore, policy) {
  const offshoreVelocity = offshore.velocityAt(request);
  if (!policy || !pointInPolygon(request.position, policy.zone.rings)) {
    return offshoreVelocity;
  }
  const nearshoreVelocity = policy.provider.velocityAt(request);
  if (!nearshoreVelocity) return null;
  if (policy.mode === "replace") return nearshoreVelocity;
  if (!offshoreVelocity) return null;
  return {
    uMetersPerSecond: offshoreVelocity.uMetersPerSecond + nearshoreVelocity.uMetersPerSecond,
    vMetersPerSecond: offshoreVelocity.vMetersPerSecond + nearshoreVelocity.vMetersPerSecond,
    sourceTime: offshoreVelocity.sourceTime,
    validAt: request.validAt
  };
}
function nearestSample(samples, request) {
  return samples.reduce((closest, sample) => {
    if (!closest) return sample;
    return distanceMeters(sample.position, request.position) < distanceMeters(closest.position, request.position) ? sample : closest;
  }, void 0);
}
function interpolate(start, end, ratio) {
  return start + (end - start) * ratio;
}

// src/risk-zone/seed.ts
function materializeParticles(seed, randomSeed) {
  const random = mulberry32(randomSeed);
  const positions = seed.geometry.kind === "point" ? samplePoint(seed.geometry.position, seed.positionUncertaintyMeters, seed.ensembleSize, random) : samplePolygon(seed.geometry.rings, seed.ensembleSize, random);
  return positions.map((position, index) => ({
    id: `particle-${index + 1}`,
    depthMeters: seed.depthMeters,
    status: "active",
    firstGateArrivalAt: null,
    coordinates: [position]
  }));
}
function samplePoint(center, uncertaintyMeters, count, random) {
  if (uncertaintyMeters === 0) {
    return Array.from({ length: count }, () => [center[0], center[1]]);
  }
  const projection = createLocalProjection(center);
  return Array.from({ length: count }, () => {
    const radius = Math.sqrt(random()) * uncertaintyMeters;
    const angle = random() * Math.PI * 2;
    return projection.toGeographic([Math.cos(angle) * radius, Math.sin(angle) * radius]);
  });
}
function samplePolygon(rings, count, random) {
  const exterior = rings[0];
  const longitudes = exterior.map(([longitude]) => longitude);
  const latitudes = exterior.map(([, latitude]) => latitude);
  const minimumLongitude = Math.min(...longitudes);
  const maximumLongitude = Math.max(...longitudes);
  const minimumLatitude = Math.min(...latitudes);
  const maximumLatitude = Math.max(...latitudes);
  const positions = [];
  const maximumAttempts = count * 100;
  for (let attempt = 0; attempt < maximumAttempts && positions.length < count; attempt += 1) {
    const candidate = [
      minimumLongitude + (maximumLongitude - minimumLongitude) * random(),
      minimumLatitude + (maximumLatitude - minimumLatitude) * random()
    ];
    if (pointInPolygon(candidate, rings)) positions.push(candidate);
  }
  if (positions.length !== count) {
    throw new Error("seed.geometry: could not sample the requested ensemble within the polygon");
  }
  return positions;
}
function mulberry32(seed) {
  let state = seed >>> 0;
  return () => {
    state += 1831565813;
    let value = state;
    value = Math.imul(value ^ value >>> 15, value | 1);
    value ^= value + Math.imul(value ^ value >>> 7, value | 61);
    return ((value ^ value >>> 14) >>> 0) / 4294967296;
  };
}

// src/risk-zone/navigability.ts
var CoastAndBathymetryProvider = class {
  constructor(options) {
    this.options = options;
  }
  options;
  canTraverse(request) {
    const projection = createLocalProjection(request.from);
    const destination = projection.toLocal(request.to);
    const numberOfSegments = Math.max(
      1,
      Math.ceil(distanceMeters(request.from, request.to) / this.options.sampleSpacingMeters)
    );
    for (let index = 0; index <= numberOfSegments; index += 1) {
      const fraction = index / numberOfSegments;
      const position = projection.toGeographic([
        destination[0] * fraction,
        destination[1] * fraction
      ]);
      if (this.options.landPolygons.some((polygon) => pointInPolygon(position, polygon))) {
        return { passable: false, reason: "land" };
      }
      const depth = this.options.bathymetry.depthAt(position, request.at);
      if (depth === null) return { passable: false, reason: "outside-coverage" };
      if (depth < this.options.minimumWaterDepthMeters) {
        return { passable: false, reason: "shallow-water" };
      }
    }
    return { passable: true };
  }
};

// src/risk-zone/regions.ts
function buildConnectivityRegions(positions, anchor, cellSizeMeters) {
  const projection = createLocalProjection(anchor);
  const cells = /* @__PURE__ */ new Map();
  for (const position of positions) {
    const [xMeters, yMeters] = projection.toLocal(position);
    const x = Math.floor(xMeters / cellSizeMeters);
    const y = Math.floor(yMeters / cellSizeMeters);
    const key = cellKey(x, y);
    const existing = cells.get(key);
    if (existing) {
      existing.particleCount += 1;
    } else {
      cells.set(key, { x, y, particleCount: 1 });
    }
  }
  const remaining = new Set(cells.keys());
  const features = [];
  while (remaining.size > 0) {
    const firstKey = remaining.values().next().value;
    const connected = collectConnectedCells(firstKey, cells, remaining);
    const coordinates = connected.map((cell) => [cellBoundary(cell, cellSizeMeters, projection)]);
    features.push({
      type: "Feature",
      properties: {
        occupiedCellCount: connected.length,
        representedParticleCount: connected.reduce((total, cell) => total + cell.particleCount, 0)
      },
      geometry: { type: "MultiPolygon", coordinates }
    });
  }
  return { type: "FeatureCollection", features };
}
function collectConnectedCells(firstKey, cells, remaining) {
  const connected = [];
  const pending = [firstKey];
  remaining.delete(firstKey);
  while (pending.length > 0) {
    const key = pending.pop();
    const cell = cells.get(key);
    connected.push(cell);
    for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
      for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
        if (offsetX === 0 && offsetY === 0) continue;
        const neighborKey = cellKey(cell.x + offsetX, cell.y + offsetY);
        if (remaining.delete(neighborKey)) pending.push(neighborKey);
      }
    }
  }
  return connected;
}
function cellBoundary(cell, cellSizeMeters, projection) {
  const minimumX = cell.x * cellSizeMeters;
  const minimumY = cell.y * cellSizeMeters;
  return [
    projection.toGeographic([minimumX, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY])
  ].map(([longitude, latitude]) => [longitude, latitude]);
}
function cellKey(x, y) {
  return `${x}:${y}`;
}

// src/risk-zone/arrival-bands.ts
function arrivalBandForMinutes(minutes) {
  if (minutes < 0 || !Number.isFinite(minutes)) return null;
  if (minutes <= 120) return "within-2h";
  if (minutes <= 240) return "within-4h";
  if (minutes <= 1440) return "within-24h";
  if (minutes <= 2880) return "within-48h";
  return null;
}
function buildEarliestArrivalBands(input) {
  const projection = createLocalProjection(input.anchor);
  const cells = /* @__PURE__ */ new Map();
  for (const trajectory of input.trajectories) {
    const firstPosition = trajectory.coordinates[0];
    if (!firstPosition) continue;
    recordPosition(cells, firstPosition, 0, trajectory.id, input, projection);
    for (let coordinateIndex = 1; coordinateIndex < trajectory.coordinates.length; coordinateIndex += 1) {
      const from = trajectory.coordinates[coordinateIndex - 1];
      const to = trajectory.coordinates[coordinateIndex];
      const fromMinutes = (coordinateIndex - 1) * input.timeStepMinutes;
      const toMinutes = coordinateIndex * input.timeStepMinutes;
      if (fromMinutes > input.maximumArrivalMinutes) break;
      const [fromX, fromY] = projection.toLocal(from);
      const [toX, toY] = projection.toLocal(to);
      const distance = Math.hypot(toX - fromX, toY - fromY);
      const stepCount = Math.max(1, Math.ceil(distance / (input.cellSizeMeters / 2)));
      for (let step = 1; step <= stepCount; step += 1) {
        const fraction = step / stepCount;
        const elapsedMinutes = fromMinutes + (toMinutes - fromMinutes) * fraction;
        if (elapsedMinutes > input.maximumArrivalMinutes) continue;
        recordPosition(
          cells,
          projection.toGeographic([
            fromX + (toX - fromX) * fraction,
            fromY + (toY - fromY) * fraction
          ]),
          elapsedMinutes,
          trajectory.id,
          input,
          projection
        );
      }
    }
  }
  const features = [];
  for (const cell of cells.values()) {
    const arrivalBand = arrivalBandForMinutes(cell.earliestArrivalMinutes);
    if (!arrivalBand) continue;
    features.push({
      type: "Feature",
      properties: {
        cellId: cellKey2(cell.x, cell.y),
        earliestArrivalMinutes: cell.earliestArrivalMinutes,
        arrivalBand,
        simulatedParticleVisits: cell.particleIds.size
      },
      geometry: {
        type: "Polygon",
        coordinates: [cellBoundary2(cell.x, cell.y, input.cellSizeMeters, projection)]
      }
    });
  }
  return { type: "FeatureCollection", features };
}
function recordPosition(cells, position, elapsedMinutes, particleId, input, projection) {
  if (elapsedMinutes > input.maximumArrivalMinutes) return;
  const [xMeters, yMeters] = projection.toLocal(position);
  const x = Math.floor(xMeters / input.cellSizeMeters);
  const y = Math.floor(yMeters / input.cellSizeMeters);
  const key = cellKey2(x, y);
  const existing = cells.get(key);
  if (existing) {
    existing.earliestArrivalMinutes = Math.min(existing.earliestArrivalMinutes, elapsedMinutes);
    existing.particleIds.add(particleId);
    return;
  }
  cells.set(key, {
    x,
    y,
    earliestArrivalMinutes: elapsedMinutes,
    particleIds: /* @__PURE__ */ new Set([particleId])
  });
}
function cellBoundary2(x, y, cellSizeMeters, projection) {
  const minimumX = x * cellSizeMeters;
  const minimumY = y * cellSizeMeters;
  return [
    projection.toGeographic([minimumX, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY]),
    projection.toGeographic([minimumX + cellSizeMeters, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY + cellSizeMeters]),
    projection.toGeographic([minimumX, minimumY])
  ].map(([longitude, latitude]) => [longitude, latitude]);
}
function cellKey2(x, y) {
  return `${x}:${y}`;
}

// src/risk-zone/simulation.ts
var TERMINAL_STATUSES = /* @__PURE__ */ new Set([
  "blocked-land",
  "blocked-shallow-water",
  "outside-navigability-coverage",
  "outside-flow-coverage"
]);
function simulateConditionalConnectivity(input) {
  const config = validateSimulationInput(input);
  const startAt = new Date(input.seed.observedAt);
  const anchor = anchorForSeed(input.seed.geometry);
  const projection = createLocalProjection(anchor);
  const gate = normalizeGate(input.gate, projection);
  const particles = materializeParticles(input.seed, config.randomSeed);
  const diagnostics = [];
  const snapshots = [];
  const statusAtHorizon = /* @__PURE__ */ new Map();
  const horizonMinutes = config.horizonsHours.map((hours) => hours * 60);
  const horizonMinuteSet = new Set(horizonMinutes);
  const maximumMinutes = Math.max(...horizonMinutes);
  let noLiveDiagnosticRecorded = false;
  for (let elapsedMinutes = config.timeStepMinutes; elapsedMinutes <= maximumMinutes; elapsedMinutes += config.timeStepMinutes) {
    const currentAt = new Date(startAt.valueOf() + (elapsedMinutes - config.timeStepMinutes) * 6e4);
    const midpointAt = new Date(currentAt.valueOf() + config.timeStepMinutes * 6e4 / 2);
    const nextAt = new Date(startAt.valueOf() + elapsedMinutes * 6e4);
    for (const particle of particles) {
      if (!isLive(particle.status)) continue;
      const currentPosition = particle.coordinates.at(-1);
      const initialVelocity = effectiveVelocityAt(
        { position: currentPosition, depthMeters: particle.depthMeters, validAt: currentAt },
        input.offshoreFlow,
        input.nearshorePolicy
      );
      if (!initialVelocity) {
        terminateForMissingFlow(particle, currentAt, diagnostics);
        continue;
      }
      const midpoint = advance(
        currentPosition,
        initialVelocity.uMetersPerSecond,
        initialVelocity.vMetersPerSecond,
        config.timeStepMinutes / 2,
        projection
      );
      const midpointVelocity = effectiveVelocityAt(
        { position: midpoint, depthMeters: particle.depthMeters, validAt: midpointAt },
        input.offshoreFlow,
        input.nearshorePolicy
      );
      if (!midpointVelocity) {
        terminateForMissingFlow(particle, midpointAt, diagnostics);
        continue;
      }
      const nextPosition = advance(
        currentPosition,
        midpointVelocity.uMetersPerSecond,
        midpointVelocity.vMetersPerSecond,
        config.timeStepMinutes,
        projection
      );
      const traversal = input.navigability.canTraverse({
        from: currentPosition,
        to: nextPosition,
        particleDepthMeters: particle.depthMeters,
        at: nextAt
      });
      if (!traversal.passable) {
        const status = navigationStatus(traversal.reason);
        particle.status = status;
        diagnostics.push({
          code: "navigability-rejection",
          particleId: particle.id,
          validAt: nextAt.toISOString(),
          message: `Particle movement rejected because of ${traversal.reason ?? "unclassified coverage"}.`
        });
        continue;
      }
      particle.coordinates.push(nextPosition);
      if (particle.firstGateArrivalAt === null && particle.depthMeters >= input.gate.minDepthMeters && particle.depthMeters <= input.gate.maxDepthMeters && segmentsIntersect(currentPosition, nextPosition, gate.start, gate.end)) {
        particle.firstGateArrivalAt = nextAt;
        particle.status = "gate-reached";
      }
    }
    const liveParticles = particles.filter((particle) => isLive(particle.status));
    if (liveParticles.length === 0 && !noLiveDiagnosticRecorded) {
      diagnostics.push({
        code: "no-live-particles",
        validAt: nextAt.toISOString(),
        message: "No particle remains in flow and navigability coverage."
      });
      noLiveDiagnosticRecorded = true;
    }
    if (elapsedMinutes % config.snapshotIntervalMinutes === 0 || horizonMinuteSet.has(elapsedMinutes)) {
      snapshots.push({
        validAt: nextAt.toISOString(),
        regions: buildConnectivityRegions(
          liveParticles.map((particle) => particle.coordinates.at(-1)),
          anchor,
          config.regionCellSizeMeters
        ),
        representedParticleCount: liveParticles.length
      });
    }
    if (horizonMinuteSet.has(elapsedMinutes)) {
      statusAtHorizon.set(elapsedMinutes, particles.map((particle) => particle.status));
    }
  }
  const particleTrajectories = particles.map((particle) => ({
    id: particle.id,
    status: particle.status,
    firstGateArrivalAt: particle.firstGateArrivalAt?.toISOString() ?? null,
    coordinates: particle.coordinates
  }));
  return {
    classification: "conditional-connectivity-not-blockage-probability",
    disclaimer: CONDITIONAL_CONNECTIVITY_DISCLAIMER,
    inputSummary: {
      observedAt: input.seed.observedAt,
      species: input.seed.species,
      depthMeters: input.seed.depthMeters,
      confidence: input.seed.confidence,
      ensembleSize: input.seed.ensembleSize,
      horizonHours: [...config.horizonsHours]
    },
    horizonSummaries: config.horizonsHours.map((horizonHours) => {
      const elapsedMinutes = horizonHours * 60;
      const arrivedMinutes = particles.flatMap((particle) => {
        if (!particle.firstGateArrivalAt) return [];
        const minutes = (particle.firstGateArrivalAt.valueOf() - startAt.valueOf()) / 6e4;
        return minutes <= elapsedMinutes ? [minutes] : [];
      });
      return {
        horizonHours,
        conditionalGateConnectionFraction: arrivedMinutes.length / particles.length,
        firstGateCrossingCount: arrivedMinutes.length,
        etaMinutes: {
          p10: nearestRankPercentile(arrivedMinutes, 10),
          p50: nearestRankPercentile(arrivedMinutes, 50),
          p90: nearestRankPercentile(arrivedMinutes, 90)
        },
        particleStatusCounts: countStatuses(statusAtHorizon.get(elapsedMinutes) ?? [])
      };
    }),
    snapshots,
    particleTrajectories,
    earliestArrivalBands: buildEarliestArrivalBands({
      trajectories: particleTrajectories,
      anchor,
      timeStepMinutes: config.timeStepMinutes,
      cellSizeMeters: config.regionCellSizeMeters,
      maximumArrivalMinutes: maximumMinutes
    }),
    diagnostics
  };
}
function nearestRankPercentile(values, percentile) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil(percentile / 100 * sorted.length) - 1];
}
function anchorForSeed(geometry) {
  return geometry.kind === "point" ? geometry.position : geometry.rings[0][0];
}
function normalizeGate(gate, projection) {
  if (gate.kind === "endpoints") return { start: gate.start, end: gate.end };
  const center = projection.toLocal(gate.center);
  const lineBearingRadians = gate.bearingDegrees * Math.PI / 180;
  const halfWidth = gate.widthMeters / 2;
  const offsetX = Math.sin(lineBearingRadians) * halfWidth;
  const offsetY = Math.cos(lineBearingRadians) * halfWidth;
  return {
    start: projection.toGeographic([center[0] - offsetX, center[1] - offsetY]),
    end: projection.toGeographic([center[0] + offsetX, center[1] + offsetY])
  };
}
function advance(position, uMetersPerSecond, vMetersPerSecond, minutes, projection) {
  const local = projection.toLocal(position);
  const durationSeconds = minutes * 60;
  return projection.toGeographic([
    local[0] + uMetersPerSecond * durationSeconds,
    local[1] + vMetersPerSecond * durationSeconds
  ]);
}
function isLive(status) {
  return !TERMINAL_STATUSES.has(status);
}
function terminateForMissingFlow(particle, validAt, diagnostics) {
  particle.status = "outside-flow-coverage";
  diagnostics.push({
    code: "flow-coverage-miss",
    particleId: particle.id,
    validAt: validAt.toISOString(),
    message: "No current vector covered this particle position, depth, and time."
  });
}
function navigationStatus(reason) {
  if (reason === "land") return "blocked-land";
  if (reason === "shallow-water") return "blocked-shallow-water";
  return "outside-navigability-coverage";
}
function countStatuses(statuses) {
  const counts = {
    active: 0,
    "gate-reached": 0,
    "blocked-land": 0,
    "blocked-shallow-water": 0,
    "outside-navigability-coverage": 0,
    "outside-flow-coverage": 0
  };
  for (const status of statuses) counts[status] += 1;
  return counts;
}

// src/risk-zone/public-data.ts
function normalizePublicCurrentRecord(record) {
  const validAt = requiredDate(record.validAt, "current.validAt");
  const sourceTime = requiredDate(record.issuedAt, "current.issuedAt");
  validateFinite(record.longitude, "current.longitude");
  validateFinite(record.latitude, "current.latitude");
  validateFinite(record.depthMeters, "current.depthMeters");
  const directVelocity = typeof record.uMetersPerSecond === "number" && typeof record.vMetersPerSecond === "number";
  let uMetersPerSecond;
  let vMetersPerSecond;
  if (directVelocity) {
    uMetersPerSecond = record.uMetersPerSecond;
    vMetersPerSecond = record.vMetersPerSecond;
  } else {
    if (typeof record.speedMetersPerSecond !== "number" || typeof record.directionDegrees !== "number" || !record.directionConvention) {
      throw new RiskZoneValidationError(
        "current",
        "needs both u/v or speed, direction, and directionConvention"
      );
    }
    validateFinite(record.speedMetersPerSecond, "current.speedMetersPerSecond");
    validateFinite(record.directionDegrees, "current.directionDegrees");
    const travelBearing = record.directionDegrees + (record.directionConvention === "from" ? 180 : 0);
    const radians = travelBearing * Math.PI / 180;
    uMetersPerSecond = record.speedMetersPerSecond * Math.sin(radians);
    vMetersPerSecond = record.speedMetersPerSecond * Math.cos(radians);
  }
  validateFinite(uMetersPerSecond, "current.uMetersPerSecond");
  validateFinite(vMetersPerSecond, "current.vMetersPerSecond");
  return {
    position: [record.longitude, record.latitude],
    depthMeters: record.depthMeters,
    sourceTime,
    validAt,
    uMetersPerSecond,
    vMetersPerSecond
  };
}
function calculateRiskZone(input) {
  const offshoreFlow = new GriddedFlowFieldProvider(
    input.offshoreCurrents.map(normalizePublicCurrentRecord)
  );
  const nearshorePolicy = input.nearshore ? createNearshorePolicy(input.nearshore) : void 0;
  const maximumBathymetryLookupMeters = input.coast.maximumBathymetryLookupMeters ?? 5e3;
  const navigability = new CoastAndBathymetryProvider({
    landPolygons: input.coast.landPolygons,
    bathymetry: {
      depthAt(position) {
        const closest = input.coast.bathymetryPoints.reduce((current, point) => {
          const distance = distanceMeters(position, [point.longitude, point.latitude]);
          return !current || distance < current.distance ? { point, distance } : current;
        }, void 0);
        if (!closest || closest.distance > maximumBathymetryLookupMeters) return null;
        return closest.point.depthMeters;
      }
    },
    minimumWaterDepthMeters: input.coast.minimumWaterDepthMeters,
    sampleSpacingMeters: input.coast.sampleSpacingMeters ?? 1e3
  });
  return simulateConditionalConnectivity({
    seed: input.observation,
    offshoreFlow,
    nearshorePolicy,
    navigability,
    gate: input.gate,
    config: input.config
  });
}
function createNearshorePolicy(nearshore) {
  const provider = new GriddedFlowFieldProvider(
    nearshore.currents.map(normalizePublicCurrentRecord)
  );
  if (nearshore.mode === "residualAdd") {
    if (nearshore.isResidual !== true) {
      throw new RiskZoneValidationError(
        "nearshore.isResidual",
        "must be true when mode is residualAdd"
      );
    }
    return { zone: nearshore.zone, mode: "residualAdd", isResidual: true, provider };
  }
  return { zone: nearshore.zone, mode: "replace", provider };
}
function requiredDate(value, field) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    throw new RiskZoneValidationError(field, "must be an ISO-8601 timestamp");
  }
  return date;
}
function validateFinite(value, field) {
  if (!Number.isFinite(value)) {
    throw new RiskZoneValidationError(field, "must be finite");
  }
}

// src/index.ts
var CONDITIONAL_CONNECTIVITY_DISCLAIMER = "This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.";

// src/bridge/cli.ts
var BRIDGE_VERSION = "risk-zone-bridge-v1";
var ENGINE_VERSION = "risk-zone-connectivity-v1";
function buildCurrents(request, seed) {
  const { domain, field, ensemble } = request;
  const start = new Date(seed.reference_time);
  const maximumHours = Math.max(...request.horizons_h);
  const end = new Date(start.valueOf() + maximumHours * 36e5);
  const corners = [
    [domain.lon_min, domain.lat_min],
    [domain.lon_min, domain.lat_max],
    [domain.lon_max, domain.lat_min],
    [domain.lon_max, domain.lat_max],
    [(domain.lon_min + domain.lon_max) / 2, (domain.lat_min + domain.lat_max) / 2]
  ];
  const records = [];
  for (const validAt of [start, end]) {
    for (const [longitude, latitude] of corners) {
      records.push({
        issuedAt: field.issued_at,
        validAt: validAt.toISOString(),
        longitude,
        latitude,
        depthMeters: ensemble.depth_m,
        uMetersPerSecond: field.u_ms,
        vMetersPerSecond: field.v_ms
      });
    }
  }
  return records;
}
function buildBathymetry(request) {
  const { domain, navigability } = request;
  const points = [];
  const columns = Math.round((domain.lon_max - domain.lon_min) / domain.spacing_deg);
  const rows = Math.round((domain.lat_max - domain.lat_min) / domain.spacing_deg);
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      points.push({
        longitude: domain.lon_min + column * domain.spacing_deg,
        latitude: domain.lat_min + row * domain.spacing_deg,
        depthMeters: navigability.flat_depth_m
      });
    }
  }
  return points;
}
function gateBearingDegrees(request) {
  if (request.gate.bearing_deg !== null && request.gate.bearing_deg !== void 0) {
    return request.gate.bearing_deg;
  }
  const { u_ms, v_ms } = request.field;
  if (u_ms === 0 && v_ms === 0) return 0;
  const travelBearing = Math.atan2(u_ms, v_ms) * 180 / Math.PI;
  return (travelBearing + 90 + 360) % 360;
}
function buildGate(request, zone) {
  return {
    kind: "center",
    center: [zone.lon, zone.lat],
    widthMeters: request.gate.width_m,
    bearingDegrees: gateBearingDegrees(request),
    minDepthMeters: request.gate.min_depth_m,
    maxDepthMeters: request.gate.max_depth_m
  };
}
function runOne(request, seed, zone) {
  return calculateRiskZone({
    observation: {
      observedAt: seed.reference_time,
      species: request.ensemble.species,
      geometry: { kind: "point", position: [seed.lon, seed.lat] },
      depthMeters: request.ensemble.depth_m,
      confidence: request.ensemble.confidence,
      ensembleSize: request.ensemble.size,
      positionUncertaintyMeters: request.ensemble.position_uncertainty_m
    },
    offshoreCurrents: buildCurrents(request, seed),
    coast: {
      landPolygons: request.navigability.land_polygons,
      bathymetryPoints: buildBathymetry(request),
      minimumWaterDepthMeters: request.navigability.minimum_water_depth_m,
      maximumBathymetryLookupMeters: request.navigability.lookup_radius_m
    },
    gate: buildGate(request, zone),
    config: {
      horizonsHours: [...request.horizons_h].sort((left, right) => left - right),
      timeStepMinutes: request.config.time_step_minutes,
      snapshotIntervalMinutes: request.config.snapshot_interval_minutes,
      regionCellSizeMeters: request.config.region_cell_size_m,
      randomSeed: request.config.random_seed
    }
  });
}
function runBridge(request) {
  if (request.request_version !== BRIDGE_VERSION) {
    throw new Error(`unsupported request_version: ${request.request_version}`);
  }
  if (request.seeds.length === 0) throw new Error("seeds must not be empty");
  if (request.zones.length === 0) throw new Error("zones must not be empty");
  const sortedSeeds = [...request.seeds].sort(
    (left, right) => left.seed_id < right.seed_id ? -1 : left.seed_id > right.seed_id ? 1 : 0
  );
  const horizons = [...request.horizons_h].sort((left, right) => left - right);
  const seedResults = sortedSeeds.map((seed) => {
    const byZone = /* @__PURE__ */ new Map();
    for (const zone of request.zones) byZone.set(zone.zone_id, runOne(request, seed, zone));
    const geometryRun = byZone.get(request.zones[0].zone_id);
    return { seed, byZone, geometryRun };
  });
  const particles = seedResults.flatMap(
    ({ seed, geometryRun }) => geometryRun.particleTrajectories.map((trajectory) => ({
      seed_id: seed.seed_id,
      particle_id: trajectory.id,
      status: trajectory.status,
      coordinates: trajectory.coordinates.map(([longitude, latitude]) => [longitude, latitude])
    }))
  );
  const gates = {};
  for (const zone of request.zones) {
    let previousHorizon = 0;
    let firstCrossingWindow = null;
    const perHorizon = horizons.map((horizonHours) => {
      let connected = 0;
      let total = 0;
      const statusCounts = {};
      for (const { byZone } of seedResults) {
        const summary = byZone.get(zone.zone_id).horizonSummaries.find((item) => item.horizonHours === horizonHours);
        if (!summary) throw new Error(`missing horizon summary for ${horizonHours}h`);
        connected += summary.firstGateCrossingCount;
        total += request.ensemble.size;
        for (const [status, count] of Object.entries(summary.particleStatusCounts)) {
          statusCounts[status] = (statusCounts[status] ?? 0) + count;
        }
      }
      if (connected > 0 && firstCrossingWindow === null) {
        firstCrossingWindow = {
          from_h: previousHorizon,
          to_h: horizonHours,
          basis: "requested_horizon_bracket"
        };
      }
      previousHorizon = horizonHours;
      return {
        horizon_h: horizonHours,
        connected_members: connected,
        members_total: total,
        display_string: `${connected} of ${total}`,
        particle_status_counts: statusCounts
      };
    });
    gates[zone.zone_id] = {
      by_horizon: perHorizon,
      first_crossing_window: firstCrossingWindow,
      unavailable_reason: firstCrossingWindow === null ? "no_crossing_within_horizons" : null
    };
  }
  const first = seedResults[0].geometryRun;
  return {
    engine_version: ENGINE_VERSION,
    bridge_version: BRIDGE_VERSION,
    gate_bearing_deg: gateBearingDegrees(request),
    gate_width_m: request.gate.width_m,
    classification: first.classification,
    disclaimer: first.disclaimer,
    time_step_minutes: request.config.time_step_minutes,
    horizons_h: horizons,
    ensemble_size_per_seed: request.ensemble.size,
    particles,
    gates,
    diagnostics: seedResults.flatMap(
      ({ seed, geometryRun }) => geometryRun.diagnostics.map((diagnostic) => ({ seed_id: seed.seed_id, ...diagnostic }))
    )
  };
}

// src/bridge/entry.ts
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}
async function main() {
  try {
    const request = JSON.parse(await readStdin());
    process.stdout.write(JSON.stringify({ ok: true, result: runBridge(request) }));
  } catch (error) {
    process.stdout.write(
      JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) })
    );
    process.exitCode = 1;
  }
}
void main();
