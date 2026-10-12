# 骨架截图 vs v3 线稿 偏差清单

## 已在本分支修（QSS）
| # | 偏差 | 修法 |
|---|---|---|
| 1 | 发送按钮是 QPushButton，规范里的圆形样式只匹配了 QToolButton，没生效 | 选择器改成 `#SendButton`，补 hover、disabled 状态 |
| 2 | `#Sidebar` 的 QSS padding 和布局 margins 叠加，留白不可控 | 去掉 QSS padding，边距统一由布局控制（见下方代码项 A） |
| 3 | 空状态和面板占位文字用的是正文色，太抢眼 | `#EmptyHint`、`#PanelPlaceholder` 改用三级文字色 text3 |
| 4 | 窗口按钮常态颜色过深 | ghost 按钮常态用 text3，hover 时变成正文色 |
| 5 | 会话项高度和选中态不明显 | padding 7×10，选中项加粗 |
| 6 | 模型下拉露出系统箭头 | 隐藏系统箭头（▾ 由代码加在文字后，见代码项 E） |
| 7 | （上一轮已修）tab 底线、模型 chip 样式、输入框双层背景 | — |

## 需要 Qt前端开发 改代码（QSS 改不了）
| # | 偏差 | v3 / 规范 | 现状 |
|---|---|---|---|
| A | 左栏边距 | 布局 margins 16,18,16,18 | 12,12,12,12 |
| B | 右栏宽度 | 默认 420（可拖 320–720） | 280 |
| C | 对话列 | 最大宽 680 居中，消息间距 18，顶部留白 52 | 撑满整个中栏 |
| D | 输入框阴影 | e3（blur 24, y4, 10% 黑），深色主题传 `dark=True` | e2，深色时没传 |
| E | 输入框底栏 | `+`、模型 ▾、权限模式 ▾、推理强度 ▾，按钮用 QToolButton+QMenu | 只有 📎 和模型下拉 |
| F | 中栏顶部 | 左上角侧栏开关 ◧，正中"项目名 / 会话标题"（caption），右上角面板开关 ◨ | 只有窗口按钮 |
| G | 空状态和占位标签 | 设置 objectName 为 `EmptyHint` 和 `PanelPlaceholder` | 没有 objectName |
| H | 状态栏 | 底部 26px `#StatusBar`：分支 · 改动数 · MCP 连接数 | 没有 |
| I | 右栏 tab | Artifacts、产物、浏览器、Git、Diff、终端、任务 | 缺前两个 |
