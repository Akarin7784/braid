# PyInstaller spec：pyinstaller packaging/braid.spec
import re
import subprocess
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
icon = str(Path(SPECPATH) / ("braid_light.icns" if sys.platform == "darwin" else "braid_light.ico"))

# 随包字体（Inter + OFL 许可证）经 collect_data_files 打进包；缺了直接报错，别打出没有字体的包
datas = collect_data_files("braid")
for _f in ("Inter-Regular.ttf", "Inter-SemiBold.ttf", "OFL.txt"):
    assert any(Path(src).name == _f and "fonts" in Path(dst).parts for src, dst in datas), f"缺少字体资源 {_f}"

# keyring 现在是懒加载（#56），静态分析看不到后端；后端靠 entry points 发现，元数据也要带上
hiddenimports = collect_submodules("keyring.backends") + [
    "jaraco.classes", "jaraco.functools", "jaraco.context",
]
if sys.platform.startswith("linux"):
    hiddenimports += collect_submodules("secretstorage") + collect_submodules("jeepney")
elif sys.platform == "win32":
    hiddenimports += collect_submodules("win32ctypes")
for _m in ("keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService",
           "keyring.backends.kwallet", "keyring.backends.chainer", "keyring.backends.fail",
           "keyring.backends.null"):
    assert _m in hiddenimports, f"缺少 keyring 后端 {_m}"
datas += copy_metadata("keyring")
assert any("keyring-" in Path(dst).name and Path(dst).name.endswith(".dist-info") for _src, dst in datas), "缺少 keyring 元数据"

# 内置浏览器：WebEngine 只在打开浏览器标签时才导入，显式列出
hiddenimports += ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
                  "braid.selfcheck"]

# ---- 瘦身：PySide6 的 QtQml/QtQuick 钩子会把整套 Qt（3D、Charts、Pdf、多媒体……）和 qml 目录都拖进来，
# 我们只用 Widgets + WebEngineWidgets。WebEngineCore 直接链接 Qml、Quick、Positioning、WebChannel，这几个必须留。
_UNUSED = re.compile(
    r"^(3D\w*|Charts\w*|DataVisualization\w*|Graphs\w*|Labs\w*|Location|Multimedia\w*|Pdf\w*|PositioningQuick"
    r"|Quick3D\w*|QuickControls2\w*|QuickDialogs2\w*|QuickEffects|QuickLayouts|QuickParticles|QuickShapes\w*"
    r"|QuickTest|QuickTimeline\w*|QuickVectorImage\w*|RemoteObjects\w*|Scxml\w*|Sensors\w*|SerialPort"
    r"|ShaderTools|SpatialAudio|Sql|StateMachine\w*|Test|TextToSpeech|VirtualKeyboard\w*|WaylandCompositor\w*"
    r"|WebChannelQuick|WebEngineQuick\w*|WebSockets|WebView\w*|QmlDesignSupport|QmlLocalStorage|QmlXmlListModel"
    r"|Help|Designer\w*|UiTools|Bluetooth|Nfc|SerialBus|HttpServer|NetworkAuth)$"
)
_KEEP = {"Core", "Gui", "Widgets", "Network", "DBus", "OpenGL", "OpenGLWidgets", "Qml", "QmlCore", "QmlMeta",
         "QmlModels", "QmlWorkerScript", "Quick", "QuickWidgets", "Positioning", "WebChannel", "WebEngineCore",
         "WebEngineWidgets", "PrintSupport", "XcbQpa", "WaylandClient", "WlShellIntegration",
         "EglFSDeviceIntegration", "EglFsKmsSupport", "Concurrent", "Svg"}
assert not any(_UNUSED.match(m) for m in _KEEP), "排除表误伤了 WebEngine 依赖"
_UNUSED_PY = ["3DAnimation", "3DCore", "3DExtras", "3DInput", "3DLogic", "3DRender", "Charts", "DataVisualization",
              "Graphs", "Location", "Multimedia", "MultimediaWidgets", "Pdf", "PdfWidgets", "Quick3D", "Sensors",
              "SerialPort", "Sql", "StateMachine", "Test", "TextToSpeech", "WebSockets", "WebView", "SpatialAudio",
              "RemoteObjects", "Scxml", "Bluetooth", "Nfc", "Help", "Designer", "UiTools"]
# qml 目录整个不要（界面全是 Widgets）；这些插件目录也用不上
_DROP_PLUGIN_DIRS = {"qmltooling", "multimedia", "sensors", "sqldrivers", "texttospeech", "renderers",
                     "sceneparsers", "geometryloaders", "renderplugins", "virtualkeyboard", "canbus",
                     "assetimporters", "designer", "help", "webview", "3dinputdevices", "position"}
_KEEP_LOCALES = {"en-US", "en-GB", "zh-CN", "zh-TW"}
_MOD = re.compile(r"(?:^lib)?Qt6?(\w+?)(?:\.so[.\d]*|\.dll|\.dylib|\.framework)$")


def _qt_module(part):
    m = _MOD.match(part)
    return m.group(1) if m else None


def _drop(dest):
    parts = Path(dest).parts
    # Linux/mac 在 PySide6/Qt/qml，Windows 轮子直接是 PySide6/qml
    if any(a in ("Qt", "PySide6") and b == "qml" for a, b in zip(parts, parts[1:])):
        return True
    if "plugins" in parts and parts.index("plugins") + 1 < len(parts) and parts[parts.index("plugins") + 1] in _DROP_PLUGIN_DIRS:
        return True
    if "translations" in parts:
        # Chromium 缺语言包时回落 en-US；只留中英文，其余 70 多种语言约 45MB
        name = parts[-1]
        stem = name.rsplit(".", 1)[0]
        if parts[-2] == "qtwebengine_locales":
            return stem not in _KEEP_LOCALES
        if name.endswith(".qm"):
            return not stem.endswith(("_zh_CN", "_zh_TW", "_en"))
    return any((mod := _qt_module(p)) and _UNUSED.match(mod) for p in parts)


def _slim(toc):
    kept = [e for e in toc if not _drop(e[0])]
    print(f"[slim] dropped {len(toc) - len(kept)} / {len(toc)} entries")
    return kept


def _check_needed(binaries):
    """Linux：依赖了被排除模块的插件一并去掉；其余 ELF 依赖的 libQt6* 必须都在包里，否则打包失败。"""
    if not sys.platform.startswith("linux"):
        return binaries
    have = {Path(d).name for d, _s, _t in binaries}
    miss, bad_plugins = set(), set()
    for d, src, _t in binaries:
        try:
            out = subprocess.run(["readelf", "-d", src], capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            continue
        for lib in re.findall(r"\[(libQt6[^\]]+)\]", out):
            if lib not in have:
                (bad_plugins.add(d) if "plugins" in Path(d).parts else miss.add(f"{d} -> {lib}"))
    for d in sorted(bad_plugins):
        print(f"[slim] dropped plugin {d} (depends on excluded module)")
    assert not miss, "瘦身后缺少 Qt 依赖:\n" + "\n".join(sorted(miss))
    return [e for e in binaries if e[0] not in bad_plugins]


a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter"] + [f"PySide6.Qt{m}" for m in _UNUSED_PY],
)
a.binaries, a.datas = _slim(a.binaries), _slim(a.datas)
a.binaries = _check_needed(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="braid",
          console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="braid")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Braid.app", icon=icon, bundle_identifier="dev.braid.app")
