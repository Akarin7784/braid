"""冒烟测试：包能导入、模拟后端可用、主窗口能创建并显示。"""
import importlib

import pytest

MODULES = [
    "braid",
    "braid.app",
    "braid.core.backend",
    "braid.backends.mock",
    "braid.ui.main_window",
    "braid.ui.tray",
    "braid.theme.shadows",
]


@pytest.mark.parametrize("name", MODULES)
def test_import(name):
    importlib.import_module(name)


def test_mock_backend_implements_interface():
    from braid.backends import mock
    from braid.core.backend import AgentBackend

    impls = [
        v for v in vars(mock).values()
        if isinstance(v, type) and issubclass(v, AgentBackend) and v is not AgentBackend
    ]
    assert impls, "mock.py 里没有找到 AgentBackend 的实现"
    for cls in impls:
        assert not getattr(cls, "__abstractmethods__", None), cls


def test_main_window_shows(qtbot):
    from braid.ui import main_window

    win_cls = next(
        v for k, v in vars(main_window).items()
        if isinstance(v, type) and k.endswith("Window")
    )
    try:
        win = win_cls()
    except TypeError:
        from braid.backends import mock
        from braid.core.backend import AgentBackend

        backend = next(
            v for v in vars(mock).values()
            if isinstance(v, type) and issubclass(v, AgentBackend) and v is not AgentBackend
        )()
        win = win_cls(backend)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    assert win.isVisible()
