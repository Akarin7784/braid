# PyInstaller spec：pyinstaller packaging/braid.spec
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

a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(root / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="braid",
          console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="braid")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Braid.app", icon=icon, bundle_identifier="dev.braid.app")
