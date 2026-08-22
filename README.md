# Jellywatch

경북 동해안 해파리·해류·해양환경 자료를 점검하고 한울 공개 데모의 조건부
취수구 접근영역을 설명하는 통합 프로젝트입니다.

## 구성

| 경로 | 역할 |
| --- | --- |
| `app/` | Copilot 데이터 매니저 웹 화면 |
| `server/` | GitHub Copilot SDK와 JellyGuard를 연결하는 읽기 전용 도구 서버 |
| `backend/` | FastAPI REST, 단일 MCP 서버, 자료 출처·이동·감시격자 계산 |
| `backend/collectors/` | KHOA/NIFS 공공데이터 수집기 3종 |
| `packages/risk-zone/` | TypeScript 조건부 입자 연결 계산과 MapLibre 데모 |
| `docs/collectors/` | 수집기 설계와 해류 통합 설명 |

## 빠른 실행

Node.js 24 이상, Python 3.11 이상, `uv`가 필요합니다.

```bash
cp .env.example .env
npm install
npm --prefix packages/risk-zone install
uv sync --project backend --dev
npm run dev
```

- 웹 화면: `http://localhost:3100`
- Copilot 도구 서버: `http://localhost:3001`
- JellyGuard REST/MCP: `http://127.0.0.1:8000`
- 기존 JellyGuard 대시보드: `http://127.0.0.1:8000/dashboard/`

Copilot CLI에 로그인되어 있으면 `COPILOT_GITHUB_TOKEN`은 비워도 됩니다.
공공데이터 키가 없어도 JellyGuard의 fixture/synthetic 모드와 전체 테스트를 실행할
수 있습니다. 실제 키는 `.env`에만 두고 `NEXT_PUBLIC_` 접두사를 붙이지 않습니다.

## 하나로 합쳐진 흐름

1. 공공데이터 수집기가 해파리, 해류, 적조·정선해양 자료를 정규화합니다.
2. JellyGuard가 출처와 자료 모드를 보존하고 조건부 이동·감시격자 계산을 제공합니다.
3. TypeScript 위험영역 패키지가 해류·수심·게이트 입력의 정밀 입자 계산과 지도 데모를 제공합니다.
4. Copilot 도구 서버가 JellyGuard REST를 읽어 데이터 상태와 품질검사 결과를 설명합니다.

Copilot에 등록되는 도구는 `list_datasets`, `get_dataset_status`,
`check_dataset_quality`, `get_risk_overview`입니다. 모든 도구는 읽기 전용입니다.
JellyGuard MCP에는 기존 6개 도메인 도구와 공공데이터 수집 도구 3개가 함께 노출됩니다.

## 검증

```bash
npm run verify
```

웹 lint/build, TypeScript 위험영역 build/test, Python 백엔드 테스트를 순서대로 실행합니다.

> 접근영역 결과는 주어진 관측·해류·수심·게이트 조건의 조건부 입자 연결 계산입니다.
> 생물량, 취수구 막힘 확률 또는 시설 위험도를 뜻하지 않습니다.
