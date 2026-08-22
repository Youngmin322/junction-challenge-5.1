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
- 테스트: `uv run pytest`

로컬 REST 요청에는 `x-jellyguard-local-key`, MCP 요청에는
`x-mcp-client-key` 또는 Bearer 토큰을 보냅니다. 공공데이터 제공기관 키가
없어도 CACHED/SYNTHETIC 계약 테스트와 서버 실행은 가능하며, LIVE 후보는
자동 대체하지 않고 차단 사유를 반환합니다.

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
