# 한울 해파리 감시 MCP·에이전트 승인 설계

- 설계 기준일: 2026-08-23 KST
- 구현 저장소: `https://github.com/Youngmin322/junction-challenge-5.1.git`
- 작업 브랜치: `feat/mcp-agent-orchestrator`
- 상태: Claude 설계 작성 → Codex 구현성 검증 → Claude F1~F13 전부 수용
- 근거 원장: [01-data-integration-evidence.md](01-data-integration-evidence.md)

## 0. 협업 프로토콜 적용 기록

이 문서는 다음 역할 경계로 작성했다.

- Claude: 제품·UI·기능 요구 해석과 전체 아키텍처·계획 작성
- Codex: 실제 API 응답, 원격 브랜치 코드, 실행환경, 데이터 계약, 테스트 가능성 검증
- Codex는 Claude 설계를 대신 다시 쓰지 않고 구체 오류만 반환했다.
- Claude는 프로젝트 파일을 수정하지 않고 F1~F13을 판정했으며 전부 수용했다.
- 자동 테스트와 원본 API·코드를 모델 간 합의보다 우선한다.
- 최종 판단은 사용자에게 있다.

기존 개발용 Claude 세션이 장시간 응답하지 않아, 기존 지시에 따라 동일 프로토콜을 전달한 새 세션 `cf820edb-4b45-4817-a510-97993293232a`에서 이어갔다.

## 1. 설계 목표와 비목표

### 목표

1. 한울 주변의 해파리 관측·보고 맥락과 해양자료를 MCP 도구로 검색·선별한다.
2. 직접관측, 보고서 목록, 점 관측, 면 유동장, 합성 시나리오를 구조적으로 구분한다.
3. 데이터가 충분할 때만 조건부 표층 이동영역과 공개 감시격자 교차를 계산한다.
4. AI가 어떤 데이터와 전제를 사용했는지 다른 AI와 사용자가 재사용·감사할 수 있게 한다.
5. REST와 MCP가 같은 도메인 서비스를 사용하고 같은 결정 결과를 반환하게 한다.

### 비목표

- 해파리 종을 입력자료보다 더 구체적으로 단정하지 않는다.
- 실제 취수구·스크린·안전계통의 위치나 임계값을 생성하지 않는다.
- 원전 정지·감발·제어를 권고하지 않는다.
- NIFS 보고서 목록을 직접관측 좌표로 취급하지 않는다.
- 적조 사건을 플랑크톤 농도나 해파리 먹이량으로 변환하지 않는다.
- 점 부이 유향·유속을 면 유동장으로 보간하지 않는다.
- 미교정 앙상블 비율을 확률, 위험도, ETA로 표현하지 않는다.

## 2. 핵심 결정

| 결정 | 승인 내용 |
|---|---|
| 애플리케이션 구조 | Python domain core와 얇은 REST·MCP adapter가 동일 application service를 공유한다. MCP가 REST를 네트워크로 재호출하지 않는다. |
| Orchestrator | 하위 도구 선택·호출·근거 요약만 수행한다. 물리 계산, 임계값 생성, 운전 판단을 하지 않는다. |
| 공개 taxonomy | `target_scope="jellyfish"`, `species_claim="none"`, 서비스명만 노출한다. 내부 분류·데이터 선택 경위는 저장소와 public manifest에서 제외한다. |
| 입력 모드 | source 단위 `LIVE`, `CACHED`, `SYNTHETIC`; 호출자가 허용한 모드만 선택한다. 자동 fallback은 없다. |
| 실행 상태 | `READY`, `DEGRADED`, `STALE`, `BLOCKED`; 선택된 필수 입력만 최상위 상태에 전파한다. |
| 실제 한울 면 유동장 | 현재 없음. ROMS는 제공키로 HTTP 403, HF_0071은 포항항이라 한울 coverage gate에서 탈락한다. |
| MVP 수송 | 합성 유동장을 명시적으로 허용한 요청에서만 조건부 시나리오로 실행한다. |
| 선택 자료 | 적조·정선관측은 context adapter로 등록하되 기본 UI에는 노출하지 않는다. |
| 원격 수집 브랜치 | merge·cherry-pick하지 않고, 검증된 endpoint·필드·station 사실만 새 adapter에 선택 이식한다. |
| 재현성 | Python 3.11+, `uv`와 `uv.lock`, 고정 시계·난수, 오프라인 fixture/golden을 사용한다. |
| MCP 전송 | Copilot Studio 연결은 HTTPS `POST /mcp`의 Streamable HTTP를 사용한다. stdio·SSE는 Copilot Studio 연결 경로로 사용하지 않는다. |

