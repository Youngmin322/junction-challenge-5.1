from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

from jellyguard.config.registry import SOURCE_REGISTRY, SourceDefinition
from jellyguard.config.settings import Settings
from jellyguard.contracts import DataMode, ErrorCode


class SourceState(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    LIVE_DISABLED = "LIVE_DISABLED"
    LIVE_UNCONFIGURED = "LIVE_UNCONFIGURED"
    LIVE_OK = "LIVE_OK"
    LIVE_AUTH_FAILED = "LIVE_AUTH_FAILED"
    LIVE_UNAVAILABLE = "LIVE_UNAVAILABLE"
    LIVE_SCHEMA_INVALID = "LIVE_SCHEMA_INVALID"
    CACHED_FRESH = "CACHED_FRESH"
    CACHED_STALE = "CACHED_STALE"
    CACHED_EXPIRED = "CACHED_EXPIRED"
    CACHE_MISS = "CACHE_MISS"
    SYNTHETIC_EXPLICIT = "SYNTHETIC_EXPLICIT"
    BLOCKED_BY_POLICY = "BLOCKED_BY_POLICY"


PUBLIC_REASON = {
    SourceState.NOT_REQUESTED: (ErrorCode.MODE_NOT_ALLOWED, "요청 모드에 포함되지 않음"),
    SourceState.LIVE_DISABLED: (
        ErrorCode.LIVE_NOT_ENABLED,
        "이 실행 프로필에서 LIVE 연결이 활성화되지 않음",
    ),
    SourceState.LIVE_UNCONFIGURED: (
        ErrorCode.LIVE_NOT_ENABLED,
        "이 실행 프로필에서 LIVE 연결이 활성화되지 않음",
    ),
    SourceState.LIVE_AUTH_FAILED: (
        ErrorCode.UPSTREAM_AUTH_FAILED,
        "제공기관이 요청을 허용하지 않음",
    ),
    SourceState.LIVE_UNAVAILABLE: (
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "제공기관 응답 없음",
    ),
    SourceState.LIVE_SCHEMA_INVALID: (
        ErrorCode.SCHEMA_INVALID,
        "응답 형식이 계약과 다름",
    ),
    SourceState.CACHED_STALE: (ErrorCode.STALE_DATA, "최신이 아닌 저장 자료"),
    SourceState.CACHED_EXPIRED: (ErrorCode.NO_COVERAGE, "사용 가능한 자료 없음"),
    SourceState.CACHE_MISS: (ErrorCode.NO_COVERAGE, "사용 가능한 자료 없음"),
    SourceState.BLOCKED_BY_POLICY: (
        ErrorCode.NO_COMPATIBLE_SOURCE,
        "정책상 사용 불가",
    ),
}


TTL_SECONDS = {
    "nifs_jelly_catalog": (10 * 86400, 45 * 86400),
    "khoa_tw_recent_hanul": (3 * 3600, 24 * 3600),
    "historical_observation_fixture": (float("inf"), float("inf")),
    "nifs_redtide_list": (7 * 86400, 30 * 86400),
    "nifs_soo_list": (7 * 86400, 30 * 86400),
}


@dataclass(frozen=True)
class SourceResolution:
    source_id: str
    source_class: str
    optional: bool
    state: SourceState
    public_reason: str | None = None
    public_reason_code: str | None = None
    data_mode: str | None = None
    issued_at: str | None = None
    fetched_at: str | None = None
    age_seconds: int | None = None
    freshness: str | None = None
    license: str = "public-data"
    payload: Any = None
    manifest: dict[str, Any] | None = None

    def public_dict(self, *, include_internal: bool = False) -> dict[str, Any]:
        value = asdict(self)
        value.pop("payload", None)
        value.pop("manifest", None)
        if not include_internal:
            value.pop("state", None)
        else:
            value["internal_state"] = value.pop("state")
        return value


class SourceCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def latest(self, source_id: str) -> dict[str, Any] | None:
        path = self.root / f"{source_id}.jsonl"
        if not path.exists():
            return None
        latest = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                latest = json.loads(line)
        return latest

    def append(self, record: dict[str, Any]) -> None:
        path = self.root / f"{record['source_id']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


class PublicDataClient:
    NIFS_ENDPOINT = "https://www.nifs.go.kr/api/OpenAPI_json"
    KHOA_TW_ENDPOINT = "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService"

    def __init__(self, settings: Settings, clock: Callable[[], datetime]) -> None:
        self.settings = settings
        self.clock = clock

    def fetch(self, source_id: str) -> dict[str, Any]:
        if source_id == "nifs_jelly_catalog":
            return self._fetch_nifs_jelly()
        if source_id == "nifs_redtide_list":
            return self._fetch_nifs_context("nifs_redtide_list", "redtideList")
        if source_id == "nifs_soo_list":
            return self._fetch_nifs_context("nifs_soo_list", "sooList")
        if source_id == "khoa_tw_recent_hanul":
            return self._fetch_khoa_points()
        raise LookupError(source_id)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(
                connect=self.settings.http_connect_timeout_s,
                read=self.settings.http_read_timeout_s,
                write=self.settings.http_read_timeout_s,
                pool=self.settings.http_connect_timeout_s,
            ),
            headers={"User-Agent": "jellyguard/0.2 (+local-demo)"},
            follow_redirects=True,
        )

    @staticmethod
    def _get(client: httpx.Client, url: str, *, params: dict[str, Any]) -> httpx.Response:
        """Retry one transient transport/server failure without hiding the final error."""
        last_error: httpx.HTTPError | None = None
        for attempt in range(2):
            try:
                response = client.get(url, params=params)
                if response.status_code >= 500:
                    response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.5)
        assert last_error is not None
        raise last_error

    def _fetch_nifs_jelly(self) -> dict[str, Any]:
        now = self.clock().astimezone(UTC)
        from datetime import timedelta

        params = {
            "id": "jellyList",
            "key": self.settings.nifs_jelly_key,
            "sdate": (now - timedelta(days=45)).strftime("%Y%m%d"),
            "edate": now.strftime("%Y%m%d"),
        }
        with self._client() as client:
            response = self._get(client, self.NIFS_ENDPOINT, params=params)
        return self._normalize_nifs(response)

    def _normalize_nifs(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code in {401, 403}:
            raise PermissionError("upstream authorization rejected")
        response.raise_for_status()
        payload = response.json()
        header = payload.get("header") or {}
        result_code = str(header.get("resultCode", ""))
        if result_code and result_code != "00":
            if result_code in {"01", "02", "03", "10", "20", "30"}:
                raise PermissionError("upstream authorization rejected")
            raise ValueError(f"provider result {result_code}")
        body = payload.get("body") or {}
        items = body.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise TypeError("body.item must be a list")
        normalized = [
            {
                "catalog_id": str(item.get("board_idx") or item.get("idx") or ""),
                "title": str(item.get("board_subject") or item.get("subject") or ""),
                "registered_at": item.get("inpt_date"),
                "source_id": "nifs_jelly_catalog",
                "claim_type": "context/report_catalog",
            }
            for item in items
        ]
        return self._record(
            "nifs_jelly_catalog",
            normalized,
            response.status_code,
            result_code or "00",
            "https://www.nifs.go.kr/api/OpenAPI_json",
        )

    def _fetch_nifs_context(self, source_id: str, dataset_id: str) -> dict[str, Any]:
        now = self.clock().astimezone(UTC)
        from datetime import timedelta

        params = {
            "id": dataset_id,
            "key": self._nifs_key(source_id),
            "sdate": (now - timedelta(days=45)).strftime("%Y%m%d"),
            "edate": now.strftime("%Y%m%d"),
        }
        with self._client() as client:
            response = self._get(client, self.NIFS_ENDPOINT, params=params)
        if response.status_code in {401, 403}:
            raise PermissionError("upstream authorization rejected")
        response.raise_for_status()
        payload = response.json()
        header = payload.get("header") or {}
        result_code = str(header.get("resultCode", ""))
        if result_code and result_code != "00":
            if result_code in {"01", "02", "03", "10", "20", "30"}:
                raise PermissionError("upstream authorization rejected")
            raise ValueError(f"provider result {result_code}")
        body = payload.get("body") or {}
        items = body.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise TypeError("body.item must be a list")
        normalized = [
            {
                "record_id": str(
                    item.get("board_idx") or item.get("idx") or item.get("sta_cde") or index
                ),
                "registered_at": item.get("inpt_date") or item.get("obs_dat") or item.get("rdate"),
                "title": item.get("board_subject") or item.get("subject"),
                "source_id": source_id,
                "claim_type": "context",
                "raw": item,
            }
            for index, item in enumerate(items)
        ]
        return self._record(
            source_id,
            normalized,
            response.status_code,
            result_code or "00",
            "https://www.nifs.go.kr/api/OpenAPI_json",
        )

    def _nifs_key(self, source_id: str) -> str | None:
        return {
            "nifs_jelly_catalog": self.settings.nifs_jelly_key,
            "nifs_redtide_list": self.settings.nifs_redtide_key,
            "nifs_soo_list": self.settings.nifs_soo_key,
        }.get(source_id)

    def _fetch_khoa_points(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        status_code = 200
        result_code = "00"
        started_at = time.monotonic()
        with self._client() as client:
            for station_code in ("HB_0007", "HB_0008", "HB_0009"):
                if time.monotonic() - started_at >= self.settings.live_budget_s:
                    raise TimeoutError("live request budget exceeded")
                response = self._get(
                    client,
                    self.KHOA_TW_ENDPOINT,
                    params={
                        "serviceKey": self.settings.khoa_key,
                        "type": "json",
                        "obsCode": station_code,
                        "numOfRows": 1,
                        "pageNo": 1,
                    },
                )
                status_code = response.status_code
                if response.status_code in {401, 403}:
                    raise PermissionError("upstream authorization rejected")
                response.raise_for_status()
                payload = response.json()
                header = payload.get("header") or {}
                result_code = str(header.get("resultCode", ""))
                if result_code and result_code != "00":
                    raise PermissionError("upstream authorization rejected")
                items = ((payload.get("body") or {}).get("items") or {}).get("item") or []
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    rows.append(
                        {
                            "station_code": station_code,
                            "station_name": item.get("obsvtrNm"),
                            "lat": item.get("lat"),
                            "lon": item.get("lot"),
                            "observed_at": item.get("obsrvnDt"),
                            "current_direction": item.get("crdir"),
                            "current_speed": item.get("crsp"),
                            "water_temperature": item.get("wtem"),
                            "crdir_convention": "UNVERIFIED",
                        }
                    )
        if not rows:
            raise ValueError("no valid rows")
        return self._record(
            "khoa_tw_recent_hanul",
            rows,
            status_code,
            result_code or "00",
            "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService",
        )

    def _record(
        self,
        source_id: str,
        payload: Any,
        http_status: int,
        provider_result_code: str,
        endpoint: str,
    ) -> dict[str, Any]:
        fetched_at = self.clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {
            "source_id": source_id,
            "request_fingerprint": hashlib.sha256(source_id.encode()).hexdigest(),
            "http_status": http_status,
            "provider_result_code": provider_result_code,
            "issued_at": None,
            "fetched_at": fetched_at,
            "content_checksum": hashlib.sha256(content.encode()).hexdigest(),
            "adapter_version": "public-data-v1",
            "license": "public-data",
            "rows_received": len(payload),
            "pages_received": 1,
            "partial": False,
            "failed_pages": [],
            "redacted_endpoint": endpoint,
            "payload": payload,
        }


class SourceResolver:
    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], datetime],
        fixture_payloads: dict[str, dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.fixture_payloads = fixture_payloads
        self.cache = SourceCache(settings.cache_root)
        self.client = PublicDataClient(settings, clock)

    def resolve(self, source_id: str, allowed_modes: list[DataMode]) -> SourceResolution:
        definition = SOURCE_REGISTRY[source_id]
        allowed = set(allowed_modes)
        supported = set(definition.modes)
        if not (allowed & supported):
            return self._state(definition, SourceState.NOT_REQUESTED)
        if DataMode.SYNTHETIC in allowed and DataMode.SYNTHETIC in supported:
            return SourceResolution(
                source_id=source_id,
                source_class=definition.source_class,
                optional=definition.optional,
                state=SourceState.SYNTHETIC_EXPLICIT,
                data_mode=DataMode.SYNTHETIC.value,
                freshness="synthetic",
                payload=self.fixture_payloads.get(source_id),
                manifest=self.fixture_payloads.get(source_id),
            )

        last_state: SourceState | None = None
        if DataMode.LIVE in allowed and DataMode.LIVE in supported:
            last_state = self._attempt_live(definition)
            if isinstance(last_state, SourceResolution):
                return last_state
        if DataMode.CACHED not in allowed or DataMode.CACHED not in supported:
            return self._state(definition, last_state or SourceState.CACHE_MISS)
        record = self._cached_record(source_id)
        if record is None:
            return self._state(definition, last_state or SourceState.CACHE_MISS)
        return self._cached_resolution(definition, record)

    def resolve_all(self, allowed_modes: list[DataMode]) -> list[SourceResolution]:
        return [self.resolve(source_id, allowed_modes) for source_id in SOURCE_REGISTRY]

    def _attempt_live(self, definition: SourceDefinition) -> SourceResolution | SourceState:
        if (
            self.settings.source_mode != "live"
            or definition.source_id not in self.settings.enabled_live_sources()
        ):
            return SourceState.LIVE_DISABLED
        key = self._key_for(definition.source_id)
        if not key:
            return SourceState.LIVE_UNCONFIGURED
        try:
            record = self.client.fetch(definition.source_id)
        except PermissionError:
            return SourceState.LIVE_AUTH_FAILED
        except (httpx.HTTPError, TimeoutError):
            return SourceState.LIVE_UNAVAILABLE
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return SourceState.LIVE_SCHEMA_INVALID
        self.cache.append(record)
        return SourceResolution(
            source_id=definition.source_id,
            source_class=definition.source_class,
            optional=definition.optional,
            state=SourceState.LIVE_OK,
            data_mode=DataMode.LIVE.value,
            fetched_at=record["fetched_at"],
            issued_at=record.get("issued_at"),
            age_seconds=0,
            freshness="live",
            license=record.get("license", "public-data"),
            payload=record["payload"],
            manifest=record,
        )

    def _cached_record(self, source_id: str) -> dict[str, Any] | None:
        if self.settings.source_mode == "cassette":
            path = self.settings.cassette_root / f"{source_id}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        runtime = self.cache.latest(source_id)
        if runtime is not None:
            return runtime
        return self.fixture_payloads.get(source_id)

    def _cached_resolution(
        self, definition: SourceDefinition, record: dict[str, Any]
    ) -> SourceResolution:
        timestamp = record.get("issued_at") or record.get("fetched_at")
        if timestamp is None or definition.source_id == "historical_observation_fixture":
            age_seconds = 0
        else:
            parsed = datetime.fromisoformat(timestamp)
            age_seconds = max(0, int((self.clock().astimezone(UTC) - parsed).total_seconds()))
        fresh_ttl, stale_ttl = TTL_SECONDS.get(definition.source_id, (0, 0))
        if age_seconds <= fresh_ttl:
            state, freshness = SourceState.CACHED_FRESH, "fresh"
        elif age_seconds <= stale_ttl:
            state, freshness = SourceState.CACHED_STALE, "stale"
        else:
            state, freshness = SourceState.CACHED_EXPIRED, "expired"
        reason = PUBLIC_REASON.get(state)
        return SourceResolution(
            source_id=definition.source_id,
            source_class=definition.source_class,
            optional=definition.optional,
            state=state,
            public_reason=reason[1] if reason else None,
            public_reason_code=reason[0].value if reason else None,
            data_mode=DataMode.CACHED.value if state != SourceState.CACHED_EXPIRED else None,
            issued_at=record.get("issued_at"),
            fetched_at=record.get("fetched_at"),
            age_seconds=age_seconds,
            freshness=freshness,
            license=record.get("license", "public-data"),
            payload=record.get("payload"),
            manifest=record,
        )

    def _state(self, definition: SourceDefinition, state: SourceState) -> SourceResolution:
        reason = PUBLIC_REASON.get(state)
        return SourceResolution(
            source_id=definition.source_id,
            source_class=definition.source_class,
            optional=definition.optional,
            state=state,
            public_reason=reason[1] if reason else None,
            public_reason_code=reason[0].value if reason else None,
        )

    def _key_for(self, source_id: str) -> str | None:
        return {
            "nifs_jelly_catalog": self.settings.nifs_jelly_key,
            "khoa_tw_recent_hanul": self.settings.khoa_key,
            "nifs_redtide_list": self.settings.nifs_redtide_key,
            "nifs_soo_list": self.settings.nifs_soo_key,
            "khoa_roms_live": self.settings.khoa_key,
        }.get(source_id)
