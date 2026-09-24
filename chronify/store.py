# Chronify — a macOS menu bar work tracker.
# Copyright (C) 2026 Zepuff
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from chronify.config import BASE_DIR


_locks = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _load(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class JsonList:
    def __init__(
        self,
        filename: str,
        sort_key: Optional[Callable] = None,
        reverse: bool = False,
    ):
        self.path = BASE_DIR / filename
        self._sort_key = sort_key
        self._reverse = reverse
        self._lock = _lock_for(self.path)

    def read_raw(self) -> list:
        with self._lock:
            return _load(self.path, [])

    def read(self) -> list:
        items = self.read_raw()
        if self._sort_key is None:
            return items
        return sorted(items, key=self._sort_key, reverse=self._reverse)

    def write(self, items: list) -> None:
        with self._lock:
            _save(self.path, items)

    def add(self, **fields) -> dict:
        entry = {"id": new_id(), "created_at": time.time()}
        entry.update(fields)
        with self._lock:
            self.write([entry] + self.read_raw())
        return entry

    def append(self, **fields) -> dict:
        entry = {"id": new_id(), "created_at": time.time()}
        entry.update(fields)
        with self._lock:
            self.write(self.read_raw() + [entry])
        return entry

    def get(self, item_id: str) -> Optional[dict]:
        for item in self.read_raw():
            if item.get("id") == item_id:
                return item
        return None

    def update(self, item_id: str, **fields) -> bool:
        with self._lock:
            items = self.read_raw()
            for item in items:
                if item.get("id") == item_id:
                    item.update(fields)
                    self.write(items)
                    return True
            return False

    def delete(self, item_ids) -> int:
        ids = set(item_ids)
        if not ids:
            return 0
        with self._lock:
            items = self.read_raw()
            remaining = [i for i in items if i.get("id") not in ids]
            self.write(remaining)
            return len(items) - len(remaining)


class JsonDict:
    def __init__(self, filename: str):
        self.path = BASE_DIR / filename
        self._lock = _lock_for(self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return _load(self.path, {}).get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = _load(self.path, {})
            data[key] = value
            _save(self.path, data)