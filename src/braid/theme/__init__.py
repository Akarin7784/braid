from importlib.resources import files


def load_qss(theme: str = "light") -> str:
    """读取主题 QSS，并把 ${assets} 替换成图标资源目录的绝对路径。"""
    qss = (files(__package__) / f"app_{theme}.qss").read_text(encoding="utf-8")
    assets = str(files("braid.assets")).replace("\\", "/")
    return qss.replace("${assets}", assets)
