"""应用配置目录（QStandardPaths.AppConfigLocation）。"""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """返回配置目录并确保存在。可用环境变量 BRAID_CONFIG_DIR 覆盖（测试用）。"""
    override = os.environ.get("BRAID_CONFIG_DIR")
    if override:
        path = Path(override)
    else:
        from PySide6.QtCore import QStandardPaths

        loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        path = Path(loc or Path.home() / ".config" / "braid")
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
