# 로컬 MCP 서버를 Copilot Studio에 연결하기

- 대상: 이 저장소의 로컬 MCP 데모를 재현하는 팀원·심사자
- 로컬 서버 전제: FastAPI, port `8000`, MCP endpoint `POST /mcp`
- 대시보드 전제: 로컬 REST `/v1/*` 사용
- 현재 상태: 실제 테넌트 연결 증거가 생기기 전까지 `orchestrator="mock"`으로 표시

> 이 문서의 `<...>`는 구현 또는 실행 시 교체할 placeholder다. 실제 tunnel URL·인증키는 Git에 커밋하지 않는다.

## 1. GitHub 데이터와 MCP 연결은 다른 문제다

| 구분 | GitHub | Copilot의 MCP 호출 |
|---|---|---|
| 목적 | 코드·계약·테스트·마스킹 fixture 공유 | 실행 중인 6개 도구 호출 |
| 시점 | commit·push | 에이전트가 도구를 선택할 때마다 |
| 데이터 위치 | 공개 저장소 | 로컬 API·SQLite·runtime cache |
| 필요한 접근 | Git 권한 | Copilot Studio에서 도달 가능한 HTTPS URL |
| 금지 | 인증키·대용량 원자료·내부 운영자료 | SQLite·admin·docs·raw fixture 직접 노출 |

Copilot Studio는 GitHub 저장소에 파일이 있다는 이유만으로 데이터를 사용하지 않는다. 반대로 MCP 도구를 호출한다고 해서 로컬 원자료 전체가 GitHub로 올라가는 것도 아니다.

연결에 필요한 것은 다음 두 가지다.

1. 실행 중인 MCP 서버
2. Copilot Studio가 그 서버에 도달할 수 있는 HTTPS 경로

## 2. 네트워크 구조

```text
사용자 → Copilot Studio (Microsoft cloud)
                    │
                    │ HTTPS · Streamable HTTP · POST /mcp
                    ▼
         Microsoft Dev Tunnel public URL
                    │
                    │ local port 8000으로 전달
                    ▼
내 노트북 ─ FastAPI :8000
           ├─ /mcp        외부 Copilot용
           ├─ /v1/*       로컬 대시보드 전용
           ├─ /docs       외부 차단
           ├─ /admin      외부 차단
           └─ SQLite·runs·fixtures  외부 차단
```

Copilot Studio는 클라우드 서비스이므로 `http://localhost:8000/mcp`를 직접 호출할 수 없다. Dev Tunnel이 임시 공개 HTTPS 주소를 만들고 그 요청을 로컬 port 8000으로 전달한다.

대시보드는 계속 `localhost`의 REST API를 호출한다. 터널은 Copilot의 MCP 연결을 위해서만 사용한다.

## 3. Dev Tunnel이 하는 일

로컬 주소:

```text
http://localhost:8000/mcp
```

터널 실행 후 발급되는 주소의 형태:

```text
https://<TUNNEL_ID>-8000.<REGION>.devtunnels.ms/mcp
```

위 주소는 예시 형식이다. 실제 주소는 `devtunnel host` 또는 `devtunnel show` 출력에서 확인한다. 실제 주소를 문서나 저장소에 커밋하지 않는다.

```text
Copilot Studio
  → https://<발급된 주소>/mcp
  → Dev Tunnel relay
  → 내 노트북 localhost:8000/mcp
```

별도 클라우드 애플리케이션 서버를 만들지 않아도 되지만, 시연 중에는 다음이 모두 실행 중이어야 한다.

- 노트북
- 로컬 FastAPI
- Dev Tunnel host process
- 인터넷 연결

## 4. 전송방식 요구사항

- Copilot Studio 연결은 MCP **Streamable HTTP**를 사용한다.
- 서버는 HTTPS로 노출되는 `POST /mcp`에서 MCP 요청을 처리한다.
- stdio는 로컬 process 간 연결이므로 Copilot Studio cloud 연결에 사용할 수 없다.
- SSE 전용 MCP server는 사용하지 않는다. Copilot Studio는 2025년 8월 이후 SSE transport를 지원하지 않는다.
- REST와 MCP는 같은 application service를 호출한다. 계산 로직을 복제하지 않는다.

