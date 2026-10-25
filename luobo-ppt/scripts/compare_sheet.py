#!/usr/bin/env python3
"""Before/after sheet: source slide on the left, beautified slide on the right.

Usage:
  python compare_sheet.py WORK_DIR [--out WORK_DIR/out/compare.png] [--slides 1,2,5] [--width 1800]
Needs WORK_DIR/source_png/slide-XX.png (extract_deck.py) and
WORK_DIR/out/png/slide-XX.png (render.py on the output).
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--out")
    ap.add_argument("--slides")
    ap.add_argument("--width", type=int, default=1800)
    a = ap.parse_args()
    work = Path(a.work)
    def pages(directory):
        return {int(p.stem.split("-")[-1]): p for p in directory.glob("slide-*.png")
                if p.stem.split("-")[-1].isdigit()}
    before = pages(work / "source_png")
    after = pages(work / "out" / "png")
    numbers = sorted(before.keys() & after.keys())
    if a.slides:
        keep = {int(x) for x in a.slides.split(",")}
        numbers = [n for n in numbers if n in keep]
    pairs = [(before[n], after[n]) for n in numbers]
    if not pairs:
        raise SystemExit("no rendered slides found; run extract_deck.py and render.py first")
    pad, lab = 16, 34
    cw = (a.width - 3 * pad) // 2
    ch = int(cw * 9 / 16)
    H = lab + len(pairs) * (ch + pad) + pad
    sheet = Image.new("RGB", (a.width, H), (236, 238, 237))
    d = ImageDraw.Draw(sheet)
    try:
        from common import get_font
        f = get_font(20, True)
    except Exception:
        f = None
    d.text((pad, 8), "BEFORE", fill=(90, 90, 90), font=f)
    d.text((2 * pad + cw, 8), "AFTER", fill=(20, 110, 90), font=f)
    for i, (b, af) in enumerate(pairs):
        y = lab + i * (ch + pad)
        for img_path, x in ((b, pad), (af, 2 * pad + cw)):
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((cw, ch))
            sheet.paste(im, (x + (cw - im.width) // 2, y + (ch - im.height) // 2))
    out = Path(a.out) if a.out else work / "out" / "compare.png"
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
