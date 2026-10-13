"""把 AgentBackend 的流式输出接到 ChatView：发送、停止、重试、编辑。"""

from __future__ import annotations

from collections.abc import Iterator

from PySide6.QtCore import QObject, QTimer, Signal

from braid.core.backend import AgentBackend, StreamChunk
from braid.ui.chat_view import ChatView


class ChatController(QObject):
    busyChanged = Signal(bool)
    editRequested = Signal(str)

    def __init__(self, backend: AgentBackend, view: ChatView, model: str = "") -> None:
        super().__init__(view)
        self.backend, self.view, self.model_id = backend, view, model
        self.session_id: str | None = None
        self.reasoning: str | None = None  # None：用模型默认
        self._it: Iterator[StreamChunk] | None = None
        # 后端是同步生成器：用 0ms 定时器分片拉取，不阻塞 UI；真实后端可换成线程/asyncio。
        self._pump = QTimer(self, interval=0)
        self._pump.timeout.connect(self._pull)
        view.actionTriggered.connect(self._on_action)

    @property
    def busy(self) -> bool:
        return self._it is not None

    def open_session(self, session_id: str) -> None:
        self.stop()
        self.session_id = session_id
        s = next(x for x in self.backend.list_sessions() if x.id == session_id)
        self.view.chat_model.set_messages([(m.role, m.text) for m in s.messages])
        self.view.scrollToBottom()

    def send(self, text: str) -> None:
        if not text.strip() or self.busy or self.session_id is None:
            return
        self.view.chat_model.append("user", text)
        row = self.view.chat_model.append("assistant", streaming=True)
        self._start(text, row)

    def _start(self, text: str, row: int) -> None:
        assert self.session_id is not None
        self._it = iter(
            # 档位 id 来自后端的 ModelInfo.efforts；None 表示用模型默认
            self.backend.send(self.session_id, text, self.model_id, self.reasoning)
        )
        self.view.stream.start(row)
        self._pump.start()
        self.busyChanged.emit(True)

    def _pull(self) -> None:
        assert self._it is not None
        for _ in range(8):  # 每轮最多取 8 个块
            chunk = next(self._it, StreamChunk("done"))
            if chunk.kind == "text":
                self.view.stream.push(chunk.data)
            elif chunk.kind == "done":
                self._end()
                return

    def stop(self) -> None:
        if self.busy:
            self._end()

    def _end(self) -> None:
        self._pump.stop()
        self._it = None
        self.view.stream.stop()
        self.busyChanged.emit(False)

    def _on_action(self, row: int, action: str) -> None:
        items = self.view.chat_model.items
        if action == "retry" and not self.busy and row > 0:
            prompt = items[row - 1].text
            self.view.chat_model.new_variant(row)
            self._start(prompt, row)
        elif action == "edit":
            self.editRequested.emit(items[row].text)
