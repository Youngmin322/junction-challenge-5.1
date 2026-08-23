from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx

from jellyguard.config.registry import SOURCE_REGISTRY, SourceDefinition
from jellyguard.config.settings import Settings
from jellyguard.contracts import DataMode, ErrorCode
from jellyguard.domain.convention import TOWARD, verify_flow_direction_convention


class SourceState(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    LIVE_DISABLED = "LIVE_DISABLED"
    LIVE_UNCONFIGURED = "LIVE_UNCONFIGURED"
    LIVE_OK = "LIVE_OK"
    LIVE_STALE = "LIVE_STALE"
    LIVE_EXPIRED = "LIVE_EXPIRED"
    LIVE_UNKNOWN_AGE = "LIVE_UNKNOWN_AGE"
    LIVE_NO_DATA = "LIVE_NO_DATA"
    LIVE_UNSUPPORTED = "LIVE_UNSUPPORTED"
    LIVE_AUTH_FAILED = "LIVE_AUTH_FAILED"
    LIVE_UNAVAILABLE = "LIVE_UNAVAILABLE"
    LIVE_SCHEMA_INVALID = "LIVE_SCHEMA_INVALID"
    CACHED_FRESH = "CACHED_FRESH"
    CACHED_STALE = "CACHED_STALE"
    CACHED_EXPIRED = "CACHED_EXPIRED"
    CACHED_UNKNOWN_AGE = "CACHED_UNKNOWN_AGE"
    CACHED_FIXTURE = "CACHED_FIXTURE"
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
    SourceState.LIVE_STALE: (ErrorCode.STALE_DATA, "최신이 아닌 LIVE 자료"),
    SourceState.LIVE_EXPIRED: (ErrorCode.NO_COVERAGE, "유효시간이 지난 LIVE 자료"),
    SourceState.LIVE_UNKNOWN_AGE: (ErrorCode.UNKNOWN_AGE, "LIVE 자료시각 미상"),
    SourceState.LIVE_NO_DATA: (ErrorCode.NO_COVERAGE, "제공기관에 해당 자료 없음"),
    SourceState.LIVE_UNSUPPORTED: (
        ErrorCode.LIVE_NOT_ENABLED,
        "이 실행 프로필에서 지원하지 않는 LIVE 연결",
    ),
    SourceState.CACHED_STALE: (ErrorCode.STALE_DATA, "최신이 아닌 저장 자료"),
    SourceState.CACHED_EXPIRED: (ErrorCode.NO_COVERAGE, "사용 가능한 자료 없음"),
    SourceState.CACHED_UNKNOWN_AGE: (ErrorCode.UNKNOWN_AGE, "저장 자료시각 미상"),
    SourceState.CACHED_FIXTURE: (ErrorCode.FIXTURE_DATA, "고정 재생자료"),
    SourceState.CACHE_MISS: (ErrorCode.NO_COVERAGE, "사용 가능한 자료 없음"),
    SourceState.BLOCKED_BY_POLICY: (
        ErrorCode.NO_COMPATIBLE_SOURCE,
        "정책상 사용 불가",
    ),
}


