# 조건부 연결영역 시나리오 지도

가상 해양생물 군집을 시간별 해류에 따라 전진시키고, 최초 도달 시간을 격자로 표현하는 해커톤용 지도 데모입니다.

> 이 화면의 모든 시나리오·해안선·해류는 가상입니다. 표시되는 색은 실제 취수구 막힘 확률이나 시설 위험도가 아니라, 입력 가정 아래 입자가 해당 격자에 처음 도달한 시점을 뜻합니다.

## 실행

```bash
npm install
npm run demo
```

브라우저에서 Vite가 출력하는 주소를 엽니다. 배포 번들을 만들려면 아래 명령을 사용합니다.

```bash
npm run demo:build
```

## 화면에서 보는 것

- `동쪽 확산`: 일정한 동북동 흐름
- `조류 반전`: 4시간 후 남동쪽으로 흐름 변화
- `해안 차단`: 가상 해안선·얕은 수역에서 입자 이동 중단
- 시간 슬라이더: 선택한 시간 이내에 최초 도달한 격자만 표시

색상은 최초 도달 시간 기준입니다. 짙은 적색은 2시간 이내, 그 뒤로 4시간·24시간·48시간 순으로 옅어집니다. 붉은 격자는 확률 또는 생물량이 아니라 조건부 이동 범위입니다.

## 실제 데이터로 바꿀 위치

데모의 입력은 [src/scenarios.ts](./src/scenarios.ts)에 모여 있습니다. 각 시나리오의 `SimulationInput`만 실제 공급자로 교체하면 지도 렌더러는 그대로 재사용됩니다.

| 입력 | 구현할 어댑터 | `SimulationInput` 연결 위치 |
|---|---|---|
| 관측 군집 | 관측 시각·점/폴리곤·종·수심·신뢰도를 `ObservationSeed`로 정규화 | `seed` |
| 외해 해류 | 시각·위치·수심으로 `u/v`를 반환하는 공급자 | `offshoreFlow.velocityAt` |
| 연안 조류 | 연안 폴리곤 안에서 외해 해류를 교체하거나 잔차만 보정 | `nearshorePolicy` |
| 수심·해안선 | 다음 입자 위치가 이동 가능한지를 판정 | `navigability.canTraverse` |
| 감시 게이트 | 취수구 전면의 가상 선분 또는 중심·폭 | `gate` |

해류와 조류는 하나의 일관된 유동장으로 다뤄야 합니다. 이미 조석을 포함한 해류에 조류 벡터를 그대로 더하지 말고, `nearshorePolicy`의 `replace` 또는 `residualAdd` 정책으로 명시적으로 선택합니다.

## 출력 데이터

`simulateConditionalConnectivity(input)`은 지도에 필요한 다음 결과를 반환합니다.

- `earliestArrivalBands`: 각 격자의 최초 도달 시간과 `within-2h` / `within-4h` / `within-24h` / `within-48h` 밴드
- `particleTrajectories`: 가상 앙상블 입자의 이동 경로
- `horizonSummaries`: 게이트 조건부 도달 비율과 ETA p10/p50/p90
- `snapshots`: 시간별 연결영역

지도는 `earliestArrivalBands`를 슬라이더 시간으로 필터링해 그립니다. 이후 실제 API 연동 시에는 공급자만 교체하고, 이 GeoJSON 형태의 출력 계약은 유지합니다.
