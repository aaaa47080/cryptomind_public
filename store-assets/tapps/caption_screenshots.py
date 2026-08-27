#!/usr/bin/env python3
"""Add marketing taglines to the 900x1600 store screenshots (ad-style).

Each output keeps the 900x1600 spec: a dark brand band at the top carries the
tagline, the original screenshot is scaled to fit below it (nothing cropped).

Usage:
    pip install Pillow
    python3 store-assets/tapps/caption_screenshots.py

Inputs:  store-assets/tapps/screenshots/<n>_*.png  (900x1600)
Outputs: store-assets/tapps/captioned/<n>_*.png    (900x1600, with tagline)
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow not installed. Run: pip install Pillow")

TARGET_W, TARGET_H = 900, 1600
BG = (11, 11, 18)        # app background #0b0b12
ACCENT = (0, 152, 234)   # TON blue #0098EA
TEXT = (255, 255, 255)

BAND_H = 250             # top band height for the tagline
SIDE_PAD = 56
MAX_FONT = 60
MIN_FONT = 34

HERE = Path(__file__).resolve().parent
SRC = HERE / "screenshots"
OUT = HERE / "captioned"

# filename stem -> marketing tagline (from LISTING.md)
TAGLINES = {
    "1_chat": "Ask AI anything about the markets",
    "2_crypto_market": "Live crypto screener — top movers at a glance",
    "3_chart": "Pro real-time charts, right in Telegram",
    "4_twstock": "Track TW stocks — TSMC, Hon Hai & more",
    "5_usstock": "US stocks too — Apple, Microsoft, Alphabet",
    "6_settings": "TON Connect login + premium",
}

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, max_w, max_lines=2):
    """Pick the largest font size where text fits in max_lines."""
    for size in range(MAX_FONT, MIN_FONT - 1, -2):
        font = _load_font(size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
    font = _load_font(MIN_FONT)
    return font, _wrap(draw, text, font, max_w)


def caption_one(path: Path) -> Path:
    shot = Image.open(path).convert("RGB")

    canvas = Image.new("RGB", (TARGET_W, TARGET_H), BG)
    draw = ImageDraw.Draw(canvas)

    # --- tagline in the top band ---
    max_w = TARGET_W - 2 * SIDE_PAD
    font, lines = _fit(draw, TAGLINES.get(path.stem, ""), max_w)
    line_h = (font.getbbox("Ag")[3] - font.getbbox("Ag")[1]) + 14
    block_h = line_h * len(lines)
    y = (BAND_H - block_h) // 2
    for ln in lines:
        w = draw.textlength(ln, font=font)
        draw.text(((TARGET_W - w) / 2, y), ln, font=font, fill=TEXT)
        y += line_h
    # accent underline
    uw = 90
    draw.rectangle(
        [(TARGET_W - uw) // 2, BAND_H - 26, (TARGET_W + uw) // 2, BAND_H - 20],
        fill=ACCENT,
    )

    # --- screenshot scaled to fit below the band ---
    avail_h = TARGET_H - BAND_H - 24
    avail_w = TARGET_W - 24
    scale = min(avail_w / shot.width, avail_h / shot.height)
    new = shot.resize(
        (round(shot.width * scale), round(shot.height * scale)), Image.LANCZOS
    )
    ox = (TARGET_W - new.width) // 2
    oy = BAND_H + (avail_h - new.height) // 2
    canvas.paste(new, (ox, oy))

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / path.name
    canvas.save(out_path, "PNG")
    return out_path


def main() -> None:
    if not SRC.is_dir():
        sys.exit(f"No screenshots dir: {SRC}")
    files = sorted(p for p in SRC.iterdir() if p.suffix.lower() == ".png")
    if not files:
        sys.exit(f"No screenshots in {SRC}")
    for p in files:
        out = caption_one(p)
        print(f"  {p.name} -> {out.relative_to(HERE)}")
    print(f"Done. {len(files)} captioned image(s) in {OUT.relative_to(HERE)}/")


if __name__ == "__main__":
    main()
