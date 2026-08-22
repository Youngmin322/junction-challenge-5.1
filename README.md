# 원전 취수구 조건부 연결영역 MVP

공공데이터 행을 넣어 원전 측 가상 감시 게이트까지의 **조건부 연결영역**을 계산합니다. 사용하는 함수는 하나입니다.

~~~ts
const result = calculateRiskZone(publicData);
~~~

> 이 결과는 주어진 관측·해류·지형·게이트 조건에서의 입자 연결 계산입니다. 생물량, 취수구 막힘 확률, 시설 위험도를 뜻하지 않습니다.

## 실행

~~~bash
npm install
npm test
npm run build
npm run example
~~~

## 공공데이터를 넣는 단순 구조

~~~ts
calculateRiskZone({
  observation,       // ① 관측 군집
  offshoreCurrents, // ② 시간별 해류
  nearshore,         // ③ 연안 조류: 선택
  coast,             // ④ 수심·해안선
  gate,              // ⑤ 가상 감시 게이트
});
~~~

| 데이터 | 넣는 위치 | 꼭 필요한 값 |
| --- | --- | --- |
| 해양생물 군집 관측 | observation | 관측시각, 점/폴리곤, 종, 수심, 신뢰도 |
| 시간별 해류 예측 | offshoreCurrents | 발표시각, 유효시각, 위경도, 수심, u/v 또는 유향·유속 |
| 연안 조류 예측 | nearshore | 적용 폴리곤, 시간별 해류 행, mode |
| 수심·해안선 | coast | 육지 폴리곤, 수심 점, 최소 통과 수심 |
| 가상 감시 게이트 | gate | 선분 또는 중심/폭/방향, 깊이 범위 |

모든 좌표는 [longitude, latitude] 순서이고, 시간은 ISO-8601 UTC, 속도는 m/s입니다.

## 가장 작은 입력 예

~~~ts
const result = calculateRiskZone({
  observation: {
    observedAt: '2026-08-23T00:00:00Z',
    species: 'jellyfish',
    geometry: { kind: 'point', position: [129, 37] },
    depthMeters: 1,
    confidence: 0.8,
    ensembleSize: 100,
    positionUncertaintyMeters: 500,
  },

  offshoreCurrents: [
    {
      issuedAt: '2026-08-23T00:00:00Z',
      validAt: '2026-08-23T00:00:00Z',
      longitude: 129,
      latitude: 37,
      depthMeters: 1,
      speedMetersPerSecond: 0.8,
      directionDegrees: 90,
      directionConvention: 'toward',
    },
    // 다음 유효시각 행들
  ],

  coast: {
    landPolygons: [],
    bathymetryPoints: [{ longitude: 129, latitude: 37, depthMeters: 30 }],
    minimumWaterDepthMeters: 3,
  },

  gate: {
    kind: 'endpoints',
    start: [129.1, 36.98],
    end: [129.1, 37.02],
    minDepthMeters: 0,
    maxDepthMeters: 10,
  },
});
~~~

해류 행은 이미 u/v가 있다면 uMetersPerSecond와 vMetersPerSecond를 넣으면 됩니다. 유향·유속만 있다면 speedMetersPerSecond, directionDegrees, directionConvention을 넣습니다.

- directionConvention: toward는 향하는 방향, from은 불어오거나 흘러오는 방향입니다.
- 유향의 기준이 데이터마다 다를 수 있으므로, 이 값을 확인하지 못하면 계산하지 말고 원본 메타데이터를 먼저 확인합니다.

## 연안 조류

nearshore는 취수구 주변에만 더 상세한 조류 자료가 있을 때 넣습니다.

~~~ts
nearshore: {
  zone: {
    kind: 'polygon',
    rings: [[[129.05, 36.95], [129.15, 36.95], [129.15, 37.05], [129.05, 37.05], [129.05, 36.95]]],
  },
  currents: nearshoreCurrentRows,
  mode: 'replace',
}
~~~

기본 mode는 replace입니다. 기본 해류와 연안 조류를 자동으로 더하지 않습니다. residualAdd는 연안 데이터가 기본 해류에 포함되지 않은 잔차라는 것이 확인된 경우에만 isResidual: true와 함께 사용합니다.

## 수심·해안선

landPolygons는 [폴리곤][링][좌표] 구조입니다. 수심 점은 가장 가까운 값을 사용하고, 기본적으로 5km보다 멀면 데이터 범위 밖으로 처리합니다. 해안선, 얕은 수심, 수심 데이터 범위 밖을 통과하려는 입자는 그 자리에서 종료됩니다. 이 모듈은 빈 수심 데이터를 열린 바다로 간주하지 않습니다.

## 결과

result에는 다음만 보면 됩니다.

- horizonSummaries: 2/4/24/48시간별 게이트 연결 비율과 ETA p10/p50/p90
- snapshots: 시간별 GeoJSON MultiPolygon 연결영역
- particleTrajectories: 입자 경로와 종료 상태
- diagnostics: 해류·수심 범위 누락과 해안선/얕은 수심 거절 이유

conditionalGateConnectionFraction은 시뮬레이션 입자 중 가상 게이트를 처음 지난 비율입니다. 실제 막힘 확률이 아닙니다.

더 큰 예시는 examples/conditional-connectivity.ts에 있습니다. 내부 계산 모듈은 고급 보정이나 별도 API 어댑터가 필요할 때만 사용하면 됩니다.
