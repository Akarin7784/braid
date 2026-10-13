"""Build file-type icons: SVG sources (light colors) -> PNG 40px light/dark.

Sources use the light-theme tokens text2 (#6B6B69) and brand (#C96442);
the dark variant swaps them for the dark-theme values from tokens.json.
Usage: python design/icons/file/build_file_icons.py  (needs cairosvg)
"""

import json
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "design/icons/file"
OUT = ROOT / "src/braid/assets/icons"
TOK = json.loads((ROOT / "src/braid/theme/tokens.json").read_text())
TYPES = ["code", "markdown", "image", "html", "sheet", "archive", "other"]

for t in TYPES:
    svg = (SRC / f"{t}.svg").read_text()
    for theme in ("light", "dark"):
        s = svg.replace("#6B6B69", TOK[theme]["text2"]).replace("#C96442", TOK[theme]["brand"])
        cairosvg.svg2png(
            bytestring=s.encode(),
            write_to=str(OUT / f"file_{t}_{theme}.png"),
            output_width=40,
            output_height=40,
        )
    print("built", t)
