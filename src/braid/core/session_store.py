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
    project_id: str | None = None


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "sessions.json"
        self._items: dict[str, SessionRecord] = {}
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for r in data.get("sessions", []):
                r.setdefault("project_id", None)
                rec = SessionRecord(**r)
                self._items[rec.id] = rec

    def _save(self) -> None:
        data = {"version": 1, "sessions": [asdict(r) for r in self._items.values()]}
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def list_sessions(self) -> list[SessionRecord]:
        """置顶在前，各组内按 updated_at 倒序。"""
        return sorted(self._items.values(), key=lambda r: (not r.pinned, -r.updated_at))

    def upsert(
        self,
        id: str,
        title: str,
        updated_at: float | None = None,
        project_id: str | None = None,
    ) -> SessionRecord:
        rec = self._items.get(id)
        ts = time.time() if updated_at is None else updated_at
        if rec is None:
            rec = SessionRecord(id=id, title=title, updated_at=ts, project_id=project_id)
            self._items[id] = rec
        else:
            rec.title, rec.updated_at = title, ts
            if project_id is not None:
                rec.project_id = project_id
        self._save()
        return rec

    def set_pinned(self, id: str, pinned: bool) -> None:
        rec = self._items[id]
        if rec.pinned != pinned:
            rec.pinned = pinned
            self._save()

    def set_project(self, id: str, project_id: str | None) -> None:
        rec = self._items[id]
        if rec.project_id != project_id:
            rec.project_id = project_id
            self._save()

    def grouped(self) -> list[tuple[str | None, list[SessionRecord]]]:
        """按 project_id 分组；None（未分配）排最后，空组不出现，组内顺序同 list_sessions。"""
        groups: dict[str | None, list[SessionRecord]] = {}
        for r in self.list_sessions():
            groups.setdefault(r.project_id, []).append(r)
        keys = sorted(k for k in groups if k is not None)
        out: list[tuple[str | None, list[SessionRecord]]] = [(k, groups[k]) for k in keys]
        if None in groups:
            out.append((None, groups[None]))
        return out

    def delete_session(self, id: str) -> None:
        if self._items.pop(id, None) is not None:
            self._save()
