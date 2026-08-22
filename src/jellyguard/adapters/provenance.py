from __future__ import annotations

import hashlib
import json
from typing import Any


def fixture_manifest(
    *,
    source_id: str,
    payload: Any,
    source_data_mode: str,
    redacted_endpoint: str,
    rows_received: int,
    provider_result_code: str = "FIXTURE",
) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    request_spec = {"source_id": source_id, "mode": source_data_mode}
    request_bytes = json.dumps(request_spec, separators=(",", ":"), sort_keys=True).encode()
    checksum = hashlib.sha256(body).hexdigest()
    return {
        "source_id": source_id,
        "request_spec": request_spec,
        "redacted_endpoint": redacted_endpoint,
        "http_status": None,
        "provider_result_code": provider_result_code,
        "fetched_at": None,
        "issued_at": None,
        "valid_at": None,
        "content_checksum": checksum,
        "request_fingerprint": hashlib.sha256(request_bytes).hexdigest(),
        "fixture_checksum": checksum,
        "source_data_mode": source_data_mode,
        "adapter_version": "fixture-v1",
        "license": "public-data-demo-fixture",
        "rows_received": rows_received,
        "rows_expected": rows_received,
        "pages_received": 1,
        "pages_expected": 1,
        "partial": False,
        "failed_pages": [],
    }
