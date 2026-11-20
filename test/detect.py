#!/usr/bin/env python3
"""Grid detection for inventory screenshots.
Writes:
  test/out/overlay.png : original with bbox + grid lines
  test/out/sheet.png   : contact sheet of sliced cards
  test/out/proj_x.png, proj_y.png : 1D projections with detected tile centers
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

IN  = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "sample.jpeg"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)


def smooth(proj, k):
    return np.convolve(proj, np.ones(2*k+1)/(2*k+1), mode='same')


def find_grid_axis(proj_raw):
    """Return (centers, period) for one axis.

    Strategy: the tile-bg mask projection is a near-binary signal (high over
    tile rows/columns, low over gaps). Threshold at 50% of max, group into
    contiguous runs, call the center of each run a tile center. The gap
    between two consecutive runs is where the grid line between tiles sits.
    """
    n = len(proj_raw)
    proj = smooth(proj_raw, max(2, round(n * 0.004)))

    lo, hi = float(proj.min()), float(proj.max())
    thr = lo + (hi - lo) * 0.5

    runs = []
    start = None
    for i, v in enumerate(proj):
        if v >= thr:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, n - 1))

    if len(runs) < 2:
        return [n // 2], max(10, n // 2)

    # Drop runs that are far too short to be a tile (noise/UI chrome)
    widths = [b - a + 1 for a, b in runs]
    typical = float(np.median(widths))
    runs = [(a, b) for a, b in runs if (b - a + 1) >= typical * 0.4]

    centers = [(a + b) / 2 for a, b in runs]
    # period = median spacing between consecutive centers
    if len(centers) >= 2:
        spans = np.diff(centers)
        period = float(np.median(spans))
    else:
        period = float(typical)
    return centers, period


def axis_to_lines(centers, period, n):
    """Convert tile centers to grid-line positions. Lines are:
    outer-left, mid(1,2), mid(2,3), ..., mid(n-1,n), outer-right."""
    if len(centers) < 1:
        return [0, n - 1]
    lines = [centers[0] - period / 2]
    for a, b in zip(centers, centers[1:]):
        lines.append((a + b) / 2)
    lines.append(centers[-1] + period / 2)
    lines[0] = max(0, lines[0])
    lines[-1] = min(n - 1, lines[-1])
    return lines


def gap_mask(rgb):
    """Detect page background (gap colour) pixels.

    The gap colour is the single most common colour in the image's border
    region. Sample from a 1-pixel-wide border ring: it crosses gaps and only
    rarely clips a tile corner."""
    h, w = rgb.shape[:2]
    # Thin border ring: top, bottom, left, right strips.
    strips = np.concatenate([
        rgb[0:3, :, :].reshape(-1, 3),
        rgb[-3:, :, :].reshape(-1, 3),
        rgb[:, 0:3, :].reshape(-1, 3),
        rgb[:, -3:, :].reshape(-1, 3),
    ])
    # Mode via rounded colour buckets (step 8 per channel).
    quant = (strips // 8) * 8
    unique, counts = np.unique(quant, axis=0, return_counts=True)
    gap = unique[np.argmax(counts)].astype(np.float32)
    dr = rgb[..., 0] - gap[0]
    dg = rgb[..., 1] - gap[1]
    db = rgb[..., 2] - gap[2]
    dist = np.sqrt(dr * dr + dg * dg + db * db)
    return dist < 70


def detect(img_pil):
    max_w = 900
    scale = min(1.0, max_w / img_pil.width)
    w, h = int(img_pil.width * scale), int(img_pil.height * scale)
    small = img_pil.resize((w, h))
    arr = np.asarray(small.convert('RGB'), dtype=np.float32)

    # Mask is 1 where the pixel matches the page background (the gap colour).
    # Invert so the signal is high over tiles and low in gaps, which plays
    # nicely with the threshold-and-runs detector below.
    mask = (~gap_mask(arr)).astype(np.float32)
    px = mask.mean(axis=0)
    py = mask.mean(axis=1)

    cx, period_x = find_grid_axis(px)
    cy, period_y = find_grid_axis(py)

    lines_x = np.array(axis_to_lines(cx, period_x, w)) / scale
    lines_y = np.array(axis_to_lines(cy, period_y, h)) / scale
    bbox = (float(lines_x[0]), float(lines_y[0]), float(lines_x[-1]), float(lines_y[-1]))
    return bbox, lines_x, lines_y, (px, py, [c/scale for c in cx], [c/scale for c in cy])


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


def is_ui_icon(tile_img):
    """True when the tile is a flat UI icon (hanger+, shuffle) rather than a
    skin portrait. Flat icons have very few distinct colours."""
    q = (np.asarray(tile_img) // 32) * 32
    unique = len(np.unique(q.reshape(-1, 3), axis=0))
    return unique < 60


def make_sheet(img, lx, ly, save_path, pad_frac=0.08, tile_w=90, tile_h=120):
    cols, rows = len(lx) - 1, len(ly) - 1
    kept = []
    for r in range(rows):
        for c in range(cols):
            x0, x1 = lx[c], lx[c + 1]
            y0, y1 = ly[r], ly[r + 1]
            cw, ch = x1 - x0, y1 - y0
            p = min(cw, ch) * pad_frac
            crop = img.crop((x0 + p, y0 + p, x1 - p, y1 - p))
            if is_ui_icon(crop):
                continue
            kept.append(crop.resize((tile_w, tile_h)))
    n = len(kept)
    cols_s = min(cols, max(1, n))
    rows_s = (n + cols_s - 1) // cols_s
    sheet_w = cols_s * (tile_w + 6) + 6
    sheet_h = rows_s * (tile_h + 6) + 6
    sheet = Image.new('RGB', (sheet_w, sheet_h), (20, 24, 34))
    for i, crop in enumerate(kept):
        rr, cc = i // cols_s, i % cols_s
        sheet.paste(crop, (6 + cc * (tile_w + 6), 6 + rr * (tile_h + 6)))
    sheet.save(save_path)


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
    img = Image.open(IN).convert('RGB')
    bbox, lx, ly, (px, py, cx, cy) = detect(img)
    print(f'image {img.size}  →  cols={len(lx)-1} rows={len(ly)-1}')
    print(f'  bbox=({bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f})')
    print(f'  linesX: {[round(float(v),1) for v in lx]}')
    print(f'  linesY: {[round(float(v),1) for v in ly]}')
    draw_overlay(img, bbox, lx, ly, OUT / 'overlay.png')
    make_sheet(img, lx, ly, OUT / 'sheet.png')
    plot_projection(px, cx, OUT / 'proj_x.png')
    plot_projection(py, cy, OUT / 'proj_y.png')
    print(f'wrote outputs to {OUT}')