## 5. 경로 선택

| 방식 | 용도 | URL | 특징 |
|---|---|---|---|
| 임시 tunnel | 짧은 리허설·1회 데모 | 실행할 때마다 변경 | 명령 한 줄로 시작 |
| persistent tunnel | 반복 리허설·Copilot 재사용 | 고정 | 한 번 생성 후 같은 ID로 host |

Copilot Studio에 MCP server URL을 한 번만 등록하려면 persistent tunnel을 사용한다.

## 6. Dev Tunnels CLI 설치와 로그인

macOS:

```bash
brew install --cask devtunnel
devtunnel user login
```

`devtunnel user login`은 Microsoft Entra ID, Microsoft 계정 또는 GitHub 계정으로 진행한다.

설치 확인:

```bash
devtunnel --version
devtunnel user show
```

## 7. 연결 순서

### 7.1 로컬 서버를 먼저 확인한다

```bash
<프로젝트 실행 명령>
```

현재 저장소에는 실행 코드가 아직 없으므로 실제 서버 기동 명령이 확정되면 위 placeholder를 교체한다.

확인 항목:

```text
<LOCAL_HEALTH_CHECK>
<LOCAL_MCP_SMOKE_TEST>
```

- `<LOCAL_HEALTH_CHECK>`: 구현 후 확정할 health endpoint 검사 명령
- `<LOCAL_MCP_SMOKE_TEST>`: MCP initialize와 `tools/list`까지 수행하는 프로젝트 smoke-test 명령

Streamable HTTP 구현에 따라 session 초기화가 필요할 수 있으므로 단일 `curl tools/list`를 확정 명령으로 가정하지 않는다.

통과 기준:

- FastAPI가 port 8000에서 응답한다.
- MCP initialize가 성공한다.
- `tools/list`가 다음 6개 도구를 반환한다.
  - `search_observations`
  - `get_field_status`
  - `run_transport`
  - `list_zones`
  - `intersect_zone`
  - `explain_run`
- 인증이 없는 `/mcp` 요청은 성공하지 않는다.

로컬 검사가 실패하면 tunnel을 열지 않는다.

### 7.2 임시 tunnel

```bash
devtunnel host -p 8000 --allow-anonymous
```

명령이 출력한 HTTPS URL을 현재 리허설에서만 사용한다. `Ctrl-C`로 host를 종료하면 임시 tunnel도 종료된다.

`--allow-anonymous`는 tunnel relay의 로그인 장벽만 해제한다. MCP endpoint의 API key 인증까지 제거한다는 뜻이 아니다.

### 7.3 Persistent tunnel

```bash
devtunnel create <TUNNEL_ID>
devtunnel port create <TUNNEL_ID> -p 8000 --protocol http
devtunnel access create <TUNNEL_ID> --port 8000 --anonymous
devtunnel host <TUNNEL_ID>
```

관리 명령:

```bash
devtunnel list
devtunnel show <TUNNEL_ID>
devtunnel delete <TUNNEL_ID>
```

`<TUNNEL_ID>`는 팀이 정한 tunnel ID로 교체한다. ID가 이미 사용 중이면 다른 값을 사용한다.

### 7.4 Tunnel을 통한 MCP 검사

```text
<TUNNELED_MCP_SMOKE_TEST>
```

구현 후 로컬 smoke-test와 같은 MCP client를 사용하고 base URL만 발급된 tunnel URL로 바꾼다.

통과 기준:

- local과 tunnel 양쪽에서 같은 6개 tool schema가 반환된다.
- 인증 없는 요청은 성공하지 않는다.
- `/mcp` 외 외부 경로는 차단된다.
- 실제 tunnel URL이나 key가 응답·로그에 남지 않는다.

### 7.5 Copilot Studio에 MCP server 등록

Copilot Studio의 현재 화면 기준:

