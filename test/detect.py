#!/usr/bin/env python3
"""Grid detection for inventory screenshots.
Writes:
  test/out/overlay.png : original with bbox + grid lines
  test/out/sheet.png   : contact sheet of sliced cards
  test/out/proj_x.png, proj_y.png : 1D projections with detected tile centers
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli'))
from inventory_grid import contact_sheet, detect, extract_cards


def draw_overlay(img, bbox, lx, ly, save_path):
    canvas = img.copy()
    dr = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = bbox
    dr.rectangle([x0, y0, x1, y1], outline=(91, 141, 255), width=4)
    for x in lx:
        dr.line([(x, y0), (x, y1)], fill=(80, 220, 120), width=2)
    for y in ly:
        dr.line([(x0, y), (x1, y)], fill=(80, 220, 120), width=2)
    canvas.save(save_path)


def plot_projection(proj, centers, save_path):
    n = len(proj); H = 120
    img = Image.new('RGB', (n, H), 'black')
    dr = ImageDraw.Draw(img)
    lo, hi = float(proj.min()), float(proj.max()); rng = hi - lo or 1
    for i in range(1, n):
        y0 = H - int((proj[i-1] - lo) / rng * (H - 4))
        y1 = H - int((proj[i]   - lo) / rng * (H - 4))
        dr.line([(i - 1, y0), (i, y1)], fill=(200, 200, 200))
    for x in centers:
        dr.line([(int(x), 0), (int(x), H)], fill=(255, 140, 0))
    img.save(save_path)


if __name__ == '__main__':
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('sample.jpeg')
    out = Path(__file__).with_name('out')
    out.mkdir(exist_ok=True)
    with Image.open(source) as screenshot:
        img = screenshot.convert('RGB')
    bbox, lx, ly, (px, py, cx, cy) = detect(img)
    print(f'image {img.size}  →  cols={len(lx)-1} rows={len(ly)-1}')
    print(f'  bbox=({bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f})')
    print(f'  linesX: {[round(float(v),1) for v in lx]}')
    print(f'  linesY: {[round(float(v),1) for v in ly]}')
    draw_overlay(img, bbox, lx, ly, out / 'overlay.png')
    cards = list(extract_cards(img, lx, ly))
    contact_sheet((card.image for card in cards), len(cards), columns=len(lx)-1).save(out / 'sheet.png')
    plot_projection(px, cx, out / 'proj_x.png')
    plot_projection(py, cy, out / 'proj_y.png')
    print(f'wrote outputs to {out}')
