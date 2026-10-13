"""会话列表与置顶状态的持久化（sessions.json）。"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from braid.core.paths import atomic_write, config_dir


@dataclass
class SessionRecord:
    id: str
    title: str
    pinned: bool = False
    updated_at: float = 0.0


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "sessions.json"
        self._items: dict[str, SessionRecord] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for r in data.get("sessions", []):
                rec = SessionRecord(**r)
                self._items[rec.id] = rec

    def _save(self) -> None:
        data = {"version": 1, "sessions": [asdict(r) for r in self._items.values()]}
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def list_sessions(self) -> list[SessionRecord]:
        """置顶在前，各组内按 updated_at 倒序。"""
        return sorted(self._items.values(), key=lambda r: (not r.pinned, -r.updated_at))

    def upsert(self, id: str, title: str, updated_at: float | None = None) -> SessionRecord:
        rec = self._items.get(id)
        ts = time.time() if updated_at is None else updated_at
        if rec is None:
            rec = SessionRecord(id=id, title=title, updated_at=ts)
            self._items[id] = rec
        else:
            rec.title, rec.updated_at = title, ts
        self._save()
        return rec

    def set_pinned(self, id: str, pinned: bool) -> None:
        rec = self._items[id]
        if rec.pinned != pinned:
            rec.pinned = pinned
            self._save()

    def delete_session(self, id: str) -> None:
        if self._items.pop(id, None) is not None:
            self._save()
