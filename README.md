# PaintMint

A layered image editor for **Linux Mint** (and any Debian/Ubuntu-based distro), inspired by Paint.NET.
It runs natively (no Windows, no Wine). The interface is in **English by default**; **Spanish** is selectable
from *Help ▸ Language*.

**Stack: Python 3 + PyQt5 (UI) + NumPy/SciPy/Pillow (pixels).** Everything ships in the Mint/Ubuntu repositories (`apt`), nothing has to be compiled, and the NumPy pixel core can be tested without a display.

---

## ☕ Donation

<a href="https://www.paypal.com/donate/?hosted_button_id=Q9VZZG5U83NC8"><img src="https://i.imgur.com/6pMw6P6.png" alt="Donate with PayPal" width="200"></a>

Donation: If this project help you, you can give me a tip :) 

[**Donate via PayPal**](https://www.paypal.com/donate/?hosted_button_id=Q9VZZG5U83NC8)

---

## Install

```bash
git clone https://github.com/juantopoarg/PaintMint.git && cd PaintMint
./scripts/install_deps.sh            # installs PyQt5, NumPy, Pillow, SciPy and pytest with apt
# alternative with a virtual environment (uses the system PyQt5):
./scripts/install_deps.sh --venv
```

Tested with Python 3.13; the syntax is checked to be compatible with Python ≥ 3.8, so it should work on Mint 21 (Python 3.10) and Mint 22 (Python 3.12). Minimum dependencies: PyQt5 ≥ 5.15, NumPy ≥ 1.21, Pillow ≥ 9, SciPy ≥ 1.8 (`requirements.txt`).

## Run

```bash
./paintmint.sh                       # or: python3 -m paintmint
./paintmint.sh photo.png other.jpg   # open files directly
./scripts/install_desktop_entry.sh   # (optional) adds PaintMint to the applications menu with its icon
```

You can also drag files onto the window. Each image opens in its own tab.

## Language

English is the default. Choose *Help ▸ Language ▸ Español* (or *English*) and restart the application.
The choice is stored in `~/.config/paintmint/config.json`; you can override it for one run with
`PAINTMINT_LANG=es ./paintmint.sh`. Adding another language means adding one dictionary
(`paintmint/translations_xx.py`) keyed by the English text.

## Automatic updates

PaintMint checks this repository (at most once a day, in the background, at startup) and, when a newer
`paintmint/__init__.py` version exists on `main`, **asks you** whether to install it. Nothing is ever replaced
without confirmation, and a failed check (offline, GitHub down) is silent.

- *Help ▸ Check for updates…* checks on demand; *Help ▸ Check for updates at startup* turns the automatic check off.
- If the folder is a `git clone`, the update is `git pull --ff-only`. Otherwise the repository ZIP is downloaded,
  validated (rejects corrupt archives, paths outside the destination and anything that is not PaintMint), and copied over
  the installation. The previous package is kept in `.paintmint-backup/` and restored automatically if the copy fails.
- Restart PaintMint after an update to use the new version.

## Colors window

A replica of Paint.NET's *Colors* window: a **Primary / Secondary** selector, a **<< Less / More >>** toggle, the
primary/secondary swatches with swap and reset, a **color wheel**, **R, G, B** sliders, a **Hex** field, **H, S, V**
sliders, a **Transparency - Alpha** slider (each with a numeric box) and a large palette (grays, hues, tints/shades and
semi-transparent rows). Left-click a palette cell to set the selected color, right-click to set the other one; **＋** adds the
current color to your own palette row (saved between sessions).
Sliders (with numeric boxes) are also used for **size, hardness, opacity and the magic wand tolerance**.

## Tests

```bash
./scripts/run_tests.sh               # same as: QT_QPA_PLATFORM=offscreen python3 -m pytest
./scripts/run_tests.sh -k history -v # subsets
```

No display needed (Qt in `offscreen` mode) and no network (the updater tests use a fake downloader). Currently
**234 tests pass**; 3 file-permission tests are skipped when running as `root` (root ignores permissions) and pass as a normal user.

| File | Covers |
|---|---|
| `test_document_layers.py` | create/select/reorder/delete/duplicate layers, visibility, opacity, merge, flatten, canvas, rotate, crop |
| `test_blend.py` | the 14 blend modes, alpha algebra, strip compositing |
| `test_selection.py` | rectangle, ellipse, lasso, wand, combining (add/subtract/intersect/XOR), undo |
| `test_history.py` | exact undo/redo, unlimited, step merging, memory trimming, timeline jumps, "modified" state |
| `test_tools.py` | brush, pencil, eraser, fill, gradient, shapes, color picker, selection, move, editable text |
| `test_effects.py` | brightness/contrast, levels, curves, hue/saturation, blur, sharpen, pixelate, noise, selection clipping |
| `test_io.py` | PNG, JPG, BMP, GIF, TIFF and ORA round trips; EXIF, 16 bit, color modes, animated GIF |
| `test_errors.py` | corrupt/truncated/empty/unsupported files, no permissions, disk full, missing folder, out of memory |
| `test_i18n_updater.py` | complete Spanish catalog, English default, language switching; updater (version check, git/ZIP install, zip-slip rejection, rollback) |
| `test_text_raster.py`, `test_ui_smoke.py` | text, raster primitives, the full window with simulated mouse, Colors window, sliders, About, Language menu |

## Architecture

```
paintmint/
├── core/           Document model (no Qt)
│   ├── document.py   Document: canvas, layer stack, selection, events
│   ├── layer.py      Layer (RGBA uint8, straight alpha) and TextSpec (editable text)
│   ├── blend.py      Blend modes and strip compositing
│   ├── selection.py  Selection mask and boolean operations
│   ├── history.py    Command-based history (undo/redo, unlimited)
│   ├── commands.py   Concrete commands (pixel patches, layers, selection...)
│   ├── session.py    EditSession: the single write gateway + EditHandle (transient edits)
│   ├── io.py         Open/save PNG, JPG, BMP, GIF, TIFF, ORA with translated errors
│   ├── memory.py     Size limits and available-RAM check
│   └── errors.py     Exception hierarchy with user-facing messages
├── render/         Rasterizing (no Qt): strokes, shapes, gradients, fill, text
├── tools/          Tools: receive events in image coordinates
├── effects/        Adjustments and effects with declarative parameters (the dialog builds itself)
├── ui/             PyQt5: zoomable canvas, panels, dialogs, Colors window widgets, About, main window
├── config.py       User settings (~/.config/paintmint/config.json)
├── i18n.py         tr() + language selection; translations_es.py is the Spanish catalog
└── updater.py      GitHub update check/installer (standard library only)
```

Design decisions:

- **A single write gateway.** Tools and UI modify the document only through `EditSession`, so *everything* lands in the history.
- **Unlimited, cheap history.** A stroke stores only the rectangle that actually changed (before/after, zlib-compressed). `EditSession(doc, history_max_bytes=N)` can bound it.
- **`EditHandle`** gives live preview (effects, shapes, gradients) without touching the history until `commit`; `cancel` restores the layer exactly.
- **The selection clips every write** (with premultiplied interpolation on soft edges).
- **Brush opacity does not accumulate within one stroke**, like Paint.NET.
- **Editable text:** a text layer keeps its `TextSpec` until you paint on it or rasterize it; it is saved in `.ora`.

> Code comments and docstrings are written in Spanish; every user-visible message is English (with a Spanish catalog).

## Error handling

Every error path produces a `PaintMintError` with a user-facing message; the UI shows it in a dialog
(or in the status bar for tool notices) and the application keeps running:

- **Corrupt or unsupported files:** `ImageLoadError` / `UnsupportedFormatError` (the *content* is validated, not just the extension).
- **No permission or disk full when saving:** `ImageSaveError`. The file is written to a temporary and renamed, so a failure **never destroys** an existing file.
- **Large images / out of memory:** limits of 100 MP and 32,768 px per side (`core/memory.py`) checked *before* decoding, plus a `MemAvailable` check before allocating (on Linux, overcommit makes the OOM-killer kill the process instead of raising `MemoryError`). A residual `MemoryError` is also translated to `OutOfMemoryAppError`.
- **Unexpected errors:** every menu action/slot is guarded and a `sys.excepthook` logs to `~/.cache/paintmint/error.log` and warns without closing.
- **Updates:** network failures, corrupt/unsafe archives and permission problems are reported without touching the current installation.

## Paint.NET features: implemented and pending

**Implemented**

| Area | Features |
|---|---|
| Layers | new, **new layer via copy (Ctrl+J) / via cut (Ctrl+Shift+J)**, duplicate, delete, move up/down, merge down, flatten, visibility, opacity, 14 blend modes, rename, flip layer, rasterize text, compositing on save |
| Selection | rectangle, ellipse, lasso, magic wand (**tolerance slider**, contiguous/global, sample image), add/subtract/intersect/XOR, invert, all/none, move selected pixels, **move selection only**, crop to selection; **Esc clears the selection** (same as Ctrl+D; if a gesture is in progress, Esc cancels it first) |
| Drawing | brush (size, hardness, opacity, antialiasing), pencil, eraser, paint bucket, gradients (linear, reflected, diamond, radial, conical), shapes as separate tools (line, rectangle, rounded rectangle, ellipse; outline/fill/both; Shift = proportional), color picker |
| Text | editable text layers: font, size, bold, italic, alignment, color, drag to move |
| Adjustments | brightness/contrast, levels, curves (interactive editor), hue/saturation, invert, black and white, sepia, posterize — all with preview |
| Effects | Gaussian blur, sharpen, pixelate, noise — with preview |
| Image | resize (4 methods), canvas size with anchor, flip, rotate 90/180/270, crop |
| Editing | unlimited undo/redo + navigable history panel, copy/cut/paste (also "paste into new image"), delete/fill selection |
| Colors | **Paint.NET-style Colors window** (wheel, RGB/HSV/Hex/Alpha, large palette with custom colors) |
| Interface | **single-column** icon-only toolbox (Paint.NET order), **per-tool mouse cursor**, app icon: paint brush with a mint leaf, **English/Spanish**, About dialog with repo link and donation |
| View | zoom 2 %–6400 % (Ctrl+wheel, shortcuts), fit to window, pan with Space/middle button/Pan tool, transparency checkerboard, marching-ants selection |
| Files | PNG, JPG (quality), BMP, GIF (1-bit transparency), TIFF (LZW), **ORA** (OpenRaster: keeps layers, text and modes), tabs, recent files, drag and drop |
| Updates | check GitHub for new versions, confirmed install (git pull or validated ZIP) |

**Pending / out of scope (with reason)**

| Paint.NET feature | Status | Reason |
|---|---|---|
| Native `.pdn` format | No | Closed proprietary .NET format; `.ora` (open standard) is offered to keep layers |
| Effect plugins (.NET FX) | No | They depend on the .NET/Windows runtime; PaintMint effects are added as Python classes (`effects/`) |
| Editable shapes with nodes/Bézier curves and polylines | No | A shape is committed on mouse release; this would need a persistent vector object model |
| Advanced artistic effects (oil, emboss, distortions, clouds, noise reduction…) | Partial | Adjustments and blur/sharpen were prioritized; the `Effect` framework lets you add more without changing the UI |
| Per-channel color correction in Levels/Curves | No | Master channel only (RGB together) |
| GIF animation, multipage TIFF | No | Only the first frame is opened/saved |
| Alpha in BMP | No | Not interoperable; flattened on white |
| ICC color profiles, 16 bits per channel | No | Work is in 8-bit sRGB; 16-bit images are converted to 8 on open |
| Clone stamp, recolor, freeform curve | No | Outside the requested core; the `Tool` framework allows adding them |
| Ruler, pixel grid, configurable selection antialiasing, custom brushes, pressure tablet | No | Outside the requested core |
| Scanner/camera (WIA/TWAIN) | No | Windows-specific API |
| Reduced-size effect preview for heavy effects | No | The preview uses full resolution (≈2.5 s for a blur on 12 MP) |

## Main shortcuts

Tools: `S` select · `Shift+S` ellipse · `L` lasso · `W` wand · `M` move pixels · `Shift+M` move selection · `B` brush · `P` pencil · `E` eraser · `F` fill · `G` gradient · `I` line · `O` rectangle · `Shift+O` rounded · `J` ellipse · `T` text · `K` color picker · `Z` zoom · `H` pan.
Edit: `Ctrl+Z` / `Ctrl+Y` undo/redo · `Ctrl+A/D/I` all/none/invert · `Esc` clear selection · `Backspace` fill with primary · `X` swap colors.
Layers: `Ctrl+Shift+N` new · `Ctrl+Shift+D` duplicate · `Ctrl+M` merge down · `F4` properties.
Adjustments: `Ctrl+L` levels · `Ctrl+Shift+M` curves · `Ctrl+Shift+U` hue/saturation · `Ctrl+Shift+I` invert · `Ctrl+Shift+G` black and white.
Selection modifiers: `Ctrl` add · `Alt` subtract · `Ctrl+Alt` intersect · `Shift` square/circle.

## Steps to verify on Linux Mint

1. `./scripts/install_deps.sh` finishes with "All good."
2. `./scripts/run_tests.sh` → all green (234 passed).
3. `./paintmint.sh` opens the window in English. **File ▸ New** (800×600, white background).
4. Brush (`B`): draw a stroke → `Ctrl+Z` removes it, `Ctrl+Y` brings it back.
5. **Layers ▸ New layer**; draw on it; lower its opacity with the slider in the *Layers* panel; hide it with its checkbox.
6. Rectangle select (`S`), then **Adjustments ▸ Brightness and contrast…**: the preview only affects the selection; *Cancel* reverts it, *OK* adds one history step.
7. Text (`T`): click the image, type in the *Text* panel, change font/size; click the text again to re-edit it.
8. **Effects ▸ Gaussian blur…** and **Adjustments ▸ Curves…** (drag curve points).
9. **File ▸ Save as…** to `.png`, `.jpg`, `.bmp`, `.gif`, `.tif` and `.ora`; close and reopen them.
10. Esc with an active selection clears it; Ctrl+J creates a new layer from the selection; the cursor changes with each tool.
11. Magic wand (`W`): the tolerance is a slider. Open the **Colors** window: wheel, R/G/B/H/S/V/Alpha sliders, Hex field and the palette all update the primary/secondary colors.
12. **Help ▸ Language ▸ Español**, restart → Spanish UI. **Help ▸ About** shows the repo link and the donation button. **Help ▸ Check for updates…** reports the version status.
13. Errors: open a text file renamed to `.png` → a "not a valid image or is damaged" warning appears and the app stays open; save into a folder without permission (e.g. `/`) → a permission warning.

## Links

Repository: <https://github.com/juantopoarg/PaintMint>
