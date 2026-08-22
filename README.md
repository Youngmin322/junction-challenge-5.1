# Junction Jellyfish

경북 동해안 해파리 관련 데이터셋을 점검하는 로컬 Copilot 데이터 매니저입니다.

## 실행

```bash
npm install
npm run dev
```

- 웹 화면: `http://localhost:3000`
- Copilot 로컬 API: `http://localhost:3001`

## API 키 설정

`.env.example`을 `.env`로 복사한 뒤 필요한 값만 입력합니다. Copilot CLI에 이미 로그인되어 있으면 `COPILOT_GITHUB_TOKEN`은 비워도 됩니다.

```text
COPILOT_GITHUB_TOKEN=
NIFS_API_KEY=
DATA_GO_KR_SERVICE_KEY=
```

실제 키가 담긴 `.env`는 저장소에서 제외됩니다. 키는 `app/`의 브라우저 코드에 넣거나 `NEXT_PUBLIC_` 접두사를 붙이지 마세요. 환경변수를 변경한 뒤에는 개발 서버를 다시 실행해야 합니다.

`GET /api/health`는 키의 실제 값이 아니라 설정 여부만 반환하며, 서버 오류 응답에도 내부 인증 오류 원문을 포함하지 않습니다.

## 현재 등록된 읽기 전용 도구

- `list_datasets`
- `get_dataset_status`
- `check_dataset_quality`

실제 공공데이터 API 수집 함수는 다음 단계에서 각 도구의 핸들러에 연결하면 됩니다.
