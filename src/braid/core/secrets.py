"""API Key 存储：优先系统钥匙串；不可用时只放进程内存，绝不写明文文件。

导入本模块不会触碰 keyring 后端，第一次调用时才解析。
"""

from __future__ import annotations

import contextlib

SERVICE = "braid"

INSTALL_HINT = (
    "系统钥匙串不可用，API Key 只保存在本次运行的内存里，退出后需要重新输入。"
    "Linux 上可安装 gnome-keyring 或 kwallet 并确保 Secret Service 在运行。"
)

_memory: dict[str, str] = {}


def keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail
    except Exception:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    if isinstance(backend, fail.Keyring):
        return False
    chained = getattr(backend, "backends", None)
    return not (chained is not None and len(chained) == 0)


def set_key(provider_id: str, key: str) -> bool:
    """保存 Key。返回 True 表示进了钥匙串，False 表示只存在内存里。"""
    if keyring_available():
        import keyring

        try:
            keyring.set_password(SERVICE, provider_id, key)
            _memory.pop(provider_id, None)
            return True
        except Exception:
            pass
    _memory[provider_id] = key
    return False


def get_key(provider_id: str) -> str | None:
    if provider_id in _memory:
        return _memory[provider_id]
    if keyring_available():
        import keyring

        try:
            return keyring.get_password(SERVICE, provider_id)
        except Exception:
            return None
    return None


def delete_key(provider_id: str) -> None:
    _memory.pop(provider_id, None)
    if keyring_available():
        import keyring

        with contextlib.suppress(Exception):
            keyring.delete_password(SERVICE, provider_id)