TTL_SECONDS = {
    "nifs_jelly_catalog": (10 * 86400, 45 * 86400),
    "khoa_tw_recent_hanul": (3 * 3600, 24 * 3600),
    # ROMS is an hourly surface forecast; issued_at is the first forecast hour, so a run
    # stays usable for a while after release but must not be presented as a nowcast.
    "khoa_roms_live": (6 * 3600, 24 * 3600),
    # hfCurrent and crntFcstTime are reference-only points, never a transport input, so a
    # generous TTL is safe -- staleness here only affects a context badge, not a physics
    # decision. Both providers omit a model run time the way ROMS does.
    "khoa_hf_current_reference": (6 * 3600, 24 * 3600),
    "khoa_crnt_fcst_reference": (6 * 3600, 24 * 3600),
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
    provenance_kind: str = "unavailable"
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


class ProviderNoDataError(ValueError):
    """The provider responded successfully but had no usable rows."""


class PublicDataClient:
    NIFS_ENDPOINT = "https://www.nifs.go.kr/api/OpenAPI_json"
    KHOA_TW_ENDPOINT = "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService"
    KHOA_ROMS_ENDPOINT = "https://apis.data.go.kr/1192136/roms/GetRomsApiService"
    KHOA_CRNT_FCST_ENDPOINT = (
        "https://apis.data.go.kr/1192136/crntFcstTime/GetCrntFcstTimeApiService"
    )
    # Tidal-current forecast points are published only for the west, south and southeast
    # coasts. 16LTC14 Ulsan New Port is the northernmost one and still sits roughly 180 km
    # south of Hanul, so this source is a convention reference, never a Hanul field.
    CRNT_FCST_REFERENCE_OBS_CODE = "16LTC14"
    KHOA_HF_ENDPOINT = "https://apis.data.go.kr/1192136/hfCurrent/GetHFCurrentApiService"
    # Exhaustively probed: exactly these 13 obsCode values are accepted by
    # GetHFCurrentApiService, everything else returns INVALID_REQUEST_PARAMETER_ERROR.
    # None of them sit anywhere near Hanul (37.05N, 129.42E) -- the closest, HF_0071
    # (Pohang harbour), is still ~120 km south. So this fetch is 13 southern/western-coast
    # reference points, never a Hanul field, regardless of how many stations answer.
    HF_STATION_CODES: ClassVar[tuple[str, ...]] = (
        "HF_0039",  # 여수해만
        "HF_0040",  # 부산항신항
        "HF_0041",  # 대한해협
        "HF_0063",  # 울산항
        "HF_0064",  # 광양항
        "HF_0065",  # 여수광양항
        "HF_0069",  # 인천항
        "HF_0070",  # 태안대산
        "HF_0071",  # 포항항
        "HF_0073",  # 동해남부 (observed values are sometimes reported as null)
        "HF_0074",  # 목포항외측
        "HF_0075",  # 목포항내측
        "HF_0076",  # 군산항
    )
    HANUL_LAT = 37.05
    HANUL_LON = 129.42
    ROMS_HANUL_BBOX: ClassVar[dict[str, float]] = {
        # Wider than the transport domain for two reasons. Bilinear sampling needs all
        # four surrounding points, so a field clipped to the domain strands every edge
        # particle with no neighbours. And the computation window expands by 25% per
        # attempt when particles leave it, which the field footprint has to allow for —
        # otherwise expansion stops immediately at `field_footprint_limit`.
        #
        # Sized from a live measurement, not a guess: 10,858 ROMS samples around Hanul
        # gave a mean surface speed of 0.243 m/s (max 0.71, p90 0.4) which integrates to a
        # mean +12h displacement of ~10.5 km and a max of ~30.7 km. The previous bbox
        # covered only ~31 km (lat) x ~17 km (lon) -- narrower than that max displacement,
        # so +12h expansion hit the field's own footprint before it could grow enough
        # (`expansion_attempt_cap`, stuck at a 92% exit fraction). This bbox was verified
        # live to cover roughly +/-43 km lat and +18/+44 km lon (west is coastline-limited,
        # not a request limit -- water simply does not extend further that way) around
        # Hanul, i.e. >=1.4x the measured max +12h displacement in every direction water
        # actually exists, and drove a live run_transport([3, 6, 12]) to READY.
        "ymin": 36.65,
        "ymax": 37.45,
        "xmin": 129.15,
        "xmax": 129.93,
    }
    ROMS_PAGE_SIZE = 300
    # The provider caps numOfRows at 300 (larger values return INVALID_REQUEST_PARAMETER_ERROR),
    # so a wider bbox means more pages, not bigger ones. The widened bbox above paged out at
    # ~300 pages live; this cap and `live_budget_s` (config/settings.py) both carry margin
    # above that measured cost so a genuine shortfall reports `partial: True` instead of
    # silently truncating.
    ROMS_MAX_PAGES = 400

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
        if source_id == "khoa_roms_live":
            return self._fetch_khoa_roms()
        if source_id == "khoa_crnt_fcst_reference":
            return self._fetch_khoa_crnt_fcst()
        if source_id == "khoa_hf_current_reference":
            return self._fetch_khoa_hf_current()
        raise LookupError(source_id)

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in km, used only to state numerically how far a
        reference point sits from Hanul -- never to imply that distance is small
        enough to matter for coverage."""
        from math import asin, cos, radians, sin, sqrt

        r_earth_km = 6371.0088
        p1, p2 = radians(lat1), radians(lat2)
        dphi = radians(lat2 - lat1)
        dlambda = radians(lon2 - lon1)
        a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
        return 2 * r_earth_km * asin(sqrt(a))

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
        return self._normalize_nifs(
            response,
            request_spec={
                "dataset_id": "jellyList",
                "sdate": params["sdate"],
                "edate": params["edate"],
            },
        )

    def _normalize_nifs(
        self, response: httpx.Response, *, request_spec: dict[str, Any]
    ) -> dict[str, Any]:
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
        if not normalized:
            raise ProviderNoDataError("no catalog rows")
        issued_at = self._latest_issued_at(
            [item.get("registered_at") for item in normalized],
            assume_tz=UTC,
        )
        return self._record(
            "nifs_jelly_catalog",
            normalized,
            response.status_code,
            result_code or "00",
            "https://www.nifs.go.kr/api/OpenAPI_json",
            issued_at=issued_at,
            request_spec=request_spec,
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
        if not normalized:
            raise ProviderNoDataError("no context rows")
        issued_at = self._latest_issued_at(
            [item.get("registered_at") for item in normalized],
            assume_tz=UTC,
        )
        return self._record(
            source_id,
            normalized,
            response.status_code,
            result_code or "00",
            "https://www.nifs.go.kr/api/OpenAPI_json",
            issued_at=issued_at,
            request_spec={
                "dataset_id": dataset_id,
                "sdate": params["sdate"],
                "edate": params["edate"],
            },
        )

    def _nifs_key(self, source_id: str) -> str | None:
        return {
            "nifs_jelly_catalog": self.settings.nifs_jelly_key,
            "nifs_redtide_list": self.settings.nifs_redtide_key,
            "nifs_soo_list": self.settings.nifs_soo_key,
        }.get(source_id)

    def _gyeongbuk_plant_distances(self, lat: Any, lon: Any) -> dict[str, Any]:
        """Report this HF station's distance to Hanul, the site this MVP targets."""
        if lat is None or lon is None:
            return {"distance_to_hanul_km": None}
        return {
            "distance_to_hanul_km": round(
                self._haversine_km(float(lat), float(lon), self.HANUL_LAT, self.HANUL_LON), 1
            )
        }

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
                    if result_code in {"20", "30", "31", "32"}:
                        raise PermissionError("upstream authorization rejected")
                    if result_code == "03":
                        continue
                    raise ValueError(f"provider result {result_code}")
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
            raise ProviderNoDataError("no valid rows")
        issued_at = self._latest_issued_at(
            [row.get("observed_at") for row in rows],
            assume_tz=ZoneInfo("Asia/Seoul"),
        )
        return self._record(
            "khoa_tw_recent_hanul",
            rows,
            status_code,
            result_code or "00",
            "https://apis.data.go.kr/1192136/twRecent/GetTWRecentApiService",
            issued_at=issued_at,
            request_spec={"station_codes": ["HB_0007", "HB_0008", "HB_0009"]},
        )

    def _fetch_khoa_roms(self) -> dict[str, Any]:
        """Fetch the KHOA ROMS surface forecast grid covering the Hanul demo domain.

        The provider pages a (grid point x forecast hour) product, so one bbox query
        returns many rows per cell. Pages are followed until ``totalCount`` is reached,
        the page cap is hit, or the live budget expires; a truncated read is reported as
        ``partial`` instead of being silently trimmed.
        """
        bbox = dict(self.ROMS_HANUL_BBOX)
        rows: list[dict[str, Any]] = []
        status_code = 200
        result_code = "00"
        total_count: int | None = None
        pages_received = 0
        failed_pages: list[int] = []
        partial = False
        started_at = time.monotonic()
        with self._client() as client:
            for page_no in range(1, self.ROMS_MAX_PAGES + 1):
                if time.monotonic() - started_at >= self.settings.live_budget_s:
                    partial = True
                    failed_pages.append(page_no)
                    break
                response = self._get(
                    client,
                    self.KHOA_ROMS_ENDPOINT,
                    params={
                        "serviceKey": self.settings.khoa_key,
                        "type": "json",
                        "numOfRows": self.ROMS_PAGE_SIZE,
                        "pageNo": page_no,
                        **bbox,
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
                    if result_code in {"20", "30", "31", "32"}:
                        raise PermissionError("upstream authorization rejected")
                    if result_code == "03":
                        break
                    raise ValueError(f"provider result {result_code}")
                body = payload.get("body") or {}
                if total_count is None and body.get("totalCount") is not None:
                    total_count = int(body["totalCount"])
                items = (body.get("items") or {}).get("item") or []
                if isinstance(items, dict):
                    items = [items]
                if not items:
                    break
                pages_received += 1
                for item in items:
                    rows.append(
                        {
                            "lat": item.get("lat"),
                            "lon": item.get("lot"),
                            "valid_at": item.get("predcDt"),
                            "current_direction": item.get("crdir"),
                            "current_speed": item.get("crsp"),
                            "water_temperature": item.get("wtem"),
                            "crdir_convention": "UNVERIFIED",
                        }
                    )
                if total_count is not None and len(rows) >= total_count:
                    break
            else:
                partial = total_count is not None and len(rows) < total_count
        if not rows:
            raise ProviderNoDataError("no valid rows")
        if total_count is not None and len(rows) < total_count:
            partial = True
        grid_summary = self._summarize_roms_grid(rows, bbox, total_count)
        # The provider publishes forecast hours but never the model run time, so the age of
        # this field is genuinely unknown. Reporting a guessed issue time would let a stale
        # run pass a freshness Gate, so the age stays unknown and the forecast window is
        # carried in the grid summary for the horizon Gate to judge instead.
        issued_at = None
        record = self._record(
            "khoa_roms_live",
            rows,
            status_code,
            result_code or "00",
            self.KHOA_ROMS_ENDPOINT,
            issued_at=issued_at,
            request_spec={"bbox": bbox, "num_of_rows": self.ROMS_PAGE_SIZE},
        )
        record["pages_received"] = pages_received
        record["partial"] = partial
        record["failed_pages"] = failed_pages
        record["rows_expected"] = total_count
        record["grid_summary"] = grid_summary
        return record

    @staticmethod
    def _summarize_roms_grid(
        rows: list[dict[str, Any]],
        bbox: dict[str, float],
        total_count: int | None,
    ) -> dict[str, Any]:
        """Describe the returned field so coverage Gates read measurements, not promises."""
        lats = sorted({row["lat"] for row in rows if row.get("lat") is not None})
        lons = sorted({row["lon"] for row in rows if row.get("lon") is not None})
        cells = sorted({(row["lat"], row["lon"]) for row in rows if row.get("lat") is not None})
        times = sorted({row["valid_at"] for row in rows if row.get("valid_at")})
        convention = verify_flow_direction_convention(rows)
        return {
            "requested_bbox": bbox,
            "cell_count": len(cells),
            "lat_count": len(lats),
            "lon_count": len(lons),
            "lat_spacing_deg": round(lats[1] - lats[0], 6) if len(lats) > 1 else None,
            "lon_spacing_deg": round(lons[1] - lons[0], 6) if len(lons) > 1 else None,
            "covered_bbox": {
                "ymin": lats[0] if lats else None,
                "ymax": lats[-1] if lats else None,
                "xmin": lons[0] if lons else None,
                "xmax": lons[-1] if lons else None,
            },
            "timestep_count": len(times),
            "valid_from_local": times[0] if times else None,
            "valid_to_local": times[-1] if times else None,
            "issue_time_published": False,
            "rows_expected": total_count,
            "is_area_field": len(cells) > 1,
            "crdir_convention": (
                "TOWARD_CHECK_BASED" if convention["verdict"] == TOWARD else "UNVERIFIED"
            ),
            "convention_check": convention,
            "depth_class": "surface_only",
        }

    def _fetch_khoa_crnt_fcst(self) -> dict[str, Any]:
        """Fetch a KHOA tidal-current forecast point used only as a direction reference.

        This endpoint reports ``crdir`` as a Korean 16-point compass **name**, not degrees,
        and ``crsp`` in a unit the provider does not document. Both are preserved verbatim
        so a later convention check compares raw provider output rather than a guess made
        here.
        """
        obs_code = self.CRNT_FCST_REFERENCE_OBS_CODE
        request_date = self.clock().astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        with self._client() as client:
            response = self._get(
                client,
                self.KHOA_CRNT_FCST_ENDPOINT,
                params={
                    "serviceKey": self.settings.khoa_key,
                    "type": "json",
                    "obsCode": obs_code,
                    "date": request_date,
                },
            )
        if response.status_code in {401, 403}:
            raise PermissionError("upstream authorization rejected")
        response.raise_for_status()
        payload = response.json()
        header = payload.get("header") or {}
        result_code = str(header.get("resultCode", ""))
        if result_code and result_code != "00":
            if result_code in {"20", "30", "31", "32"}:
                raise PermissionError("upstream authorization rejected")
            raise ValueError(f"provider result {result_code}")
        items = ((payload.get("body") or {}).get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        rows = [
            {
                "obs_code": obs_code,
                "station_name": item.get("obsvtrNm"),
                "lat": item.get("lat"),
                "lon": item.get("lot"),
                "valid_at": item.get("predcDt"),
                "current_direction_text": item.get("crdir"),
                "current_speed_raw": item.get("crsp"),
                "crdir_format": "korean_16point_text",
                "crsp_unit": "UNVERIFIED",
                "crdir_convention": "UNVERIFIED",
            }
            for item in items
        ]
        if not rows:
            raise ProviderNoDataError("no valid rows")
        record = self._record(
            "khoa_crnt_fcst_reference",
            rows,
            response.status_code,
            result_code or "00",
            self.KHOA_CRNT_FCST_ENDPOINT,
            issued_at=None,
            request_spec={"obs_code": obs_code, "date": request_date},
        )
        record["reference_only"] = True
        record["distance_note"] = "nearest_forecast_point_is_not_near_hanul"
        return record

    def _fetch_khoa_hf_current(self) -> dict[str, Any]:
        """Fetch KHOA's real-time HF-radar current stations, as southern/western-coast
        context points -- never as a Hanul field.

        There are exactly 13 valid ``obsCode`` values for this operation (probed
        exhaustively; any other code is rejected by the provider) and every one of them
        sits well south or west of Hanul, so no amount of station coverage here adds up
        to area-field coverage at the plant. Each station is read as a single snapshot
        row (``numOfRows=1``), the same shape as ``_fetch_khoa_points`` -- this endpoint
        actually paginates a small local mesh per station, but claiming that mesh as a
        field would repeat the mistake the now-permanently-rejected
        ``khoa_hf_current_regression`` source made, so only one representative point per
        station is kept. ``crdir``/``crsp`` are preserved verbatim, including when the
        provider reports them as null (observed live for HF_0073) -- a null observation
        is still a row, not a reason to drop the station from the batch.
        """
        rows: list[dict[str, Any]] = []
        status_code = 200
        result_code = "00"
        started_at = time.monotonic()
        with self._client() as client:
            for station_code in self.HF_STATION_CODES:
                if time.monotonic() - started_at >= self.settings.live_budget_s:
                    raise TimeoutError("live request budget exceeded")
                response = self._get(
                    client,
                    self.KHOA_HF_ENDPOINT,
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
                    if result_code in {"20", "30", "31", "32"}:
                        raise PermissionError("upstream authorization rejected")
                    if result_code == "03":
                        continue
                    raise ValueError(f"provider result {result_code}")
                items = ((payload.get("body") or {}).get("items") or {}).get("item") or []
                if isinstance(items, dict):
                    items = [items]
                for item in items:
                    lat, lon = item.get("lat"), item.get("lot")
                    rows.append(
                        {
                            "station_code": station_code,
                            "station_name": item.get("obsvtrNm"),
                            "lat": lat,
                            "lon": lon,
                            "observed_at": item.get("obsrvnDt"),
                            "current_direction": item.get("crdir"),
                            "current_speed": item.get("crsp"),
                            "crdir_convention": "UNVERIFIED",
                            **self._gyeongbuk_plant_distances(lat, lon),
                        }
                    )
        if not rows:
            raise ProviderNoDataError("no valid rows")
        issued_at = self._latest_issued_at(
            [row.get("observed_at") for row in rows],
            assume_tz=ZoneInfo("Asia/Seoul"),
        )
        record = self._record(
            "khoa_hf_current_reference",
            rows,
            status_code,
            result_code or "00",
            self.KHOA_HF_ENDPOINT,
            issued_at=issued_at,
            request_spec={"station_codes": list(self.HF_STATION_CODES)},
        )
        record["reference_only"] = True
        record["distance_note"] = "no_station_is_near_hanul"
        return record

    def _record(
        self,
        source_id: str,
        payload: Any,
        http_status: int,
        provider_result_code: str,
        endpoint: str,
        *,
        issued_at: str | None,
        request_spec: dict[str, Any],
    ) -> dict[str, Any]:
        fetched_at = self.clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint_input = json.dumps(
            {"source_id": source_id, **request_spec},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "source_id": source_id,
            "request_spec": request_spec,
            "request_fingerprint": hashlib.sha256(fingerprint_input.encode()).hexdigest(),
            "http_status": http_status,
            "provider_result_code": provider_result_code,
            "issued_at": issued_at,
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

    @staticmethod
    def _latest_issued_at(values: list[Any], *, assume_tz) -> str | None:
        parsed_values: list[datetime] = []
        for value in values:
            if value in {None, ""}:
                continue
            text = str(value).strip()
            try:
                if len(text) == 8 and text.isdigit():
                    parsed = datetime.strptime(text, "%Y%m%d").replace(tzinfo=assume_tz)
                elif len(text) == 10 and text[4] == "-" and text[7] == "-":
                    parsed = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=assume_tz)
                else:
                    parsed = datetime.fromisoformat(text)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=assume_tz)
            parsed_values.append(parsed.astimezone(UTC))
        if not parsed_values:
            return None
        return max(parsed_values).isoformat().replace("+00:00", "Z")


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
        real_mode_requested = bool(allowed & supported & {DataMode.LIVE, DataMode.CACHED})
        if (
            DataMode.SYNTHETIC in allowed
            and DataMode.SYNTHETIC in supported
            and not real_mode_requested
        ):
            return SourceResolution(
                source_id=source_id,
                source_class=definition.source_class,
                optional=definition.optional,
                state=SourceState.SYNTHETIC_EXPLICIT,
                data_mode=DataMode.SYNTHETIC.value,
                freshness="synthetic",
                provenance_kind="synthetic",
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
        except ProviderNoDataError:
            return SourceState.LIVE_NO_DATA
        except LookupError:
            return SourceState.LIVE_UNSUPPORTED
        except PermissionError:
            return SourceState.LIVE_AUTH_FAILED
        except (httpx.HTTPError, TimeoutError):
            return SourceState.LIVE_UNAVAILABLE
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return SourceState.LIVE_SCHEMA_INVALID
        self.cache.append(record)
        return self._live_resolution(definition, record)

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
        is_fixture = bool(record.get("fixture_checksum")) or str(
            record.get("adapter_version", "")
        ).startswith("fixture-")
        if is_fixture:
            age_seconds = None
            state, freshness = SourceState.CACHED_FIXTURE, "fixture"
        elif timestamp is None:
            age_seconds = None
            state, freshness = SourceState.CACHED_UNKNOWN_AGE, "unknown"
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
            provenance_kind="fixture" if is_fixture else "cache",
            payload=record.get("payload"),
            manifest=record,
        )

    def _live_resolution(
        self, definition: SourceDefinition, record: dict[str, Any]
    ) -> SourceResolution:
        timestamp = record.get("issued_at")
        if timestamp is None:
            age_seconds = None
            state, freshness = SourceState.LIVE_UNKNOWN_AGE, "unknown"
        else:
            parsed = datetime.fromisoformat(timestamp)
            age_seconds = max(0, int((self.clock().astimezone(UTC) - parsed).total_seconds()))
            fresh_ttl, stale_ttl = TTL_SECONDS.get(definition.source_id, (0, 0))
            if age_seconds <= fresh_ttl:
                state, freshness = SourceState.LIVE_OK, "fresh"
            elif age_seconds <= stale_ttl:
                state, freshness = SourceState.LIVE_STALE, "stale"
            else:
                state, freshness = SourceState.LIVE_EXPIRED, "expired"
        reason = PUBLIC_REASON.get(state)
        return SourceResolution(
            source_id=definition.source_id,
            source_class=definition.source_class,
            optional=definition.optional,
            state=state,
            public_reason=reason[1] if reason else None,
            public_reason_code=reason[0].value if reason else None,
            data_mode=DataMode.LIVE.value,
            fetched_at=record["fetched_at"],
            issued_at=timestamp,
            age_seconds=age_seconds,
            freshness=freshness,
            license=record.get("license", "public-data"),
            provenance_kind="upstream",
            payload=record["payload"],
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
            "nifs_jelly_detail2_unverified": self.settings.nifs_jelly_key,
            "khoa_crnt_fcst_reference": self.settings.khoa_key,
            "khoa_hf_current_reference": self.settings.khoa_key,
        }.get(source_id)
