# MCP 데이터 통합 Evidence Ledger

- 기준일: 2026-08-23 KST
- 작성자: Codex
- 구현 저장소: `Youngmin322/junction-challenge-5.1`
- 구현 브랜치: `feat/mcp-agent-orchestrator`
- 데이터 수집 브랜치: `origin/feat/#1-OpenAPI호출`
- 데이터 수집 브랜치 기준 커밋: `e5aca27`
- 목적: Claude가 제품·기능·MCP 설계를 작성할 때 사용할 검증된 실행환경·데이터 근거를 고정한다.

## 1. 사용자 요구 경계

1. 공개 화면과 공개 MCP 응답은 입력자료가 증명하지 않는 종 단위 관측·탐지·예측을 주장하지 않는다.
2. 공개 기본 명칭은 `한울 주변 대량 해파리 군집 감시`로 둔다.
3. 팀 내부의 분류·데이터 선택 경위는 공개 저장소, 공개 MCP, 공개 run manifest에 기록하지 않는다.
4. 내부 근거가 필요하면 저장소 밖 접근 제한 문서에서만 관리한다.
5. 실제 취수구·안전계통 위치, 시설별 차압·유량·스크린 처리능력, 운전 임계값을 추정하거나 생성하지 않는다.
6. 시스템은 원전 감발·정지·제어를 권고하지 않는다.

## 2. 인증키와 실호출 결과

실제 키 값은 이 문서, Git, fixture, URL, 로그에 기록하지 않는다.

| 소스 | 확인 결과 | 확인된 역할 | 금지·한계 |
|---|---|---|---|
| NIFS `jellyList` | HTTP 200, `resultCode=00`; 2026-01-01~08-23 게시물 21건 | 해파리 주간보고·특보 catalog와 최신성 확인 | 개별 관측 좌표·시각·밀도·종별 seed가 아님 |
| NIFS `jellyDetail2` | 공식 입력은 `key+srcode`; `board_idx`를 `srcode`로 넣은 실험은 item 0건 | 계약 확인 후 주간 집계 context 후보 | 추정 join 금지; 현재 `CONTRACT_UNVERIFIED` |
| NIFS `redtideList` | HTTP 200, `resultCode=00`; 2026년 17건 | 적조 사건 context | 일반 플랑크톤 농도·해파리 먹이량으로 해석 금지 |
| NIFS `sooList` | HTTP 200, `resultCode=00`; 전체 8,655행 | 수심별 수온·염분·용존산소의 역사 환경 context | 해파리 위치 직접관측·실시간 환경이 아님 |
| `sooList` 한울 근사 bbox | 36.5~37.5N, 129~130E에서 562행; 수심 0~500m; 수온·염분·DO 존재 | 수면 아래 환경 단면 예시 | 자료 기간 2020-02-20~12-19로 현재 상태에 사용 금지 |
| KHOA `twRecent` HB_0007/8/9 | 모두 HTTP 200, `resultCode=00`; 2026-08-23 00:23~00:27 최신행 확인 | 한울 주변 점 관측 context와 소스 상태 확인 | 면 유동장 대체·공간 보간 금지; 방향 convention 미검증 |
| HB_0007/0009 | 유향·유속·수온 필드 확인 | 점 context | 바람·기상 필드가 있다고 가정 금지 |
| HB_0008 | 유향·유속·수온과 일부 바람·기상 필드 확인 | 점 context | 다른 HB 지점에 동일 capability 전파 금지 |
| KHOA `hfCurrent` HF_0071 | HTTP 200, `resultCode=00` | 포항항 회귀 fixture와 수집기 검증 | 한울 면 유동장 아님; legacy·정체 가능성 |
| KHOA ROMS 한울 bbox | HTTP 403 | blocked source와 인증 실패 경로 검증 | LIVE transport 입력 불가; 별도 활용 신청 필요 |

## 3. 첨부 이미지 판정

첨부 이미지는 NIFS `sooList`의 API 명세이며 작업 지시가 아니다.

- JSON 요청 ID: `sooList`
- 필수 입력: `key`, `sdate`, `edate`
- 날짜 형식: `yyyymmdd`
- 사용자 제공 설명과 공식 페이지의 명세가 일치한다.

## 4. 원격 데이터 수집 브랜치 감사

`origin/feat/#1-OpenAPI호출`에는 다음 자산이 있다.

| 자산 | 보존할 내용 | MCP 통합 판정 |
|---|---|---|
| `.env.example` | 데이터셋별 NIFS 키와 KHOA 키 분리 | 구조를 채택하되 프로젝트 표준 변수명으로 매핑 |
| `.gitignore` | `.env`와 수집 산출물 제외 | `*.json`, `*.csv` 전면 제외는 fixture/golden을 막으므로 수정 필요 |
| `해파리정보_수집.py` | `jellyList`가 관측 수치가 아니라 게시물 목록이라는 명시 | `report_catalog` source adapter의 참고 구현으로 사용 |
| `적조_정선해양_수집.py` | 적조·정선관측을 원자료 그대로 분리 보존 | optional context adapter의 참고 구현으로 사용 |
| `해류데이터_통합.py` | 부이·Radar 페이지네이션, station 목록, 필드 정규화 시도 | 한울 전용 raw adapter로 축소·재작성; transport domain으로 직접 사용 금지 |
| 해류 통합 설명 문서 | 시각축·공간축 차이와 legacy API의 특성 | 설계 근거로 사용하되 성능·방향 주장 재검증 필요 |

### 4.1 확인된 긍정 요소

