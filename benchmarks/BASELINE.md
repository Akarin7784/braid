# 发布前性能基线（main `175d539`）

测量脚本：`benchmarks/baseline.py`（每次测量新开进程，先预热 1 次不计入，再取 7 次的中位数和 p95）。原始数据：`benchmarks/baseline_175d539.json`。

```bash
PYTHONPATH=src python benchmarks/baseline.py -n 7 --json benchmarks/baseline_175d539.json
```

## 机器

| 项 | 值 |
|---|---|
| CPU | Intel(R) Xeon(R) Processor，8 核（云主机，共享） |
| 内存 | 15.6 GiB |
| 系统 | Linux 6.12.94+ x86_64，glibc 2.41 |
| Python / PySide6 | 3.13.5 / 6.12.0 |
| 平台插件 | offscreen；xvfb（`xvfb-run`，1600×1000×24，Qt xcb） |
| 窗口 | 1280×800，浅色主题，Mock 后端，配置目录用临时目录 |

注意：这台机器是共享云主机，xvfb 的 p95 波动比较大，个别项上 offscreen 和 xvfb 相差最多约 40%。比较时请在同一台机器上用同一个平台插件。

## 结果（单位 ms，内存 MB）

| 指标 | offscreen 中位数 | offscreen p95 | xvfb 中位数 | xvfb p95 |
|---|---:|---:|---:|---:|
| 冷启动：spawn → 主窗口 `show()` 返回 | 483.9 | 505.0 | 573.0 | 811.7 |
| 冷启动：spawn → 首次 Paint | 573.2 | 605.1 | 663.7 | 953.7 |
| 　其中 `import PySide6.QtWidgets` | 91.9 | 96.3 | 89.5 | 123.7 |
| 　其中 `import braid`（主窗口 + Mock，PySide6 已加载） | 65.6 | 69.9 | 64.2 | 89.9 |
| 首次打开设置页 | **526.5** | 550.1 | **564.4** | 662.2 |
| 分区首次显示：模型与服务 | 2.1 | 2.4 | 2.9 | 3.6 |
| 　权限 | 7.5 | 8.0 | 8.6 | 11.4 |
| 　通用 | 5.9 | 6.5 | 7.2 | 8.1 |
| 　智能体 | 8.4 | 10.4 | 9.5 | 11.1 |
| 　MCP 服务 | **60.8** | 67.9 | **63.2** | 65.7 |
| 　规则与指令 | 7.7 | 8.4 | 8.2 | 8.6 |
| 　快捷键 | 10.4 | 12.8 | 12.0 | 13.6 |
| 　高级 | 9.6 | 10.2 | 10.9 | 16.3 |
| 空闲 RSS：启动后静置 500ms | 112.5 | 113.1 | 116.0 | 116.7 |
| 空闲 RSS：访问完 8 个设置分区后 | 148.4 | 148.8 | 151.9 | 152.5 |
| 主题切换 浅 → 深（真实路径，含重绘） | **470.5** | 497.1 | **466.2** | 511.7 |
| 主题切换 深 → 浅 | **458.0** | 494.9 | **476.6** | 502.3 |

各项口径：

- **spawn**：父进程启动子进程之前的时刻，所以冷启动包含解释器启动。
- **首次 Paint**：主窗口收到的第一个 `QEvent.Paint`，等待用的事件过滤器和超时计时器都挂在窗口下面。
- **分区首次显示**：`show_section` 加事件处理，再对当前页同步 `repaint()`，在设置页已经打开之后测。
- **主题切换**：`backend.set_config("general", {"theme": ...})`，走 `config_changed` → `apply_theme` → `chat_view.set_dark` 这条真实路径，再加同步重绘；每次运行切 3 个来回取平均。
- 测主题切换时，设置页已经建过，处于隐藏状态。

## `python -X importtime`（`import braid.ui.main_window, braid.backends.mock`，3 次中位数）

| 累计 ms | 自身 ms | 模块 |
|---:|---:|---|
| 165.0 | 20.8 | `braid.ui.main_window`（含 PySide6） |
| 81.1 | 11.7 | `PySide6.QtCore` |
| 61.8 | 0.3 | `shiboken6` |
| 45.1 | 0.9 | `shibokensupport.signature.loader` |
| 17.8 | 0.7 | `braid.ui.chat_controller` |
| 17.1 | 13.8 | `braid.ui.chat_view` |
| 10.4 | 4.6 | `braid.ui.composer` |
| 8.5 | 8.5 | `PySide6.QtGui` |
| 5.1 | 5.1 | `braid.theme.menu` |
| 4.4 | 0.5 | `braid.backends.mock_artifacts` |

braid 自己的导入只有约 65ms，其余是 PySide6 / shiboken 的固定开销。导入不是主要矛盾。

## 三个可着手的热点（本 PR 不修）

### 1. 首次打开设置页约 530ms：8 个分区页一次性全建好，钥匙串探测也在这一步

cProfile（`show_settings(True)`，共 590ms）的分布：

- `SettingsPage.__init__` 509ms。
- 10 次 `QScrollArea.setWidget` 合计 150ms，主要是全局 QSS 下首次 polish 整页控件。
- `secrets.keyring_available()` 150ms。`ModelsPage` 构建时就导入 keyring 并探测后端，绝大部分是 keyring 及其依赖的导入。
- 各分区页工厂合计约 150ms，其中智能体页 94ms。

建议：

- **按需建页**：只建默认分区；其余分区在第一次 `show_section` 时才构建并 `_install`。按上表，单页首显本来就只有 2–60ms。
- **推迟钥匙串探测**：放到第一次需要读写 Key 时，或用空闲计时器在后台预热（计时器挂在设置页下）。

预计首开可以降到 150ms 以内。

### 2. 主题切换约 460ms：`QApplication.setStyleSheet` 要重新 polish 全部约 660 个控件

- `apply_theme` 里的 `setStyleSheet` 单独就占 384–404ms，重绘只占约 13ms。
- 控件数 663，其中大部分是隐藏着的设置页（打开过一次就常驻）。

建议（任选或组合）：

- 关闭设置页时销毁它，或者配合热点 1 的按需建页，减少常驻控件。
- 把只和设置页相关的选择器拆成设置页自己的样式表，切主题时设置页不可见就延后到下次显示再套。
- 精简全局 QSS 里的后代选择器。

先做前两条，预计能减半。

### 3. MCP 分区首次显示约 61ms（其他分区 2–12ms）：等宽字体回退链首次解析很慢

- cProfile 显示 4 次 `QFontMetrics.elidedText` 共 48ms，即每行约 12ms。
- 原因：`#mcpTarget` 的 QSS 字体族 `"JetBrains Mono", "Menlo", "Consolas", monospace` 在 Linux 上前三个都没装，首次排版时 Qt 要逐个回退、做字形查找。
- 规则页、高级页用的 `mono_font()` 走的是已解析的回退列表，没有这个问题。

建议：

- `McpRow` 的命令 / URL 改用 `widgets.mono_font()`（与规则页一致），去掉 QSS 里的字体族；
- 或者在启动后用空闲时间预热一次等宽字体解析。

预计降到约 10ms。

## 其他观察

- 访问完 8 个设置分区后 RSS 增加约 36MB（112 → 148MB），并且常驻不释放。与热点 1、2 同源。
- spawn 到 `show()` 约 484ms，其中导入约 160ms，`MainWindow()` 构建和首帧样式套用占大头（见 `benchmarks/startup_phases.py`）。首次 Paint 比 `show()` 晚约 90ms。