1. 대상 agent를 연다.
2. **Build** 또는 **Tools**에서 **Add a tool**을 선택한다.
3. **Model Context Protocol (MCP)**을 선택한다.
4. 다음 값을 입력한다.

| 항목 | 값 |
|---|---|
| Name | `Hanul Jellyfish Monitoring MCP` |
| Description | 공개 관측·해양자료·프로토타입 감시격자를 조회하는 도구 모음 |
| Server URL | `https://<실제 Dev Tunnel host>/mcp` |
| Authentication | MCP server가 요구하는 API key 설정 |

5. 연결 후 Copilot Studio가 표시하는 도구 목록이 6개인지 확인한다.
6. agent에 도구를 추가하고 저장한다.
7. Preview/Test에서 MCP가 필요한 질문을 실행한다.

화면 이름은 Copilot Studio 업데이트에 따라 달라질 수 있다. 핵심 입력은 `HTTPS server URL`과 MCP server authentication이다.

### 7.6 Activity trace 검증

Copilot Studio의 activity trace에서 확인한다.

- 호출된 tool 이름
- tool input arguments
- tool response의 status와 근거
- 최종 답변에 사용된 모든 숫자가 tool response에 존재하는지
- `status=BLOCKED`일 때 AI가 계산 보류와 사유를 말하는지

이 검사가 통과하기 전에는 `orchestrator="mock"`을 유지하고 `Copilot 연동 검증 완료`라고 표현하지 않는다.

## 8. `/mcp`만 외부에 공개하는 방법

Dev Tunnel은 URL path가 아니라 **port 전체를 전달**한다. 따라서 port 8000을 tunnel로 열면 FastAPI의 `/v1/*`, `/docs`, `/openapi.json`도 별도 조치 없이는 외부에서 보일 수 있다.

프로젝트 구현은 외부 tunnel host로 들어온 요청을 다음처럼 제한해야 한다.

```text
외부 Dev Tunnel Host + /mcp   → 허용
외부 Dev Tunnel Host + 기타   → 404 또는 403
localhost + /v1/*             → 허용
localhost + /docs             → 개발 설정에 따라 허용
```

구현 방법은 FastAPI middleware 또는 로컬 reverse proxy 중 하나로 고정한다. 이 제한이 테스트되기 전에는 tunnel을 열지 않는다.

## 9. 최소 보안 계약

### 9.1 MCP client key

- `/mcp`는 별도의 MCP client API key를 요구한다.
- provider key와 MCP client key는 서로 다른 값이다.
- provider key를 Copilot Studio에 입력하지 않는다.
- 모든 key는 환경변수로 주입하고 Git에 넣지 않는다.
- 인증이 없거나 틀린 요청은 `401` 또는 `403`을 반환한다.

예시 변수명:

```dotenv
JELLYGUARD_MCP_CLIENT_KEY=
```

값은 `.env.example`에도 비워 둔다.

### 9.2 Tunnel access

`--allow-anonymous` tunnel은 URL을 아는 사람이 relay에 접근할 수 있다. URL의 무작위성은 인증이 아니다. MCP application 인증을 반드시 유지한다.

### 9.3 로그

다음을 로그에 남기지 않는다.

- 전체 URL과 query string
- authorization·API key header
- provider key
- request·response raw payload
- 예외 객체의 원문 `repr`

### 9.4 종료

- 임시 tunnel은 데모 직후 host process를 종료한다.
- 더 이상 쓰지 않는 persistent tunnel은 `devtunnel delete <TUNNEL_ID>`로 삭제한다.
- 데모 후 MCP client key를 교체한다.
- 공개 배포 전 provider key도 회전한다.

## 10. Troubleshooting

