from importlib.resources import files


def load_qss(theme: str = "light") -> str:
    return (files(__package__) / f"app_{theme}.qss").read_text(encoding="utf-8")
