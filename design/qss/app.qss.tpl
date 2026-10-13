/* 由 build_qss.py 从 tokens.json 生成；勿手改 app_light.qss / app_dark.qss */
* { font-size: 13px; color: ${text}; outline: none; }
QWidget { background: transparent; border: none; selection-background-color: ${sel}; }
QMainWindow, #ChatArea { background: ${bg_app}; }
#Sidebar { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 ${sb_a}, stop:0.8 ${sb_a}, stop:1 ${sb_b}); }
#SidePanel { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 ${pn_a}, stop:0.2 ${pn_b}, stop:1 ${pn_b}); }
#StatusBar { background: ${sb_a}; color: ${text2}; font-size: 12px; min-height: 26px; padding: 0 14px; }
QSplitter::handle { background: transparent; width: 6px; }
QSplitter::handle:hover { background: ${hover}; }
QLabel[role="caption"] { color: ${text3}; font-size: 12px; }
QLabel[role="title"] { font-size: 18px; font-weight: 600; }
QLabel[role="secondary"] { color: ${text2}; }

QPushButton, QToolButton { background: ${control}; border-radius: 10px; padding: 6px 12px; }
QPushButton:hover, QToolButton:hover { background: ${hover}; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked { background: ${active}; }
QPushButton:disabled, QToolButton:disabled { color: ${text3}; }
QPushButton[variant="primary"] { background: ${accent}; color: ${accent_text}; font-weight: 600; }
QPushButton[variant="primary"]:hover { background: ${accent_hover}; }
QPushButton[variant="ghost"], QToolButton[variant="ghost"] { background: transparent; color: ${text2}; }
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover { background: ${hover}; color: ${text}; }
QPushButton[variant="danger"] { background: transparent; color: ${danger}; }
QPushButton[variant="danger"]:hover { background: ${hover}; }
#SendButton { background: ${accent}; color: ${accent_text}; border-radius: 17px; min-width: 34px; min-height: 34px; padding: 0; }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton[role="chip"], QLabel[role="chip"] { background: ${control}; border-radius: 12px; padding: 4px 12px; font-size: 12px; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox { background: ${hover}; border-radius: 12px; padding: 8px 12px; border: 1.5px solid transparent; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: ${brand}; }
QLineEdit[placeholderText] { color: ${text}; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: ${surface}; border-radius: 10px; padding: 4px; }
#Composer { background: ${surface}; border-radius: 16px; }
#Composer QPlainTextEdit { background: transparent; padding: 4px; font-size: 14px; border: none; }
QPlainTextEdit[role="textarea"] { background: ${surface}; }

QListView, QListWidget, QTreeView { background: transparent; }
QListView::item, QListWidget::item, QTreeView::item { border-radius: 10px; padding: 6px 8px; margin: 1px 0; }
QListView::item:hover, QListWidget::item:hover, QTreeView::item:hover { background: ${hover}; }
QListView::item:selected, QListWidget::item:selected, QTreeView::item:selected { background: ${active}; color: ${text}; }

QFrame[role="card"], QDialog, #QuickWindow { background: ${surface}; border-radius: 14px; }
QFrame[role="toolBlock"], QFrame[role="code"] { background: ${subtle}; border-radius: 12px; }
QFrame[role="userBubble"] { background: ${bubble}; border-radius: 14px; }
QTextBrowser, QTextBrowser[role="markdown"] { background: transparent; font-size: 14px; }

QTabBar::tab { background: transparent; color: ${text3}; padding: 4px 8px; margin-right: 2px; border-radius: 8px; }
QTabBar::tab:hover { color: ${text}; }
QTabBar::tab:selected { background: ${hover}; color: ${text}; font-weight: 600; }
QTabWidget::pane { border: none; }

QCheckBox::indicator { width: 14px; height: 14px; border-radius: 4px; background: ${check}; }
QCheckBox::indicator:checked { background: ${accent}; }
QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; background: ${check}; }
QRadioButton::indicator:checked { background: ${accent}; }
QSlider::groove:horizontal { height: 4px; background: ${hover}; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: ${accent}; border-radius: 7px; }

