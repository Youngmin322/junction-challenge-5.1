# 원격 데이터 수집 브랜치 이식 지도

- 대상: `origin/feat/#1-OpenAPI호출@e5aca27`
- 대조 상태: Codex 원문 대조 완료
- 원칙: merge·rebase·cherry-pick하지 않고, 검증된 endpoint·parameter·station·field 사실만 새 source adapter에 선택 이식한다.

## 1. 원문 감사 결과

다음 사항을 실제 파일에서 확인했다.

1. `.env.example`은 저장소 루트에 있지만 수집 스크립트는 `Path(__file__).parent/.env`만 읽는다.
2. `requests` 예외 문자열이 full URL과 query의 인증키를 포함할 가능성이 있다.
3. 전국 `hfCurrent` grid가 하나의 연속 field처럼 합쳐질 수 있다.
4. pagination 후속 호출 실패 시 부분 자료를 정상처럼 반환한다.
5. KHOA 키가 없으면 module import 단계에서 종료한다.
6. 대용량 raw JSON을 그대로 반환·저장한다.
7. `.gitignore`가 모든 JSON·CSV를 무시해 fixture와 golden도 추적하지 못한다.
8. 세 collector는 Python 정적 compile을 통과했다.
9. 데이터셋별 NIFS 키 분리와 jellyList의 보고서 목록 경계는 올바르게 반영했다.

## 2. 자산별 migration map

| 원본 | 판정 | 새 모듈 | 보존 | 폐기·재작성 | 회귀 테스트 |
|---|---|---|---|---|---|
| `.env.example` | 구조 채택 | `.env.example`, `config/settings.py` | NIFS dataset별 키와 KHOA 키 분리 | root/collectors 이중 경로; exact 변수명은 `JELLYGUARD_*`로 통일 | `test_settings_single_load`, `test_registry_env_names_match_example` |
| `.gitignore` | 부분 채택 | `.gitignore` | `.env`, run 산출물 제외 | JSON/CSV 전면 제외; `tests/fixtures/**`, `tests/golden/**` 예외 | `test_fixtures_are_tracked` |
| `collectors/해파리정보_수집.py` | 참고 후 재작성 | `nifs_jelly_catalog.py` | endpoint·필수 parameter, jellyList가 관측수치가 아님을 명시 | 직접 파일 출력, 대형 raw 반환, URL 포함 예외 | `test_jelly_catalog_is_context_only`, `test_catalog_has_no_geometry` |
| `collectors/적조_정선해양_수집.py` | optional adapter 2개로 분리 | `nifs_redtide.py`, `nifs_soo.py` | 적조와 정선관측 원자료를 분리 보존 | 두 의미를 하나로 합치기, 현재환경·먹이량으로 해석, 8,655행 직접 응답 | `test_context_only_claim`, `test_soo_historical_warning`, `test_response_size_limit` |
| `collectors/해류데이터_통합.py` | 대폭 축소 재작성 | `khoa_tw_recent.py`, `khoa_hf_current_regression.py`, `http.py` | pagination 기본 구조, station 코드, raw field 이름 | 전국 기본호출, grid 병합, 미검증 `to_uv`, 부분성 은폐, import-time exit | `test_station_scope_hanul_only`, `test_no_grid_merge`, `test_to_uv_guarded`, `test_partial_pagination_degraded`, `test_boot_without_keys` |
| `docs/해류데이터_통합 코드 설명.md` | 설계 근거로만 사용 | 본 문서·Evidence Ledger | 시간축·공간축 차이와 legacy 특성 | 검증 전 성능·방향 주장 | 문서 사실 대조 |

## 3. 선택 이식 절차

1. 참고 브랜치는 읽기 전용으로 조회한다.
2. 위 표의 보존 항목과 endpoint contract만 추출한다.
3. 새 adapter를 처음부터 작성하며 원본 collector를 복사하지 않는다.
4. 각 행의 회귀 테스트를 먼저 작성해 실패를 확인한다.
5. 구현 뒤 offline fixture와 live smoke test를 분리한다.
6. live smoke test의 URL·query·header·payload는 저장하지 않는다.
7. source별 checksum·page completeness·capability를 manifest에 기록한다.

## 4. 이식하지 않는 이유

원본 collector는 빠른 탐색에는 유용하지만 MCP 재사용 표면에 그대로 넣으면 다음 문제가 생긴다.

- 보고서 catalog, 환경 context, 점 관측, 면 유동장의 의미가 한 응답에서 섞인다.
- 일부 page 실패와 방향 미검증이 정상 데이터처럼 전파될 수 있다.
- import-time key 검사 때문에 offline test와 blocked-path 시연이 불가능해진다.
- 전국 grid 병합은 한울 coverage와 무관한 자료를 수송 field로 오독시킨다.
- 대용량 raw response와 URL 예외가 응답량·비밀관리 계약을 깨뜨린다.

따라서 코드 재사용보다 검증된 API 사실을 계약·테스트와 함께 이식하는 편이 더 안전하고 빠르다.