## 3. 최종 아키텍처

```text
Copilot Orchestrator / 범용 MCP Client       Web UI
                 │                             │
     HTTPS Streamable HTTP /mcp          REST /v1/*
                 │                             │
        mcp/tools/*.py                api/routers/*.py
                 └──────────┬──────────────────┘
                            │
                  domain/services/*
                            │
      ┌─────────────┬───────┼────────┬──────────────┐
      │ selection   │ gates │ fields │ observations │
      │ transport   │ zones │ intersect             │
      └─────────────┴───────┴────────┴──────────────┘
                            │
                 adapters/sources/*
                            │
        LIVE provider / CACHED fixture / SYNTHETIC
                            │
             blob·run·zone·audit stores
```

요청 흐름은 다음과 같다.

1. REST/MCP adapter가 요청을 동일한 `DomainCommand`로 변환한다.
2. selection policy가 요청의 `allowed_modes[]` 안에서 역할별 후보를 선택한다.
3. 제외된 후보도 사유와 component status를 남긴다.
4. source adapter는 원자료와 수집 metadata만 반환한다.
5. domain이 정규화·품질 gate·계산을 수행한다.
6. 선택된 필수 입력 component만 최상위 실행 상태를 결정한다.
7. `CanonicalResult`를 생성하고 public projection을 거쳐 REST/MCP로 반환한다.
8. 입력·버전·오류·체크섬은 append-only run/audit 기록으로 보존한다.

Copilot Studio는 클라우드에서 실행되므로 로컬 `localhost`를 직접 호출할 수 없다. 해커톤 데모에서는 Microsoft Dev Tunnel이 공개 HTTPS `/mcp` 요청을 로컬 port 8000으로 전달한다. 대시보드의 REST API와 저장소는 로컬 전용으로 유지한다. 연결 절차는 [04-copilot-studio-local-mcp-connection.md](04-copilot-studio-local-mcp-connection.md)를 따른다.

## 4. 패키지 구조

```text
pyproject.toml
uv.lock
.env.example
.gitignore
docs/
  01-data-integration-evidence.md
  02-mcp-agent-architecture.md
  03-remote-branch-migration-map.md
src/jellyguard/
  config/
    settings.py
    registry.py
    policy.py
    profiles.py
  contracts/
    enums.py
    errors.py
    envelope.py
    observation.py
    field_status.py
    run.py
    zone.py
    intersect.py
    explain.py
    context.py
  domain/
    selection/policy.py
    gates/evaluate.py
    gates/status.py
    observations/{normalize,dedupe,grade,qc}.py
    fields/{identity,convention,coverage}.py
    zones/{derive,version,geometry}.py
    transport/{release,integrate,terminate,envelope,seed}.py
    intersect/compute.py
    provenance/{manifest,digest,redact_view}.py
    services/
      search_observations.py
      get_field_status.py
      run_transport.py
      list_zones.py
      intersect_zone.py
      explain_run.py
      context_bundle.py
  adapters/
    sources/
      base.py
      http.py
      redact.py
      historical_observation_fixture.py
      scenario_seed_synthetic.py
      nifs_jelly_catalog.py
      nifs_jelly_detail2_unverified.py
      nifs_redtide.py
      nifs_soo.py
      khoa_tw_recent.py
      khoa_hf_current_regression.py
      khoa_roms_live.py
      khoa_roms_blocked_fixture.py
      cached_field.py
      synthetic_field.py
    store/{blob_store,run_store,observation_store,zone_store,audit_log}.py
  api/
    app.py
    routers/
  mcp/
    server.py
    tools/
  copilot/
    system_prompt.md
    tool_descriptions.md
    linter/{number_source,banned_terms,claim_labels,blocked_consistency}.py
  cli/__main__.py
tests/
  fixtures/raw/
  golden/
  contract/
  adapters/
  domain/
  equivalence/
  safety/
  demo/
  security/
```

