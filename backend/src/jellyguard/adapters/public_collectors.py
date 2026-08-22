from __future__ import annotations

import importlib.util
from types import ModuleType
from typing import Any

from jellyguard.config.settings import (
    BACKEND_ROOT,
    Settings,
    export_legacy_collector_credentials,
)

COLLECTORS_ROOT = BACKEND_ROOT / "collectors"


DATASETS: dict[str, dict[str, Any]] = {
    "jellyfish": {
        "label": "해파리 보고",
        "source": "국립수산과학원 해파리정보",
        "cadence": "주간",
        "collector": "nifs_jelly",
        "live_sources": ["nifs_jelly_catalog"],
        "checks": ["보고서와 위치 관측 구분", "미관측과 미출현 구분", "게시일 최신성 확인"],
    },
    "ocean_current": {
        "label": "해류 관측",
        "source": "KHOA 해양관측부이·HF-RADAR",
        "cadence": "시간별 통합",
        "collector": "khoa_current",
        "live_sources": ["khoa_tw_recent_hanul"],
        "checks": ["유향 정의 확인", "u/v 단위 확인", "레이더·부이 시간 정렬"],
    },
    "marine_environment": {
        "label": "적조·해양환경",
        "source": "국립수산과학원 적조·정선해양관측",
        "cadence": "자료원별",
        "collector": "nifs_environment",
        "live_sources": ["nifs_redtide_list", "nifs_soo_list"],
        "checks": ["수온·용존산소 단위 확인", "관측 수심 확인", "QC·결측값 확인"],
    },
    "risk_zone": {
        "label": "취수구 접근영역",
        "source": "JellyGuard 조건부 연결 계산",
        "cadence": "시나리오 실행 시",
        "collector": "risk_engine",
        "live_sources": [],
        "checks": ["합성·실자료 표시", "해류·수심 coverage 확인", "확률이 아닌 조건부 연결로 표기"],
    },
}


class PublicCollectors:
    """Load the legacy public-data collectors without making them the app entrypoint."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._modules: dict[str, ModuleType] = {}

    def _export_credentials(self) -> None:
        export_legacy_collector_credentials(self.settings)

    def _load(self, module_name: str, filename: str) -> ModuleType:
        if module_name in self._modules:
            return self._modules[module_name]
        self._export_credentials()
        path = COLLECTORS_ROOT / filename
        spec = importlib.util.spec_from_file_location(f"jellyguard_collectors.{module_name}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"수집기 모듈을 열 수 없습니다: {filename}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SystemExit as exc:
            raise RuntimeError(str(exc)) from exc
        self._modules[module_name] = module
        return module

    def list_datasets(self) -> list[dict[str, Any]]:
        return [self.dataset_status(dataset_id) for dataset_id in DATASETS]

    def dataset_status(self, dataset_id: str) -> dict[str, Any]:
        definition = DATASETS.get(dataset_id)
        if definition is None:
            raise KeyError(dataset_id)
        configured = self._configured(dataset_id)
        if dataset_id == "risk_zone":
            connection = "synthetic_ready"
        elif configured:
            connection = "credentials_configured"
        else:
            connection = "credentials_required"
        return {
            "id": dataset_id,
            **definition,
            "configured": configured,
            "connection": connection,
            "live_enabled": bool(
                set(definition["live_sources"]) & self.settings.enabled_live_sources()
            ),
        }

    def dataset_quality(self, dataset_id: str) -> dict[str, Any]:
        status = self.dataset_status(dataset_id)
        ready = dataset_id == "risk_zone" or status["configured"]
        return {
            "dataset": status["label"],
            "ready": ready,
            "mode": "synthetic" if dataset_id == "risk_zone" else ("live-capable" if ready else "fixture"),
            "reason": (
                "합성 시나리오 엔진과 테스트가 준비되어 있습니다."
                if dataset_id == "risk_zone"
                else (
                    "제공기관 인증키가 설정되어 실제 수집을 실행할 수 있습니다."
                    if ready
                    else "제공기관 인증키가 없어 고정 재생자료만 사용할 수 있습니다."
                )
            ),
            "requiredChecks": status["checks"],
            "nextAction": (
                "실제 해류·수심 어댑터를 연결한 뒤 조건부 접근영역을 실행하세요."
                if dataset_id == "risk_zone"
                else "LIVE 소스를 활성화하고 출처·시각·단위 검증을 먼저 수행하세요."
            ),
        }

    def _configured(self, dataset_id: str) -> bool:
        if dataset_id == "jellyfish":
            return bool(self.settings.nifs_jelly_key)
        if dataset_id == "ocean_current":
            return bool(self.settings.khoa_key)
        if dataset_id == "marine_environment":
            return bool(self.settings.nifs_redtide_key or self.settings.nifs_soo_key)
        return True

    def get_ocean_current(
        self,
        *,
        date: str | None = None,
        hours: int = 24,
        tolerance_min: int = 60,
        include_series: bool = False,
        include_extra: bool = True,
    ) -> dict[str, Any]:
        module = self._load("ocean_current", "해류데이터_통합.py")
        return module.build_dataset(
            date=date,
            hours=hours,
            tolerance_min=tolerance_min,
            include_series=include_series,
            include_extra=include_extra,
            verbose=False,
        )

    def get_jellyfish_reports(
        self,
        *,
        sdate: str | None = None,
        edate: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        module = self._load("jellyfish", "해파리정보_수집.py")
        return module.build_dataset(sdate=sdate, edate=edate, days=days, verbose=False)

    def get_marine_environment(
        self,
        *,
        sdate: str | None = None,
        edate: str | None = None,
        redtide_days: int = 30,
        soo_days: int = 365,
    ) -> dict[str, Any]:
        module = self._load("marine_environment", "적조_정선해양_수집.py")
        return module.build_dataset(
            sdate=sdate,
            edate=edate,
            redtide_days=redtide_days,
            soo_days=soo_days,
            verbose=False,
        )
