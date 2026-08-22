# 원전 취수구 조건부 연결영역 MVP

관측된 해양생물 군집을 시간별 유동장으로 전진 이동시켜, 원전 측 가상 감시 게이트와의 **조건부 연결영역**을 계산하는 TypeScript 라이브러리입니다.

이 모듈은 해양생물 개체수나 원전 취수구 막힘 가능성을 예측하지 않습니다. 입력된 관측·해류·지형·게이트 조건에서 입자들이 연결되는지를 계산하는 엔진입니다.

> This output is a conditional particle-connectivity calculation under supplied observation, flow, navigability, and gate assumptions. It is not an estimate of organism abundance, intake blockage probability, or facility risk.

## 실행

~~~bash
npm install
npm test
npm run build
npm run example
~~~

npm run example은 네트워크를 호출하지 않는 일정한 동향 해류와 열린 바다 제약으로 결과 JSON을 출력합니다.

## MVP 입력 계약

| 필요한 데이터 | 엔진 입력 | 필수로 정규화할 값 | 역할 |
| --- | --- | --- | --- |
| 해양생물 군집 관측정보 | ObservationSeed | 관측시각, 점 또는 폴리곤, 종, 관측/가정 수심, 신뢰도 | 입자 출발 위치와 개수 설정 |
| 시간별 해류 예측장 | FlowFieldProvider | 예보 발표시각, 유효시각, 위경도, 수심, u/v | 2/4/24/48시간 전진 이동 |
| 연안 조류 예측 | NearshoreFlowPolicy | 시간별 u/v, 적용 폴리곤, 조석 역전 반영 벡터 | 취수구 인근 유동장 교체 또는 명시적 잔차 보정 |
| 수심·해안선 | NavigabilityProvider | 수심, 육지 폴리곤, 최소 통과 수심 | 육지·얕은 물·미관측 수역 이동 차단 |
| 가상 감시 게이트 | MonitoringGate | 선분 또는 중심/폭/방향, 깊이 범위 | 첫 게이트 교차와 ETA 계산 |

모든 위치는 GeoJSON 순서인 [longitude, latitude]입니다. 시간은 ISO-8601 UTC 문자열이고, 속도는 m/s입니다. u는 동쪽, v는 북쪽을 양수로 합니다. 원천 API가 “향하는 방향” 대신 “불어오는/흘러오는 방향”을 제공하면 어댑터에서 180도를 변환한 뒤 u/v로 바꿔야 합니다.

## 외부 데이터 연결 방식

계산 엔진은 API 키를 보관하거나 HTTP 호출을 하지 않습니다. 수집 코드에서 데이터를 정규화한 뒤 다음 인터페이스를 구현해 주입합니다.

~~~ts
const romsAdapter: FlowFieldProvider = {
  velocityAt({ position, depthMeters, validAt }) {
    // ROMS 레코드를 위치·수심·유효시각으로 찾고, 방향/속도를 u/v로 변환한다.
    // 관측 범위 밖이면 null을 반환한다. 0 m/s를 null로 바꾸지 않는다.
    return { uMetersPerSecond, vMetersPerSecond, sourceTime, validAt };
  },
};

const coastAdapter: NavigabilityProvider = {
  canTraverse({ from, to, particleDepthMeters, at }) {
    // 전체 선분이 육지, 얕은 수역, 수심 미관측 범위를 통과하는지 판정한다.
    return { passable: true };
  },
};
~~~

GriddedFlowFieldProvider는 해커톤 fixture나 정규화된 격자 레코드에 사용할 수 있는 기본 구현입니다. 요청 시각 전후의 동일 수심 기록을 시간 선형보간하고, 각 시각에서는 가장 가까운 격자점을 사용합니다. 공간 이중선형 보간은 이 MVP에 포함하지 않습니다.

### ROMS와 조류도는 자동 합산하지 않습니다

기본 해류가 조석을 이미 포함할 수 있으므로, 연안 조류는 다음 중 하나만 선택합니다.

- replace: 연안 적용 폴리곤 내부에서 해류장을 연안 조류장으로 교체합니다. 기본 권장 방식입니다.
- residualAdd: 연안 데이터가 기본 해류에 포함되지 않은 **잔차 벡터**임을 데이터 어댑터가 보장할 때만 합산합니다. isResidual: true가 필요합니다.

## 결과 해석

simulateConditionalConnectivity(input)은 다음을 반환합니다.

- horizonSummaries: 각 2/4/24/48시간의 conditionalGateConnectionFraction, 첫 게이트 도달 개수, ETA p10/p50/p90, 입자 상태 수
- snapshots: 시간별 점유 격자를 8방향으로 군집화한 GeoJSON FeatureCollection<MultiPolygon>
- particleTrajectories: 입자별 경로, 최종 상태, 첫 게이트 도달시각
- diagnostics: 해류 범위 누락, 해안선·수심 통과 거절, 살아 있는 입자 없음 등의 계산 근거

conditionalGateConnectionFraction은 시뮬레이션 입자 중 감시 게이트를 처음 교차한 비율입니다. 막힘 확률, 시설 위험도, 생물량, 실제 취수구 도달 여부로 해석하면 안 됩니다.

입자가 해류 범위 밖이면 outside-flow-coverage, 육지·얕은 수역·지형 데이터 범위 밖이면 각각 대응하는 종료 상태가 됩니다. 엔진은 누락 데이터를 정지 해류나 열린 바다로 추정하지 않습니다.

## 간단한 사용 예

~~~ts
const result = simulateConditionalConnectivity({
  seed: {
    observedAt: '2026-08-23T00:00:00.000Z',
    species: 'jellyfish',
    geometry: { kind: 'point', position: [129, 37] },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 100,
    positionUncertaintyMeters: 500,
  },
  offshoreFlow: romsAdapter,
  navigability: coastAdapter,
  gate: {
    kind: 'endpoints',
    start: [129.1, 36.98],
    end: [129.1, 37.02],
    minDepthMeters: 0,
    maxDepthMeters: 10,
  },
});
~~~

설계 결정과 세부 입력·오류 처리 기준은 docs/superpowers/specs/2026-08-23-nuclear-intake-risk-zone-design.md에서 확인할 수 있습니다.