CI는 다음 import 경계를 강제한다.

- `domain/*`는 `adapters`, `api`, `mcp`를 import하지 않는다.
- source adapter는 `os.environ`을 직접 읽지 않는다.
- `domain/*`는 시스템 시계·난수·네트워크를 직접 사용하지 않는다.
- REST/MCP adapter는 `domain.services` 외 도메인 모듈을 직접 호출하지 않는다.

## 5. 설정과 비밀관리

정확한 환경변수 이름은 다음으로 통일한다.

```dotenv
JELLYGUARD_NIFS_JELLY_KEY=
JELLYGUARD_NIFS_REDTIDE_KEY=
JELLYGUARD_NIFS_SOO_KEY=
JELLYGUARD_KHOA_KEY=
JELLYGUARD_PROFILE=hanul_public_demo
JELLYGUARD_SOURCE_MODE=fixture
JELLYGUARD_BLOB_ROOT=./runs
```

- 값은 커밋하지 않는다.
- 앱 진입점의 `settings.py`가 한 번만 읽고 adapter에 주입한다.
- 키가 없어도 서버와 fixture 테스트는 기동한다.
- live adapter를 호출할 때만 필요한 키를 검사한다.
- URL, 쿼리스트링, 요청 헤더, 예외 `repr`, 원자료 payload를 로그에 남기지 않는다.
- 오류 로그에는 provider, HTTP status, provider result code, 경로와 파라미터 이름만 남긴 redacted endpoint를 기록한다.
- 공개 배포 전 모든 provider 키를 회전한다(운영 체크리스트 항목).

## 6. Source registry

### MVP core

| source_id | class | mode | claim | 핵심 gate |
|---|---|---|---|---|
| `historical_observation_fixture` | observation | CACHED | direct_observation | 좌표·관측시각 필수 |
| `scenario_seed_synthetic` | scenario_seed | SYNTHETIC | conditional_scenario | 합성 워터마크 필수 |
| `nifs_jelly_catalog` | report_catalog | LIVE/CACHED | context | 관측 seed 사용 금지 |
| `khoa_tw_recent_hanul` | point_context | LIVE/CACHED | context | HB_0007/8/9, capability 동적 |
| `cached_field` | field | CACHED | n/a — field input | grid별 분리, 한울 coverage 필수 |
| `synthetic_field` | field | SYNTHETIC | n/a — field input | 선언된 u/v만 사용 |
| `khoa_roms_blocked_fixture` | field | CACHED | n/a — field input | 항상 `UPSTREAM_AUTH_FAILED`; 403 차단 경로 재현 |

### Optional context·회귀

| source_id | class | 역할·한계 |
|---|---|---|
| `nifs_redtide_list` | event_context | 적조 사건 목록. 플랑크톤 농도나 먹이량이 아니다. |
| `nifs_soo_list` | profile_context | 한울 근사영역의 2020년 수심별 환경맥락. 현재 상태가 아니다. |
| `khoa_hf_current_regression` | field fixture | 포항항 수집 회귀용. 한울 수송에 사용하지 않는다. |
| `khoa_roms_live` | field | 별도 활용승인 전 403. 승인 후에도 coverage·방향 gate 필요. |
| `nifs_jelly_detail2_unverified` | report_catalog | `srcode` 계약 확인 전 비활성. |

