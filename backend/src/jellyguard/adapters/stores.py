from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import Lock


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._lock = Lock()

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._items[key] = deepcopy(value)

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._items.get(key)
            return deepcopy(value) if value is not None else None

    def values(self) -> list[dict]:
        with self._lock:
            return [deepcopy(value) for value in self._items.values()]


class JsonlStore:
    """Small append-only JSONL store used for demo runs and provenance."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, dict] = {}
        self._lock = Lock()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                self._items[record["_key"]] = record["value"]

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            if key in self._items:
                raise ValueError(f"append-only key already exists: {key}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {"_key": key, "value": deepcopy(value)}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._items[key] = deepcopy(value)

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._items.get(key)
            return deepcopy(value) if value is not None else None

    def values(self) -> list[dict]:
        with self._lock:
            return [deepcopy(value) for value in self._items.values()]
