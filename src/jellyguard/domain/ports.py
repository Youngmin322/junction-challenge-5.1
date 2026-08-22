from __future__ import annotations

from typing import Protocol


class KeyValueStore(Protocol):
    def put(self, key: str, value: dict) -> None: ...

    def get(self, key: str) -> dict | None: ...

    def values(self) -> list[dict]: ...