적조·정선관측은 핵심 인과 경로인 `관측 → 면 유동장 → 수송 → 감시격자 교차`의 입력이 아니다. 오독 위험과 응답량이 크므로 registry에는 존재를 명시하되 `context_ui_enabled=false`를 기본으로 한다.

## 7. 데이터 계약

### 7.1 RawPayload

```text
source_id, request_spec, redacted_endpoint,
http_status, provider_result_code,
fetched_at, issued_at?, valid_at?,
content_checksum, request_fingerprint, fixture_checksum?,
source_data_mode, adapter_version, license,
rows_received, rows_expected?,
pages_received, pages_expected?,
partial, failed_pages[]
```

체크섬은 세 의미를 분리한다.

- `content_checksum`: provider response body bytes의 SHA-256
- `request_fingerprint`: 키 값을 제거한 정규 요청명세의 SHA-256
- `fixture_checksum`: 커밋된 fixture 파일 bytes의 SHA-256

provider 본문에 비밀값이 들어오면 마스킹 뒤 content checksum을 계산하고 `content_redaction_applied=true`, `redaction_rule_version`을 남긴다.

### 7.2 직접관측과 scenario seed

직접관측 record는 다음을 모두 만족해야 한다.

```text
geometry != null
observed_at != null
source_class == observation
claim_type == direct_observation
```

`jellyList` record에는 geometry·밀도·개체수 필드를 아예 정의하지 않는다. 합성 seed도 직접관측과 섞지 않는다.

합성 seed는 REST에서 사전 등록한다.

```http
POST /v1/observations/scenario-seeds
```

```json
{
  "geometry": {},
  "reference_time": "ISO-8601",
  "seed_mode": "synthetic",
  "author_note": "...",
  "basis": "...",
  "created_by": "..."
}
```

반환된 `seed_id`만 `run_transport`에 쓸 수 있으며, 이 seed가 포함되면 합성 의존성과 워터마크를 강제한다.

### 7.3 Field

```text
field_ref = provider:grid_id:issued_at:valid_at
```

- 서로 다른 `grid_id`를 하나의 면장으로 병합하지 않는다.
- 실제 provider field는 `crdir_convention=unverified`가 기본이다.
- 공급자 명세 또는 검산 fixture가 없으면 `to_uv()`를 호출하지 않고 수송을 BLOCKED로 둔다.
- 합성 field는 `u_ms/v_ms`를 직접 선언해 방향 convention을 사용하지 않는다.
- HB 점 관측은 station별 실제 응답 필드로 capability를 매번 판별한다.

### 7.4 입력 모드

```text
selected_sources[].source_data_mode
input_mode_set[]
effective_mode
mode_derivation = max_contamination
synthetic_dependency
replay_dependency
```

`effective_mode`는 synthetic이 하나라도 있으면 `synthetic`, 아니면 cached가 있으면 `cached`, 아니면 `live`다. optional context의 모드는 계산의 `input_mode_set`에 넣지 않는다.

호출자가 `allowed_modes`에 넣지 않은 모드로 자동 대체하지 않는다. 같은 역할의 source를 여러 모드로 혼합하지 않는다.

## 8. 여섯 MCP 도구와 REST 대응

| MCP tool | REST | 역할 |
|---|---|---|
| `search_observations` | `POST /v1/observations/search` | 직접관측 검색과 별도 catalog context |
| `get_field_status` | `GET /v1/hanul/field-status` | field 후보·gate·점관측 capability·선택적 context |
| `run_transport` | `POST /v1/hanul/runs` | 등록된 seed와 선택 field의 조건부 수송 |
| `list_zones` | `GET /v1/hanul/zones` | 공개 관측점 기반 DEMO_GATE 조회 |
| `intersect_zone` | `POST /v1/hanul/runs/{run_id}/intersect` | 앙상블 member와 DEMO_GATE 교차 |
| `explain_run` | `GET /v1/hanul/runs/{run_id}/explain` | 입력·선택·가정·오류·재현 명령 설명 |

