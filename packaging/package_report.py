"""打包产物的体积报告、重复文件检查与发版归档。

用法（CI 的 package 任务里调用）::

    python packaging/package_report.py archive <OS>         # 生成 release 归档，打印路径
    python packaging/package_report.py report <OS> <归档>   # 写 size-<OS>.txt，体积并入自检

Linux 用 tar.gz、mac 用 .dmg（hdiutil UDZO），都保留 PyInstaller 的符号链接；Windows 用 zip。
不要直接把 dist/ 交给 actions/upload-artifact：它打 zip 时会把符号链接展开，
Linux 包因此多出约 400MB。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path

DIST = Path("dist")
# 超过这个解压体积只告警，不拦（WebEngineCore 本身就有 ~200MB）
WARN_UNPACKED_MB = {"Linux": 520, "macOS": 600, "Windows": 520}
MB = 1024 * 1024


def app_root(os_name: str) -> Path:
    return DIST / ("Braid.app" if os_name == "macOS" else "braid")


def archive(os_name: str) -> Path:
    root = app_root(os_name)
    out = Path(f"braid-{os_name}")
    if os_name == "Linux":
        dst = out.with_suffix(".tar.gz")
        with tarfile.open(dst, "w:gz") as tf:  # tarfile 默认保存符号链接本身，不展开
            tf.add(root, arcname="braid")
    elif os_name == "macOS":
        dst = out.with_suffix(".dmg")
        dst.unlink(missing_ok=True)
        stage = Path("dmg-stage")
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        subprocess.run(
            ["ditto", str(root), str(stage / "Braid.app")], check=True, stdout=sys.stderr
        )
        os.symlink("/Applications", stage / "Applications")
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "Braid",
                "-srcfolder",
                str(stage),
                "-ov",
                "-format",
                "UDZO",
                str(dst),
            ],
            check=True,
            stdout=sys.stderr,  # 只让产物路径进 stdout
        )
        shutil.rmtree(stage)
    else:
        dst = out.with_suffix(".zip")
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    zf.write(p, Path("braid") / p.relative_to(root))
    return dst


def walk(root: Path) -> tuple[int, int, dict[str, int], list[tuple[str, int, list[str]]]]:
    """返回 (实际占用字节, 符号链接数, 顶层目录体积, 同名同大小的重复文件)。符号链接不计体积。"""
    total, links = 0, 0
    per_dir: dict[str, int] = defaultdict(int)
    seen: dict[tuple[str, int], list[str]] = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            rel = p.relative_to(root)
            if p.is_symlink():
                links += 1
                continue
            size = p.stat().st_size
            total += size
            deep = rel.parts[0] in ("_internal", "Contents")
            top = "/".join(rel.parts[:3]) if deep else rel.parts[0]
            per_dir[top] += size
            if size >= 1 * MB:
                seen[(name, size)].append(str(rel))
    dups = [(n, s, ps) for (n, s), ps in seen.items() if len(ps) > 1]
    return total, links, dict(per_dir), sorted(dups, key=lambda d: -d[1] * (len(d[2]) - 1))


def report(os_name: str, packed: Path) -> int:
    total, links, per_dir, dups = walk(app_root(os_name))
    dup_bytes = sum(s * (len(ps) - 1) for _n, s, ps in dups)
    lines = [
        f"os: {os_name}",
        f"archive: {packed.name} {packed.stat().st_size / MB:.1f} MB",
        f"unpacked: {total / MB:.1f} MB（符号链接 {links} 个，不计体积）",
        f"duplicates(>=1MB 同名同大小): {len(dups)} 组，多占 {dup_bytes / MB:.1f} MB",
        "",
        "按目录：",
    ]
    biggest = sorted(per_dir.items(), key=lambda kv: -kv[1])[:40]
    lines += [f"{v / MB:9.1f} MB  {k}" for k, v in biggest]
    if dups:
        lines += ["", "重复文件："]
        lines += [f"{s / MB:9.1f} MB x{len(ps)}  {n}: {', '.join(ps)}" for n, s, ps in dups[:30]]
    Path(f"size-{os_name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    sc = Path(f"selfcheck-{os_name}.txt")
    if sc.exists():
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
        except ValueError:
            data = None
        if isinstance(data, dict):
            data["package"] = {
                "archive": packed.name,
                "packed_bytes": packed.stat().st_size,
                "unpacked_bytes": total,
                "symlinks": links,
                "duplicate_bytes": dup_bytes,
            }
            sc.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    limit = WARN_UNPACKED_MB.get(os_name)
    if limit and total / MB > limit:
        print(f"::warning::{os_name} 包解压后 {total / MB:.0f}MB，超过 {limit}MB 告警线")
    if dup_bytes > 20 * MB:
        print(f"::warning::{os_name} 包里有 {dup_bytes / MB:.0f}MB 重复文件，见 size-{os_name}.txt")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "archive":
        print(archive(argv[1]))
        return 0
    if len(argv) >= 3 and argv[0] == "report":
        return report(argv[1], Path(argv[2]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
