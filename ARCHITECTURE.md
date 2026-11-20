# Architecture

Script framing: each box is a single file. Two parallel pipelines share the same gap-colour grid detection algorithm, one in the browser app and one in the Python harness used to iterate on it.

```
┌───────────────┐    ┌──────────────────┐
│   print JPG   │    │ test/sample.jpeg │
│ (user upload) │    │                  │
└───────────────┘    └──────────────────┘
        │                      │
        └┐                   ┌─┘
         ▼ file input        ▼ argv
  ┌────────────┐    ┌────────────────┐
  │ index.html │    │ test/detect.py │
  └────────────┘    └────────────────┘
         │                   │
         │                   └┐
         ▼ sets/exports       ▼ overlay/sheet
 ┌──────────────┐    ┌────────────────┐
 │   browser    │    │ test/out/*.png │
 │ localStorage │    │                │
 └──────────────┘    └────────────────┘
```

## The boxes

**index.html** — the whole app. Hash router with four views (`/sets`, `/upload`, `/set/:id`, `/exports`), upload+auto-slice flow, tierlist drag/drop editor and PNG exporter. The grid detector lives in `detectGrid` + `findGridLines` (gap-colour mask, projection threshold, run centres); UI-icon filter in `isUiIcon`.

**test/detect.py** — Python port of the same algorithm, run against `sample.jpeg`. Writes an overlay of the detected grid, a contact sheet of sliced cards, and the raw X/Y projections. Used to iterate the detector visually before porting changes back to `index.html`.

**browser localStorage** — client-only persistence. Two keys: `sets` (cards + per-set tier list + layout + cover index) and `exports` (generated tierlist PNGs).

**test/out/\*.png** — ignored by git. Regenerated every run of the harness.

The two spines never cross: no code is imported between them. The algorithm is intentionally duplicated so the Python side can move faster without a build step.