Optional context는 MCP 도구를 늘리지 않고 `get_field_status(include_context=true)`와 `GET /v1/hanul/context`로만 조회한다.

### 8.1 공통 public envelope

```text
schema_version, tool_name, tool_version, as_of,
site_id, profile, status, status_reasons[], component_status[],
claim_type, input_mode_set[], effective_mode,
synthetic_dependency, replay_dependency, watermark_code?,
selection_policy_version, gate_policy_version,
selected_sources[], excluded_sources[],
target_scope="jellyfish", species_claim="none",
external_display_name="한울 주변 대량 해파리 군집 감시",
units, warnings[], error?, provenance_ref,
run_id|query_id, request_id*, latency_ms*
```

`*`는 volatile 필드다. 공개 response와 저장소에는 내부 분류·데이터 선택 경위 또는 그 참조를 넣지 않는다.

### 8.2 도구별 핵심 불변식

`search_observations`

- `records[]`는 direct observation만 포함한다.
- 합성 seed는 요청 시 별도 `scenario_seeds[]`로 반환한다.
- `jellyList`는 `catalog_context.items[]`에만 들어간다.
- `candidates_scanned = returned + sum(excluded_counts)`.
- 위 불변식은 관측 후보에만 적용한다. scenario seed는 `records[]`, `returned`, `candidates_scanned`, `excluded_counts`에 합산하지 않고 `scenario_seeds_returned`로만 센다.

`get_field_status`

- 모든 field 후보의 coverage·freshness·direction gate를 보여준다.
- ROMS 403도 후보 목록에서 지우지 않고 rejected/blocked component로 남긴다.
- HB capability는 station별 응답으로 동적 판별한다.

`run_transport`

- 입력은 `seed_ids[]`만 허용한다.
- direction 또는 coverage gate 실패 시 계산하지 않는다.
- `released = valid + sum(terminated_by)`.
- probability, ETA, risk score 필드는 스키마에 존재하지 않는다.

`list_zones`

- zone은 공개 관측점 기반 prototype gate다.
- 실제 취수구·스크린·호기 기하 필드를 정의하지 않는다.
- `facility_geometry=null`, `disclaimer_code=NOT_INTAKE_STRUCTURE`.

`intersect_zone`

- 결과는 `members_intersected=M`, `members_total=N`, `display_string="M of N"`이다.
- 서버가 M/N을 백분율이나 확률로 변환하지 않는다.
- 시간 결과는 단일 ETA가 아니라 `first_intersection_window`다.

`explain_run`

- LLM이 아니라 템플릿으로 입력·선택·제외·가정·오류·체크섬을 설명한다.
- public surface에는 내부 분류 경위가 없다.

### 8.3 표준 오류코드

```text
NO_OBSERVATION
NO_COVERAGE
STALE_DATA
DIRECTION_UNVERIFIED
NO_COMPATIBLE_SOURCE
MODEL_BLOCKED
SCHEMA_INVALID
ZONE_NOT_FOUND
RUN_NOT_FOUND
ZONE_VERSION_MISMATCH
DOMAIN_INSUFFICIENT
GATE_MAPPING_BLOCKED
UPSTREAM_AUTH_FAILED
UPSTREAM_UNAVAILABLE
```

`MODEL_BLOCKED`의 `unavailable_reason`은 `no_seed`, `no_field`, `direction_unverified`, `outside_coverage`, `domain_insufficient` 중 하나다.

오류를 자연어에만 숨기지 않는다. 응답 필드 클래스는 `computed_metric`, `request_echo`, `diagnostic`, `provenance`이며 오류 시 `computed_metric`만 null이다.

### 8.4 도구별 최소 요청 파라미터

