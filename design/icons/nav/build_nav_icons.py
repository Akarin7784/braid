"""Build browser nav icons: SVG sources (light text2) -> PNG 40px light/dark.

Sources use the light-theme token text2 (#6B6B69); the dark variant swaps it
for the dark-theme value from tokens.json. Also writes a review sheet.
Usage: python design/icons/nav/build_nav_icons.py  (needs cairosvg)
"""

import json
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "design/icons/nav"
OUT = ROOT / "src/braid/assets/icons"
REVIEW = ROOT / "design/review/nav_icons.png"
TOK = json.loads((ROOT / "src/braid/theme/tokens.json").read_text())
NAMES = ["back", "forward", "reload", "stop", "external"]

cells = []
for i, name in enumerate(NAMES):
    svg = (SRC / f"{name}.svg").read_text()
    for theme in ("light", "dark"):
        s = svg.replace("#6B6B69", TOK[theme]["text2"])
        cairosvg.svg2png(
            bytestring=s.encode(),
            write_to=str(OUT / f"nav_{name}_{theme}.png"),
            output_width=40,
            output_height=40,
        )
        inner = s.split(">", 1)[1].rsplit("</svg>", 1)[0]
        y = 0 if theme == "light" else 40
        head = s.split(">", 1)[0].split("viewBox")[1]
        attrs = head.split('"', 2)[2]
        cells.append(f'<g transform="translate({10 + i * 40} {y + 10})" {attrs}>{inner}</g>')
    print("built", name)

bg = (
    f'<rect width="210" height="40" fill="{TOK["light"]["surface"]}"/>'
    f'<rect y="40" width="210" height="40" fill="{TOK["dark"]["surface"]}"/>'
)
sheet = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 80">{bg}{"".join(cells)}</svg>'
cairosvg.svg2png(bytestring=sheet.encode(), write_to=str(REVIEW), output_width=840)
