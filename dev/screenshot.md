# Screenshot & Picture Editor

## Architecture

Screenshot uses macOS `screencapture -i` for region selection (supports drag selection + Space to switch to window capture), then opens an annotation editor built with WKWebView + Fabric.js.

```
src/wenzi/screenshot/
├── __init__.py          # Exports AnnotationLayer
├── annotation.py        # WKWebView annotation layer (composes WebViewPanel)
└── templates/
    ├── annotation.html  # Canvas annotation UI
    ├── annotation.css   # Toolbar and tool styles
    ├── annotation.js    # 8 annotation tools + undo/redo + export
    └── fabric.min.js    # Fabric.js v6.6.1 (bundled locally)
```

## Flow

1. User presses hotkey (`Cmd+Ctrl+A` by default, configurable in Settings → Screenshot)
2. `screencapture -i` runs in a background thread — macOS shows native selection UI
3. On success, `AnnotationLayer` opens the image in a titled WKWebView panel
4. User annotates with tools (rect, ellipse, arrow, line, pen, mosaic, text, numbered markers)
5. Double-click / Enter / ✓ → exports Canvas as PNG → clipboard; save icon → NSSavePanel

## Configuration

```json
{
  "screenshot": {
    "enabled": false,
    "hotkey": "cmd+ctrl+a"
  }
}
```

Screenshot is **disabled by default**. Enable it in Settings → Screenshot. The hotkey listener only starts when `enabled` is true.

## AnnotationLayer API

`AnnotationLayer` composes `WebViewPanel` — it does NOT duplicate bridge JS, message handlers, or file scheme handlers. All WKWebView infrastructure is inherited.

Key parameter: `delete_on_close` — set to `True` for screenshot temp files (auto-cleaned), `False` for plugin-provided user files (preserved).

## Plugin API — `wz.ui.picture_editor`

Plugins can open the annotation editor for any image file:

```python
wz.ui.picture_editor(
    image_path="/path/to/image.jpg",
    on_done=lambda: wz.log("Copied to clipboard"),
    on_cancel=lambda: wz.log("Cancelled"),
)
```

- Supports all macOS image formats: PNG, JPG, GIF, BMP, WebP, TIFF, etc.
- The original image file is **never** modified or deleted.
- `on_done` and `on_cancel` are optional.

## PyInstaller Packaging

The `templates/` directory must be included in both spec files:
```python
datas=[
    ('src/wenzi/screenshot/templates', 'wenzi/screenshot/templates'),
]
```
