# 设计规范 v1（基于 wireframe_main_v3）

原则：无标题栏、无边框、无分割线。区域区分只靠 **留白 + 渐变底色 + 柔和阴影**。圆角 10–14px。

## 1. 色板（tokens.json 为单一来源，QSS 由它生成）
| Token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| bg.app | #FDFDFD | #1B1B1A | 对话区底 |
| bg.sidebar | #F4F4F3→#F9F9F8 | #222221→#1E1E1D | 左栏横向渐变 |
| bg.panel | #FBFBFA→#F6F6F5 | #1E1E1D→#232322 | 右栏横向渐变 |
| bg.surface | #FFFFFF | #2A2A29 | 卡片、输入框、弹窗 |
| bg.subtle | #F3F3F2 | #262625 | 工具调用块、代码块 |
| bg.control | #F0F0EF | #30302F | 次级按钮、chip |
| bg.hover | #ECECEB | #343433 | hover / 选中 tab |
| bg.active | #E9E9E8 | #3A3A39 | 选中会话 |
| bg.userBubble | #EFEFEE | #2F2F2E | 用户消息气泡 |
| text.primary | #1F1F1E | #ECECEA | 正文 |
| text.secondary | #6B6B69 | #A3A3A0 | 次要 |
| text.tertiary | #9E9E9B | #73736F | 占位、分组标题 |
| accent | #555555 | #E6E6E3 | 主按钮、发送（中性强调） |
| accent.text | #FFFFFF | #1B1B1A | 主按钮文字 |
| accent.brand | #C96442 | #D97757 | 焦点环、链接、进度（克制使用） |
| success | #2E8B57 | #5CC28A | Git A、已连接 |
| warning | #B26A00 | #E0A54A | Git M、需审批 |
| danger | #C0392B | #E2685B | Git D、删除、高风险 |
| scrim | #00000033 | #00000080 | 模态遮罩 |

## 2. 字体
- 界面：系统字体优先 —— macOS "PingFang SC"/SF，Windows "Microsoft YaHei UI"/Segoe UI，Linux "Noto Sans CJK SC"。
- 等宽：JetBrains Mono → Cascadia Code → Menlo → Consolas。
| 级别 | 字号/行高 | 字重 | 用途 |
|---|---|---|---|
| title | 18/26 | 600 | 弹窗、设置页标题 |
| body | 14/22 | 400 | 消息正文、输入框 |
| ui | 13/20 | 400/600 | 按钮、列表、tab |
| caption | 12/18 | 400 | 分组标题、元信息、状态栏 |
| code | 13/20 | 400 | 代码块、diff、终端 |

## 3. 间距（4px 基准）
4 / 8 / 12 / 16 / 24 / 32 / 48。左栏内边距 18×16；右栏内容 18；对话列最大宽 680 居中，消息间距 18；顶部留白 52。
栏宽：左 240（180–360 可拖），右 420（320–720 可拖），对话区最小 480。拖动手柄 6px 透明，hover 时显示 2px 圆角 bg.hover 条。

## 4. 圆角
| r.sm 6 | 复选框、tag |
| r.md 10 | 按钮、列表项、tab、输入行 |
| r.lg 12 | 工具块、chip、文本域 |
| r.xl 14 | 卡片、用户气泡 |
| r.2xl 16 | 主输入框、弹窗、快捷窗口 |
| 50% | 发送按钮、头像、状态点 |

## 5. 阴影（QSS 不支持 box-shadow，用 QGraphicsDropShadowEffect）
| 级别 | 浅色 | 深色 | 用于 |
|---|---|---|---|
| e1 | blur 12, y2, #0000000C | blur 12, y2, #00000059 | 文本域、小卡 |
| e2 | blur 18, y4, #0000000F | blur 18, y4, #00000066 | 文件卡片 |
| e3 | blur 24, y4, #0000001A | blur 24, y4, #00000080 | 主输入框 |
| e4 | blur 40, y12, #00000024 | blur 40, y12, #0000008C | 弹窗、快捷窗口、菜单 |
Qt 只能叠一层阴影，取上表单层即可。

## 6. 状态
- hover：底色升一级（control→hover）；pressed：再升一级（active）。
- focus：1.5px accent.brand 外描边（仅键盘焦点，用 :focus 在输入框上）。
- disabled：文字 text.tertiary，底色不变，透明度 0.5。
- 动效：150ms ease-out（hover/展开），200ms（面板显隐），流式光标闪烁 1s。

## 7. 组件约定（objectName 供 QSS 选择）
Sidebar `#Sidebar`、对话区 `#ChatArea`、右栏 `#SidePanel`、主输入框 `#Composer`、主按钮 `QPushButton[variant="primary"]`、次级 `[variant="secondary"]`、幽灵 `[variant="ghost"]`、危险 `[variant="danger"]`、chip `[role="chip"]`、会话项 `QListView#SessionList`、工具块 `QFrame[role="toolBlock"]`、卡片 `QFrame[role="card"]`、用户气泡 `QFrame[role="userBubble"]`、面板 tab `QTabBar#PanelTabs`、状态栏 `#StatusBar`。

## 8. 补充线稿
见 `wireframes/`：权限弹窗、设置页、快捷窗口、文件预览。
- 权限弹窗：Enter = **仅本次允许**（默认），始终允许为次级，拒绝为幽灵按钮；显示工具名、服务器、参数摘要、风险等级、持久化范围、撤销位置。
