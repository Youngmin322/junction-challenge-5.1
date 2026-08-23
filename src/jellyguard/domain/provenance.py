from __future__ import annotations

import hashlib
import json
from typing import Any

VOLATILE_FIELDS = {
    "as_of",
    "request_id",
    "latency_ms",
    "trace_id",
    "query_id",
    "run_id",
    "created_at",
    "provenance_ref",
    "audit_ref",
    "deterministic_result_digest",
}


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable(item) for key, item in sorted(value.items()) if key not in VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, float):
        return round(value, 7)
    return value


def deterministic_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        _stable(payload), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
