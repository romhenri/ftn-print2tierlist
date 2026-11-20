"""Grid detection and card extraction for inventory screenshots."""

from dataclasses import dataclass

import numpy as np
from PIL import Image


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
    if n < 5:
        return [n / 2], n
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
    region. Sample from a three-pixel-wide border ring: it crosses gaps and only
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
    w = max(1, int(img_pil.width * scale))
    h = max(1, int(img_pil.height * scale))
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


@dataclass
class Card:
    row: int
    column: int
    bounds: tuple[int, int, int, int]
    image: Image.Image


def full_screen_grid(img):
    """Find the right-hand 8×5 grid and align it to the row gutters."""
    if img.width < 64 or abs(img.width / img.height - 16 / 9) >= .04:
        return None

    width = min(900, img.width)
    height = max(1, round(img.height * width / img.width))
    pixels = np.asarray(img.resize((width, height)), dtype=np.float32)
    cols, rows = 8, 5
    left, top = 809.5 / 1599, 244.5 / 899
    step_x, step_y = 85.15 / 1599, 115 / 899
    x_edges = left + np.arange(cols + 1) * step_x
    y_edges = top + np.arange(rows + 1) * step_y
    x_centers = x_edges[:-1] + step_x / 2

    def sample(x, y):
        return pixels[np.rint(y * height).astype(int), np.rint(x * width).astype(int)]

    def distance(a, b):
        return np.linalg.norm(a - b, axis=-1)

    radius = round(step_y * height / 4)
    gutter = round(8 * height / 899)
    offsets = np.arange(-radius, radius + 1)
    seam_rows = np.rint(y_edges[1:-1] * height).astype(int)
    scan_y = (seam_rows[None, :, None] + offsets[:, None, None] +
              np.arange(-gutter, gutter + 1)[None, None, :]) / height
    center = sample(x_centers, scan_y[..., None])
    left_gap = sample(x_edges[:-1], scan_y[..., None])
    right_gap = sample(x_edges[1:], scan_y[..., None])
    distances = np.minimum(distance(center, left_gap), distance(center, right_gap))
    scores = np.minimum(distances, 90).sum(axis=(1, 2, 3))
    best_offset = offsets[np.lexsort((np.abs(offsets), scores))[0]]
    y_edges += best_offset / height
    y_centers = y_edges[:-1] + step_y / 2

    def count_gutters(x, y, dx, dy):
        center = sample(x, y)
        before = distance(center, sample(x-dx, y-dy))
        after = distance(center, sample(x+dx, y+dy))
        return np.count_nonzero((before >= 45) & (after >= 45))

    if count_gutters(x_edges[1:-1], y_centers[:, None], 14 / 1599, 0) < 4:
        return None
    if count_gutters(x_centers, y_edges[1:-1, None], 0, 19 / 899) < 3:
        return None
    return x_edges * img.width, y_edges * img.height


def extract_cards(img, x_lines, y_lines, *, full_screen=False, padding=.08):
    """Yield full-resolution cards in row-major order, with source coordinates."""
    for row, (top, bottom) in enumerate(zip(y_lines, y_lines[1:]), 1):
        for column, (left, right) in enumerate(zip(x_lines, x_lines[1:]), 1):
            width, height = right - left, bottom - top
            inset_x = (width if full_screen else min(width, height)) * padding
            inset_y = height * padding if full_screen else inset_x
            bounds = tuple(round(value) for value in (
                left + inset_x, top + inset_y, right - inset_x, bottom - inset_y,
            ))
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                continue
            card = img.crop(bounds)
            # Full-screen tiles use the browser's subsampled color check.
            pixels = np.asarray(card).reshape(-1, 3)
            colors = (pixels[::4] if full_screen else pixels) // 32
            min_colors = 53 if full_screen else 60
            if len(np.unique(colors, axis=0)) >= min_colors:
                yield Card(row, column, bounds, card)


def contact_sheet(cards, count, *, columns=8, tile_width=90, tile_height=120):
    columns = max(1, min(columns, count))
    rows = (count + columns - 1) // columns
    gap = 6
    stride_x, stride_y = tile_width + gap, tile_height + gap
    sheet = Image.new('RGB', (columns * stride_x + gap, rows * stride_y + gap), (20, 24, 34))
    for index, card in enumerate(cards):
        row, col = divmod(index, columns)
        sheet.paste(card.resize((tile_width, tile_height)), (gap + col * stride_x, gap + row * stride_y))
    return sheet