QMenu { background: ${surface}; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 6px 14px; border-radius: 8px; }
QMenu::item:selected { background: ${hover}; }
QMenu::separator { height: 6px; background: transparent; }
QToolTip { background: ${accent}; color: ${accent_text}; border: none; border-radius: 6px; padding: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: ${active}; border-radius: 3px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: ${text3}; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle:horizontal { background: ${active}; border-radius: 3px; min-width: 32px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; width: 0; height: 0; }

QLabel[status="A"] { color: ${success}; font-weight: 600; }
QLabel[status="M"] { color: ${warning}; font-weight: 600; }
QLabel[status="D"] { color: ${danger}; font-weight: 600; }
QLabel[risk="low"] { color: ${success}; } QLabel[risk="medium"] { color: ${warning}; } QLabel[risk="high"] { color: ${danger}; }

/* —— v1.1：并入 app.py 的 EXTRA_QSS，并修正首轮截图问题 —— */
#ComposerInput { background: transparent; border: none; padding: 4px; font-size: 14px; }
#ChatArea QPushButton[variant="ghost"] { font-size: 14px; }
QTabBar { qproperty-drawBase: 0; }
QTabWidget::tab-bar { border: none; }
#Composer QComboBox, #Composer QToolButton { background: ${control}; border-radius: 10px; padding: 4px 10px; border: none; font-size: 12px; }
#Composer QComboBox:hover, #Composer QToolButton:hover { background: ${hover}; }
#Composer #SendButton { background: ${accent}; color: ${accent_text}; border-radius: 17px; padding: 0; }

/* —— v1.2：骨架截图 vs v3 线稿对照修正 —— */
#SendButton:hover { background: ${accent_hover}; }
#SendButton:disabled { background: ${active}; color: ${text3}; }
#EmptyHint, #PanelPlaceholder { color: ${text3}; font-size: 13px; }
#Sidebar QPushButton[variant="secondary"] { padding: 8px 12px; }
#SessionList::item { padding: 7px 10px; }
#SessionList::item:selected { font-weight: 600; }
QTabBar#PanelTabs::tab { padding: 4px 8px; font-size: 13px; }
#ChatArea QPushButton[variant="ghost"] { color: ${text3}; border-radius: 8px; }
#ChatArea QPushButton[variant="ghost"]:hover { color: ${text}; }
#Composer QComboBox::down-arrow { image: none; width: 0; }
#Composer QComboBox { padding-right: 10px; }

/* —— v1.3：多级菜单（模型 + 推理强度）。$${assets} 由 load_qss 在运行时替换为图标目录 —— */
QMenu { background: ${surface}; border: none; border-radius: 12px; padding: 6px; }
QMenu[rounded="true"] { background: transparent; padding: 24px; qproperty-surfaceColor: "${surface}"; }
QMenu::item { color: ${text}; padding: 7px 30px 7px 32px; border-radius: 8px; min-width: 150px; font-size: 13px; }
QMenu::item:selected { background: ${hover}; }
QMenu::item:checked { background: ${active}; font-weight: 600; }
QMenu::item:checked:selected { background: ${hover}; }
QMenu::item:disabled { color: ${text3}; background: transparent; font-size: 12px; padding: 8px 12px 3px 12px; }
QMenu::indicator { width: 16px; height: 16px; left: 10px; }
QMenu::indicator:checked { image: url($${assets}/icons/check_${name}.png); }
QMenu::right-arrow { image: url($${assets}/icons/chevron_right_${name}.png); width: 12px; height: 12px; right: 10px; }
QMenu::separator { height: 1px; margin: 5px 10px; background: transparent; }
QMenu::section { color: ${text3}; font-size: 12px; padding: 8px 12px 4px 12px; }
QToolButton[role="modelChip"] { background: ${control}; border-radius: 12px; padding: 4px 26px 4px 12px; font-size: 12px; }
QToolButton[role="modelChip"]:hover, QToolButton[role="modelChip"][popupOpen="true"] { background: ${hover}; }
QToolButton[role="modelChip"]::menu-indicator { image: url($${assets}/icons/chevron_down_${name}.png); width: 10px; height: 10px; subcontrol-position: right center; right: 10px; }
