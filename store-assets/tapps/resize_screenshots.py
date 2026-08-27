#!/usr/bin/env python3
"""Resize raw app screenshots to the 900x1600 portrait spec for store listings.

Usage:
    1. Drop raw screenshots (any size) into store-assets/tapps/raw/
    2. Run:  python3 store-assets/tapps/resize_screenshots.py
    3. Find 900x1600 PNGs in store-assets/tapps/out/

Aspect ratio is preserved; the image is scaled to fit and centered on a
dark canvas (matches the app background) so nothing is cropped or distorted.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow not installed. Run: pip install Pillow")

TARGET_W, TARGET_H = 900, 1600
BG = (11, 11, 18)  # app background (#0b0b12)

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
OUT = HERE / "out"
EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def resize_one(path: Path) -> Path:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = min(TARGET_W / w, TARGET_H / h)
    new = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)

    canvas = Image.new("RGB", (TARGET_W, TARGET_H), BG)
    offset = ((TARGET_W - new.width) // 2, (TARGET_H - new.height) // 2)
    canvas.paste(new, offset)

    out_path = OUT / f"{path.stem}_900x1600.png"
    canvas.save(out_path, "PNG")
    return out_path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not RAW.is_dir():
        RAW.mkdir(parents=True, exist_ok=True)
        sys.exit(f"Put raw screenshots in {RAW} and re-run.")

    files = sorted(p for p in RAW.iterdir() if p.suffix.lower() in EXTS)
    if not files:
        sys.exit(f"No images found in {RAW}")

    for p in files:
        out = resize_one(p)
        print(f"  {p.name} -> {out.relative_to(HERE)}")
    print(f"Done. {len(files)} image(s) written to {OUT.relative_to(HERE)}/")


if __name__ == "__main__":
    main()