| 증상 | 가능한 원인 | 확인·조치 |
|---|---|---|
| Copilot Studio가 server URL에 연결하지 못함 | tunnel 미기동, URL 오타, `/mcp` 누락 | `devtunnel show`, tunnel smoke-test 확인 |
| 등록됐지만 tool이 0개 | MCP initialize·`tools/list` 계약 오류 | local smoke-test부터 통과시킨다 |
| 401 또는 403 | MCP client key 설정 불일치 | Copilot 인증 설정과 server header 계약 확인 |
| 502 또는 504 | 로컬 server 종료, port 불일치 | local health와 port 8000 확인 후 tunnel 재시작 |
| SSE 연결 오류 | SSE 전용 server 구현 | Streamable HTTP `POST /mcp`로 교체 |
| URL이 매번 바뀜 | 임시 tunnel 사용 | persistent tunnel로 전환 |
| dashboard가 tunnel URL에서 안 열림 | 정상 동작 | dashboard는 localhost 전용이다 |
| `/docs` 또는 `/v1/*`가 tunnel에서 열림 | 외부 path restriction 미구현 | 즉시 tunnel 종료 후 middleware/reverse proxy 수정 |
| AI 답변에 tool response에 없는 숫자가 있음 | orchestrator가 값을 생성 | activity trace 검토 후 mock/실연동 표현 중단 |
| `devtunnel` 명령을 찾지 못함 | CLI 설치·PATH 문제 | Homebrew 설치 확인 후 새 shell에서 재시도 |

## 11. 데모 체크리스트

### 시작 전

- [ ] 로컬 server health 통과
- [ ] 로컬 MCP initialize와 `tools/list` 통과
- [ ] tool 6개 확인
- [ ] MCP client key 설정
- [ ] 미인증 `/mcp` 요청이 성공하지 않는지 확인
- [ ] tunnel에서 `/mcp` 외 경로가 차단되는지 확인
- [ ] tunnel MCP smoke-test 통과
- [ ] Copilot Studio Preview/Test 1건 성공
- [ ] activity trace에서 tool input/output 확인

### 진행 중

- [ ] 화면에 tunnel URL·key·provider credential이 노출되지 않게 한다.
- [ ] `BLOCKED`를 실패가 아니라 근거가 부족해 계산을 보류한 상태로 설명한다.
- [ ] 합성·캐시 의존 워터마크를 유지한다.

### 종료 후

- [ ] Dev Tunnel host 종료
- [ ] 사용하지 않을 persistent tunnel 삭제
- [ ] MCP client key 교체
- [ ] activity trace 증거 보관

### 중단조건

다음 중 하나라도 해당하면 tunnel을 닫고 로컬 mock demo로 전환한다.

- local MCP smoke-test 실패
- 미인증 MCP 요청 성공
- tunnel URL에서 `/mcp` 외 경로 접근 가능
- 로그·응답에서 key 노출
- Copilot 답변에 tool response에 없는 수치 발생
- 남은 시간이 30분 미만인데 tunnel 연결 미검증

## 12. 구현 후 교체할 placeholder

| placeholder | 교체 시점 |
|---|---|
| `<프로젝트 실행 명령>` | FastAPI 실행 command 확정 후 |
| `<LOCAL_HEALTH_CHECK>` | health endpoint 구현 후 |
| `<LOCAL_MCP_SMOKE_TEST>` | MCP Streamable HTTP test client 구현 후 |
| `<TUNNELED_MCP_SMOKE_TEST>` | 같은 test client의 base URL option 구현 후 |
| `<TUNNEL_ID>`, `<REGION>` | Dev Tunnel 출력 확인 시; 실제 값은 커밋 금지 |

Dev Tunnels CLI 명령은 Microsoft 공식 문서 기준 실제 명령이다. 프로젝트 실행·MCP smoke-test 명령은 구현 전이므로 placeholder를 사실처럼 실행하지 않는다.

## 13. 공식 문서

- [Copilot Studio에 MCP server 추가](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/tools-add-mcp-server)
- [Copilot Studio용 MCP server 생성과 인증](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-create-new-server)
- [Microsoft 365 Copilot의 로컬 MCP·API 디버깅](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api-plugin-debug-local)
- [Dev Tunnels 시작하기](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/get-started)
- [Dev Tunnels CLI command reference](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/cli-commands)
- [Dev Tunnels 보안](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/security)