```text
search_observations:
  site_id|bbox, time_from, time_to, allowed_modes[],
  min_evidence_grade, presence, limit, cursor, include_scenario_seeds

get_field_status:
  site_id, as_of, horizons_h[], allowed_modes[], include_context

run_transport:
  seed_ids[], field_ref, horizons_h[], scenario_id,
  gate_mapping, boundary_rule, allowed_modes[]

list_zones:
  site_id, access_class, as_of

intersect_zone:
  run_id, zone_ids[], horizons_h[]

explain_run:
  run_id|query_id, include[]
```

단, `SYNTH_DOMAIN_HANUL_v1`에서는 `boundary_rule=null`만 허용하며 다른 값은 `SCHEMA_INVALID`다.

## 9. 상태와 source 선택

각 component에는 다음 role이 붙는다.

```text
required_input
selected_alternative
rejected_candidate
optional_context
```

최상위 상태는 `required_input` component만으로 정한다.

```text
READY=0 < DEGRADED=1 < STALE=2 < BLOCKED=3
```

- 선택되지 않은 ROMS 403, optional 적조·정선 오류는 warnings/component status에만 남는다.
- 필수 source의 부분수집은 최소 DEGRADED이며 `PARTIAL_FETCH`를 남긴다.
- stale과 partial이 함께면 top-level은 STALE, reasons에는 둘 다 남긴다.
- BLOCKED에서는 computed metric만 null이고 요청·진단·provenance는 반환한다.

선택 규칙:

1. 요청에 허용된 모드 안에서 역할별 후보를 비교한다.
2. 우선순위는 LIVE → CACHED → SYNTHETIC이지만, 호출자가 SYNTHETIC을 허용하지 않으면 절대 선택하지 않는다.
3. `[LIVE]`와 ROMS 403이면 BLOCKED다.
4. `[LIVE,CACHED]`인데 한울 cached field가 없으면 BLOCKED다.
5. SYNTHETIC을 명시 허용하면 합성 field를 선택할 수 있고 ROMS 403은 rejected candidate로 남는다.

## 10. 합성 도메인과 DEMO_GATE

MVP 합성 격자는 다음으로 확정한다.

```yaml
domain_id: SYNTH_DOMAIN_HANUL_v1
bbox:
  lat_min: 36.99
  lat_max: 37.14
  lon_min: 129.36
  lon_max: 129.48
spacing_deg: 0.01
domain_rule: open_rectangle_no_landmask
land_mask_rule: none_synthetic_domain
physical_realism: none
coastline_basis: none
termination_rules:
  - out_of_domain
  - forecast_unavailable
  - field_missing
boundary_rule: null
```

gate는 공개된 HB 관측점이 포함되는 synthetic cell로만 정의한다.

- `DEMO_GATE_ONYANG_v1` — HB_0007
- `DEMO_GATE_DEOKCHEON_v1` — HB_0008
- `DEMO_GATE_NAGOK_v1` — HB_0009

규칙:

- 실제 해안·수심·육지·취수구를 반영하지 않는다.
- `beached` 종료를 사용하지 않는다.
- land mask가 없는 이 도메인에서는 `boundary_rule`을 null로 고정한다.
- 지도에서는 실제 basemap 위 사선 해칭 synthetic domain으로만 렌더링한다.
- 합성 궤적을 basemap 단독으로 표시하지 않는다.
- W-5를 항상 표시한다: `합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다.`

## 11. Run manifest와 감사

public run manifest는 다음을 append-only로 남긴다.

```text
run_id, created_at, profile, tool_chain[],
request_echo, request_hash, allowed_modes[], input_mode_set[],
effective_mode, synthetic_dependency, replay_dependency, watermark_code,
sources[]{source_id, role, redacted_endpoint, status, source_data_mode,
          fetched_at, issued_at, valid_at,
          content_checksum, request_fingerprint, fixture_checksum?,
          rows/pages expected/received, partial, failed_pages[],
          license, adapter_version},
gate_results, component_status[], status, status_reasons[], error,
field_ref, zone_versions[], model/engine versions,
reproducibility{}, deterministic_result_digest,
artifact_refs[], audit_ref
```

