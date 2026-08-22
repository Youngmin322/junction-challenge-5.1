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

P0에서는 데이터가 충분하지 않은 수송·감시격자 교차 계산을 의도적으로
`BLOCKED`로 반환합니다. 합성·캐시 자료로 자동 대체하지 않습니다.
