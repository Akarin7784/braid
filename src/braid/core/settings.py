"""应用设置（第一版只放内存里，后续接 QSettings）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Settings:
    default_model: str = "mock-large"
    default_reasoning: str = "medium"


settings = Settings()
