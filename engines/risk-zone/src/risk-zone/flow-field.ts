import { distanceMeters, pointInPolygon } from './geo.js';
import type {
  FlowFieldProvider,
  GriddedFlowSample,
  NearshoreFlowPolicy,
  VelocityRequest,
  VelocitySample,
} from './types.js';

/**
 * Fixture and adapter-friendly field that performs temporal interpolation
 * between the nearest spatial records at each bracketing valid time.
 */
export class GriddedFlowFieldProvider implements FlowFieldProvider {
  constructor(private readonly samples: readonly GriddedFlowSample[]) {}

  velocityAt(request: VelocityRequest): VelocitySample | null {
    const compatible = this.samples.filter((sample) => sample.depthMeters === request.depthMeters);
    if (compatible.length === 0) return null;

    const requestedTime = request.validAt.valueOf();
    const earlierTimes = compatible
      .map((sample) => sample.validAt.valueOf())
      .filter((time) => time <= requestedTime);
    const laterTimes = compatible
      .map((sample) => sample.validAt.valueOf())
      .filter((time) => time >= requestedTime);
    if (earlierTimes.length === 0 || laterTimes.length === 0) return null;

    const earlierTime = Math.max(...earlierTimes);
    const laterTime = Math.min(...laterTimes);
    const earlier = nearestSample(
      compatible.filter((sample) => sample.validAt.valueOf() === earlierTime),
      request,
    );
    const later = nearestSample(
      compatible.filter((sample) => sample.validAt.valueOf() === laterTime),
      request,
    );
    if (!earlier || !later) return null;

    const intervalMilliseconds = laterTime - earlierTime;
    const ratio = intervalMilliseconds === 0 ? 0 : (requestedTime - earlierTime) / intervalMilliseconds;
    return {
      uMetersPerSecond: interpolate(earlier.uMetersPerSecond, later.uMetersPerSecond, ratio),
      vMetersPerSecond: interpolate(earlier.vMetersPerSecond, later.vMetersPerSecond, ratio),
      sourceTime: earlier.sourceTime,
      validAt: request.validAt,
    };
  }
}

export function effectiveVelocityAt(
  request: VelocityRequest,
  offshore: FlowFieldProvider,
  policy?: NearshoreFlowPolicy,
): VelocitySample | null {
  const offshoreVelocity = offshore.velocityAt(request);
  if (!policy || !pointInPolygon(request.position, policy.zone.rings)) {
    return offshoreVelocity;
  }

  const nearshoreVelocity = policy.provider.velocityAt(request);
  if (!nearshoreVelocity) return null;
  if (policy.mode === 'replace') return nearshoreVelocity;
  if (!offshoreVelocity) return null;

  return {
    uMetersPerSecond: offshoreVelocity.uMetersPerSecond + nearshoreVelocity.uMetersPerSecond,
    vMetersPerSecond: offshoreVelocity.vMetersPerSecond + nearshoreVelocity.vMetersPerSecond,
    sourceTime: offshoreVelocity.sourceTime,
    validAt: request.validAt,
  };
}

function nearestSample(
  samples: readonly GriddedFlowSample[],
  request: VelocityRequest,
): GriddedFlowSample | undefined {
  return samples.reduce<GriddedFlowSample | undefined>((closest, sample) => {
    if (!closest) return sample;
    return distanceMeters(sample.position, request.position) < distanceMeters(closest.position, request.position)
      ? sample
      : closest;
  }, undefined);
}

function interpolate(start: number, end: number, ratio: number): number {
  return start + (end - start) * ratio;
}
