# JunctionProject

한울 주변 대량 해파리 군집 감시 MCP의 실행 코드입니다. 승인 설계 문서는
[`junction-challenge5.1`의 `DocsShare` 브랜치](https://github.com/Youngmin322/junction-challenge5.1/tree/DocsShare/docs)에 있습니다.

## 실행

```bash
cp .env.example .env
# .env에 서로 다른 JELLYGUARD_LOCAL_REST_KEY와
# JELLYGUARD_MCP_CLIENT_KEY를 설정합니다.
uv sync --dev
uv run jellyguard
```

- 로컬 REST: `http://127.0.0.1:8000/v1/*`
- MCP Streamable HTTP: `POST http://127.0.0.1:8000/mcp`
- 로컬 대시보드: `http://127.0.0.1:8000/dashboard/`
- 테스트: `uv run pytest`

로컬 REST 요청에는 `x-jellyguard-local-key`, MCP 요청에는
`x-mcp-client-key` 또는 Bearer 토큰을 보냅니다. 공공데이터 제공기관 키가
없어도 CACHED/SYNTHETIC 계약 테스트와 서버 실행은 가능하며, LIVE 후보는
자동 대체하지 않고 차단 사유를 반환합니다.

## 자료 모드와 데모 검증

- `fixture`: 저장소에 포함된 고정 자료와 합성 시나리오로 재현 가능한 데모를 실행합니다.
- `cassette`: `tests/cassettes`에 고정한 정규화 응답을 사용합니다.
- `live`: `.env`의 제공기관 인증키와 `JELLYGUARD_LIVE_ENABLED_SOURCES`에 명시한
  소스만 호출합니다. 실패해도 합성 자료로 자동 전환하지 않습니다.

주요 LIVE 소스는 `nifs_jelly_catalog,khoa_tw_recent_hanul`이며, 선택적 환경 맥락으로
`nifs_redtide_list,nifs_soo_list`도 활성화할 수 있습니다. NIFS 해파리 자료는
공식 보고 목록이며 개별 위치 관측으로 재해석하지 않습니다. KHOA 한울 인근 관측점은
유향 정의 검증 전이므로 이동 계산에 쓰지 않고 화면의 관측점 맥락으로만 제공합니다.
인증키는 `.env`에만 두며 Git에 커밋하지 않습니다.

서버를 실행한 뒤 MCP의 고정 6도구 흐름을 점검할 수 있습니다.

```bash
uv run python scripts/demo_check.py --client-key "$JELLYGUARD_MCP_CLIENT_KEY"
```

## 현재 실행 범위

- `B0_hold`, `B2_current_only`, `B3` 합성 field의 결정론적 member 수송
- 3·6·12시간 이동 envelope와 member 보존 진단
- 온양·덕천·나곡 공개 관측점 기반 `DEMO_GATE`의 core/edge4/edge8 교차
- `M of N`과 요청 horizon 기반 최초 교차 시간창
- REST와 MCP에서 동일한 결과 digest

기본 합성 seed는 `SEED-HANUL-DEMO-001`입니다. 먼저
`get_field_status(allowed_modes=["SYNTHETIC"])`가 반환한 `field_ref`를 사용해
`run_transport`를 호출하고, 반환된 `run_id`로 `intersect_zone`을 호출합니다.

실제 ROMS 면 유동장, 해안선·수심, 실제 취수구 기하가 필요한 요청은 계속
`BLOCKED`로 남습니다. 캐시나 합성 자료를 LIVE 자료로 자동 대체하지 않습니다.

대시보드는 외부 지도·CDN에 의존하지 않는 임시 구현입니다. 공개 관측점 기반 감시격자,
조건부 이동 envelope, 3·6·12시간별 `M of N` 교차, 실행 ID·digest·근거를 보여줍니다.
UI를 교체하더라도 `/v1/dashboard/bootstrap`, `/v1/hanul/runs`,
`/v1/hanul/runs/{run_id}/intersect`, `/v1/hanul/explain` 계약을 그대로 사용할 수 있습니다.
