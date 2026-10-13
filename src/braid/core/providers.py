"""服务商配置：存 providers.json，不含任何 Key（Key 在 secrets 里）。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from braid.core import secrets
from braid.core.paths import atomic_write, config_dir

KINDS = ("openai", "anthropic", "openai-compatible", "ollama")


@dataclass
class Provider:
    name: str
    kind: str = "openai-compatible"
    base_url: str = ""
    models: list[str] = field(default_factory=list)
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class ProviderStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "providers.json"
        self._items: list[Provider] = []
        self.default_model: str | None = None
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._items = [Provider(**p) for p in data.get("providers", [])]
        self.default_model = data.get("default_model")

    def save(self) -> None:
        data = {
            "version": 1,
            "default_model": self.default_model,
            "providers": [asdict(p) for p in self._items],
        }
        atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    def list(self) -> list[Provider]:
        return list(self._items)

    def get(self, provider_id: str) -> Provider | None:
        return next((p for p in self._items if p.id == provider_id), None)

    def upsert(self, provider: Provider) -> None:
        if provider.kind not in KINDS:
            raise ValueError(f"未知服务商类型: {provider.kind}")
        for i, p in enumerate(self._items):
            if p.id == provider.id:
                self._items[i] = provider
                break
        else:
            self._items.append(provider)
        self.save()

    def remove(self, provider_id: str) -> None:
        self._items = [p for p in self._items if p.id != provider_id]
        secrets.delete_key(provider_id)
        self.save()
