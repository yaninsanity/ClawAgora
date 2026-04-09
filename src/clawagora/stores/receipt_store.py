from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any


class ReceiptRecord:
    def __init__(self, task_id: str, body: dict[str, Any], body_hash: str) -> None:
        self.task_id = task_id
        self.body = body
        self.body_hash = body_hash


class ReceiptStore(ABC):
    @abstractmethod
    def persist(self, task_id: str, body: dict[str, Any]) -> ReceiptRecord:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, task_id: str) -> ReceiptRecord | None:
        raise NotImplementedError


def hash_body(body: dict[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class InMemoryReceiptStore(ReceiptStore):
    def __init__(self) -> None:
        self._data: dict[str, ReceiptRecord] = {}

    def persist(self, task_id: str, body: dict[str, Any]) -> ReceiptRecord:
        h = hash_body(body)
        rec = ReceiptRecord(task_id=task_id, body=body, body_hash=h)
        self._data[task_id] = rec
        return rec

    def fetch(self, task_id: str) -> ReceiptRecord | None:
        return self._data.get(task_id)
