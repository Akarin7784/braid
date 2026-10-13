"""模拟产物来源：产出几种示例产物（Markdown / 代码带前版本 / HTML）。"""

from __future__ import annotations

import itertools

from braid.core.artifacts import Artifact, ArtifactSource

_SAMPLES = [
    ("README.md", "# Braid\n\n轻量的桌面 Agent 界面。\n\n- 三栏布局\n- 流式输出\n", None),
    (
        "app.py",
        'def main() -> None:\n    print("hello, braid")\n',
        'def main():\n    print("hello")\n',
    ),
    ("report.html", "<h2>报告</h2><p>共 <b>3</b> 项产物。</p>", None),
]


class MockArtifactSource(ArtifactSource):
    def __init__(self) -> None:
        super().__init__()
        self._items: list[Artifact] = []
        self._ids = itertools.count(1)
        self._cycle = itertools.cycle(_SAMPLES)

    def list_artifacts(self) -> list[Artifact]:
        return list(self._items)

    def produce(self) -> Artifact:
        name, content, prev = next(self._cycle)
        a = Artifact(id=f"a{next(self._ids)}", name=name, content=content, previous=prev)
        self._items.append(a)
        self.artifact_added.emit(a)
        return a

    def seed(self, n: int = 3) -> None:
        for _ in range(n):
            self.produce()