수정·삭제 API는 만들지 않는다. 재계산은 새 run ID를 만든다.

`zone_version`은 다음으로 계산한다.

```text
blake2b(
  domain_id + gate_rule + sorted(station_codes)
  + neighbor_mode + zone_policy_version
)
```

run이 참조한 `zone_version`과 조회 시점 값이 다르면 조용히 재계산하지 않는다. `ZONE_VERSION_MISMATCH`를 warning으로 남기고 두 버전을 함께 반환한다.

audit log 한 줄은 다음만 기록한다.

```text
ts, request_id, tool, request_hash, allowed_modes,
selected_source_ids[], excluded[{source_id,reason_code}],
gate_summary, status, error_code, run_id|query_id,
digest, duration_ms
```

## 12. REST/MCP 등가성

REST와 MCP는 같은 `DomainCommand → CanonicalResult`를 사용한다.

`deterministic_result_digest`에서 제외할 volatile 필드:

```text
request_id, latency_ms, trace_id, run_id, created_at,
provenance_ref, artifact_ref, audit_ref, transport,
mcp_session_id, hostname, process_id, http_status
```

정규화 규칙:

- 객체 키 사전순
- 배열 순서 보존
- 좌표 1e-7, 물리량 1e-6 양자화
- null 통일
- UTF-8 compact JSON
- ISO-8601 UTC Z

판정은 REST digest = MCP digest = golden digest이고, 별도 artifact content checksum도 같아야 한다.

### 12.1 결정론 정책

- `B0_hold`, `B2_current_only`는 난수를 쓰지 않고 고정 5×5 방출 격자를 사용한다.
- `B3`만 RNG를 사용한다.
- `run_seed`는 정규화한 `sorted(seed_ids)`, `field_ref`, `horizons`, `scenario_id`, `gate_mapping`, `engine_version`, policy versions의 BLAKE2b 결과 상위 8 bytes다.
- RNG는 PCG64이며 전역 RNG를 사용하지 않는다.
- 입자 stream은 `SeedSequence.spawn(index)`로 분리한다.
- float64, RK4를 고정하고 병렬 reduce를 금지하며 합산 전 index를 정렬한다.
- 응답과 manifest에 `reproducibility{run_seed, rng_algorithm, quantization, float_policy, reproducibility_class="quantized_cross_env"}`를 기록한다.

## 13. 테스트·보안 acceptance

### 필수 테스트

- 키 0개 환경에서 서버·MCP·fixture가 기동한다.
- adapter가 환경변수를 직접 읽지 않는다.
- full URL/query를 포함한 예외를 던져도 로그·응답에 키가 없다.
- 부분 페이지 실패는 partial, failed pages, received/expected를 남긴다.
- NIFS catalog record에 geometry·밀도 필드가 없다.
- 합성 seed가 direct observation records에 섞이지 않는다.
- station capability가 HB 지점 사이에 전파되지 않는다.
- 다른 grid ID는 병합되지 않는다.
- 미검증 방향에서 `to_uv()` 호출은 실패하고 run은 BLOCKED다.
- live 실패 시 silent synthetic substitution이 없다.
- 공개 6도구 응답에 내부 분류 경위나 참조가 없다.
- 응답은 256 KiB 이하이며 대용량 원자료는 blob ref로만 노출한다.
- 6도구 REST/MCP/golden digest가 일치한다.
- fixture와 golden은 네트워크 0회로 재현된다.

### 비밀 스캔

1. 실행환경의 실제 키 값과 exact match 시 실패
2. `serviceKey|authKey|key=` 값이 마스킹되지 않으면 실패
3. entropy scanner는 fixture checksum allowlist를 제외하고 경고