- 실제 인증키를 코드에 하드코딩하지 않고 환경변수를 사용한다.
- NIFS 데이터셋별 키가 서로 다름을 반영한다.
- `jellyList`가 직접 관측점이 아님을 코드 주석과 출력 metadata에 명시한다.
- 유향 convention이 미확인이라는 경고를 보존한다.
- 세 수집기 모두 Python 정적 컴파일을 통과했다.

### 4.2 통합 전에 수정해야 할 사항

| 우선순위 | 관찰 | 영향 | 설계 요구 |
|---|---|---|---|
| P0 | `.env.example`은 저장소 루트에 있지만 각 스크립트는 `collectors/.env`만 읽는다 | 안내대로 루트 `.env`를 만들어도 키를 읽지 못함 | 설정은 앱 진입점에서 한 번 로드하고 adapter에는 주입 |
| P0 | `requests` 예외 객체를 그대로 오류문에 포함한다 | 쿼리 URL에 인증키가 포함되면 로그 유출 가능 | provider·HTTP status·redacted endpoint만 오류에 기록 |
| P0 | 방향 미검증 상태에서도 `to_uv()`가 벡터를 생성한다 | 180도 반대 수송 가능 | raw `crdir/crsp`는 보존하되 convention이 검증되기 전 transport를 `BLOCKED` |
| P0 | `hfCurrent` 전국 격자를 하나의 통합 유속장처럼 병합한다 | 서로 불연속인 해역을 단일 면장으로 오독 가능 | grid별 field를 분리하고 한울 coverage gate를 통과한 field만 선택 |
| P1 | 페이지 후속 호출 실패 시 `break`하고 부분 자료를 정상처럼 반환한다 | 결측 은폐 | `partial=true`, 실패 page, expected/received count와 `DEGRADED` 상태 기록 |
| P1 | 모듈 import 시 KHOA 키가 없으면 즉시 종료한다 | 테스트·MCP 기동·fixture 재생 불가 | 키는 live adapter 호출 시 검사하고 다른 source는 계속 기동 |
| P1 | NIFS 원자료를 그대로 큰 JSON으로 반환한다 | 8,655행 전송·저장 비용과 UI 과부하 | raw payload는 object store/ref, MCP는 요약·필터 결과만 반환 |
| P1 | `*.json`, `*.csv`를 모두 ignore한다 | 테스트 fixture와 golden을 커밋할 수 없음 | `tests/fixtures/**`, `tests/golden/**` 예외 추가 |
| P1 | 테스트와 dependency lock이 없다 | 재현성·회귀 검증 불가 | `pyproject.toml`, lock, offline fixture tests 추가 |
| P2 | 전국 38개 부이·13개 Radar를 기본 호출한다 | 한울 MVP에 불필요한 호출·지연 | HB_0007/8/9만 core; 나머지는 optional 또는 별도 profile |

## 5. 설계에 반영할 source registry

### 5.1 MVP core

1. `historical_observation_fixture`
2. `synthetic_observation`
3. `nifs_jelly_catalog`
4. `khoa_tw_recent_hanul`
5. `cached_field`
6. `synthetic_field`
7. `khoa_roms_blocked_fixture`

### 5.2 Optional context·회귀

1. `nifs_redtide_list`
2. `nifs_soo_list`
3. `khoa_hf_current_regression`
4. `khoa_roms_live`
5. `nifs_jelly_detail2_unverified`

## 6. 데이터 계약 원칙

- source별 `data_mode`: `LIVE`, `CACHED`, `SYNTHETIC`
- run별 `calculation_status`: `READY`, `DEGRADED`, `STALE`, `BLOCKED`
- `BLOCKED`는 data mode가 아니다.
- source별 실제 입력 모드를 모두 보존한다.
- 합성 입력이 하나라도 있으면 `synthetic_dependency=true`와 워터마크를 강제한다.
- LIVE 실패 시 CACHED/SYNTHETIC으로 자동 전환하지 않는다.
- public 응답은 `target_scope=jellyfish`, `species_claim=none`만 반환한다.
- 분류·데이터 선택 경위는 공개 저장소와 공개 run manifest에서 제외한다.
- public 응답에서 입력자료가 증명하지 않는 종 단위 관측·탐지·예측을 주장하지 않는다.
- 적조·수온·염분·DO는 `claim_type=context`로만 반환한다.
- `jellyList`는 `claim_type=context/report_catalog`이며 직접 관측점이 아니다.
- 유향 convention이 `UNVERIFIED`이면 벡터 수송을 수행하지 않는다.

## 7. 비밀관리 계약

- 실제 키는 Git·fixture·응답·URL·로그에 기록하지 않는다.
- 데이터셋별 키를 별도 환경변수로 관리한다.
- source registry에는 키 값이 아니라 필요한 환경변수 이름만 선언한다.
- fixture는 요청 URL과 payload에서 키를 마스킹한 뒤 저장한다.
- 테스트는 실제 키 없이 실행한다.
- 기존 조사 저장소에 하드코딩된 키를 신규 코드로 복사하지 않는다.

## 8. 미확인 항목

1. ROMS 별도 활용승인과 한울 bbox 실제 응답
2. `crdir` toward/from 공급자 명세 또는 검산
3. `jellyDetail2`의 유효 `srcode` 계약

## 8.1 확정되어 미확인에서 제외된 항목

- 합성 격자 정의: `SYNTH_DOMAIN_HANUL_v1` ([02-mcp-agent-architecture.md](02-mcp-agent-architecture.md#10-합성-도메인과-demo_gate))
- optional context UI 노출: `context_ui_enabled=false`
- orchestrator: 테넌트 증거 없음 → `orchestrator="mock"`