무차별 base64 정규식은 사용하지 않는다.

## 14. 구현 순서

### P0 — 차단까지 정직하게 구현

1. `pyproject.toml`, `uv.lock`, 패키지 트리, socket guard, `.gitignore` 예외
2. contracts, settings, 12개 registry 항목
3. core adapter 6개
   - historical observation fixture
   - scenario seed synthetic
   - NIFS jelly catalog
   - KHOA Hanul point observations
   - cached field
   - ROMS blocked fixture
4. source selection, gate, component/top-level 상태
5. 확정한 synthetic domain과 3개 DEMO_GATE
6. 여섯 MCP 도구와 여섯 REST endpoint 모두 노출
   - transport와 intersect는 P0에서 계약에 맞는 명시적 BLOCKED 응답
7. public projection, blob/run/audit store, explain_run

P0 acceptance:

- ROMS 403가 누락되지 않고 BLOCKED component로 보인다.
- HF_0071은 한울 coverage 실패로 탈락한다.
- SYNTHETIC 미허용 요청은 자동 대체되지 않는다.
- 오류에서도 request·diagnostic·provenance가 남는다.
- 키 없이 모든 offline golden이 통과한다.

### P1 — 합성 조건부 수송과 교차

1. synthetic field 3개 프로파일과 cached field gate
2. 결정론적 적분·종료 사유·이동 envelope
3. DEMO_GATE 교차와 core/edge4/edge8 민감도
4. 여섯 도구 3-way equivalence golden
5. mock orchestrator와 안전 린터

테넌트 연결 증거가 없으므로 `orchestrator="mock"`으로 표시하고 Copilot 연동 완료를 주장하지 않는다.

### Optional

- 적조·정선관측 context adapter
- HF regression adapter
- ROMS live adapter
- jellyDetail2 계약 확인
- context REST endpoint
- 확산 앙상블

P0·P1 통과 후 시간이 2시간 이상 남을 때만 착수한다.

## 15. 공개 데모 문구

필수 워터마크:

- `공개 관측점 기반 프로토타입 감시격자입니다. 실제 취수구·안전계통 경계가 아닙니다.`
- 합성 의존 시: `합성 유동장에 의존한 조건부 시나리오입니다. 실제 예보가 아닙니다.`
- 캐시 의존 시: `과거 녹화 자료 재생이며 현재 상태가 아닙니다.`
- BLOCKED 시: `계산 보류 — 사유: {error_code}. 필요한 데이터: {required[]}`
- 합성 도메인: `합성 사각 도메인입니다. 해안선·육지·수심을 반영하지 않으며 입자가 육상 위를 지날 수 있습니다.`

허용 표현:

- 표층조건부 이동영역
- 공개 감시격자와 교차한 앙상블 member M of N
- 최초 교차 시간창
- 직접관측 / 조건부 시나리오 / 환경맥락 / 자료부족
- 계산 보류 — 면 유동장 미확보
- 유향 정의가 검증되지 않아 벡터 수송을 수행하지 않음

금지 표현:

- 도착확률, ETA, 막힘확률, 정지위험, 위험점수
- M/N의 백분율 변환
- 운전·감발·정지 권고
- 실제 취수구·안전계통 경계로 오인시키는 표현
- 해파리 주간보고를 실시간 군집 좌표로 표현
- 적조를 먹이 농도라고 표현
- 2020년 정선관측으로 현재 환경을 판단
- 자료가 없으므로 안전하다는 결론

## 16. 남은 비차단 항목

- ROMS 별도 활용승인이 오면 live 후보로 추가한다. 승인 전에도 P0·P1은 완결 가능하다.
- 공개 배포 전 provider 키를 회전한다.
- 실제 해안·수심·시설자료가 합법적·승인된 형태로 제공되기 전에는 synthetic domain을 실제 물리영역으로 교체하지 않는다.
