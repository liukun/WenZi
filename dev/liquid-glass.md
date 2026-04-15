# NSGlassEffectView — Liquid Glass API Reference

macOS 26+ Liquid Glass — replaces NSVisualEffectView (deprecated in this project).

## Core Properties

| Property | Type | Notes |
|----------|------|-------|
| `contentView` | NSView | Content embedding point. Only content inside `contentView` renders correctly |
| `cornerRadius` | CGFloat | Built-in corner radius, no maskImage needed |
| `tintColor` | NSColor | Background tint, recommended alpha 0.2-0.3 |
| `style` | `.regular`/`.clear` | `.clear` only for media-dense backgrounds |

## Usage (PyObjC)

```python
from AppKit import NSGlassEffectView
glass = NSGlassEffectView.alloc().initWithFrame_(frame)
glass.setCornerRadius_(18)
glass.setContentView_(webview)
```

Window must be transparent: `panel.setOpaque_(False)`, `panel.setBackgroundColor_(NSColor.clearColor())`, `panel.setHasShadow_(True)`.

## NSGlassEffectContainerView

Container for multiple glass elements. `spacing` controls liquid merge distance. Elements within `spacing` auto-merge. Prevents glass-sampling-glass artifacts.

## Lock Adaptive Appearance (Critical)

NSGlassEffectView is **adaptive by default** — it samples behind-window brightness and ignores the system theme. Must disable:

```python
from wenzi.ui_helpers import configure_glass_appearance
glass = NSGlassEffectView.alloc().initWithFrame_(frame)
glass.setCornerRadius_(12)
configure_glass_appearance(glass)  # locks to system theme
```

Under the hood: `_adaptiveAppearance` values: 0=auto, 1=off, 2=on. We set 1 (off) + `setAppearance_` to system theme. Guard with `respondsToSelector_`.

### Other Private Properties

| Property | Values | Notes |
|----------|--------|-------|
| `_variant` | 0-23 | Material variant (2=dock, 9=notification center) |
| `_scrimState` | 0/1/2 | Scrim layer (0=none, 1=light, 2=dark) |
| `_interactionState` | 0/1 | Hover highlight (>=2 crashes) |

## Best Practices

**Always use `contentView`** — `addSubview_` directly on glass may render behind the material. Exception: decorative views (outline, highlight) intentionally layered on top.

**Enable layer clipping** — `glass.setWantsLayer_(True)`, `glass.layer().setMasksToBounds_(True)` to clip subviews to corner radius.

**Scale decorations to panel size:**
- Compact (indicator, alert pill): outline + highlight band
- Content (streaming overlay): thin outline only
- Full-size (chooser, settings): just layer masking + shadow

## Visual Enhancement Techniques

### Outline

Transparent view with `borderWidth` over glass. Enhances edge clarity.

```python
from wenzi.ui_helpers import dynamic_color
ol_color = dynamic_color((1.0, 1.0, 1.0, 0.26), (1.0, 1.0, 1.0, 0.14))
outline = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
outline.setWantsLayer_(True)
outline.layer().setCornerRadius_(corner_radius)
outline.layer().setBorderWidth_(1.0)
outline.layer().setBorderColor_(ol_color.CGColor())
glass.addSubview_(outline)
```

Compact panels: borderWidth 1.0, alpha 0.26/0.14. Content panels: 0.5, alpha 0.20/0.08.

### Highlight Band

Semi-transparent white rectangle at top of glass. Only for compact pill shapes (e.g. `wz.alert`).

### tintColor

`glass.setTintColor_(NSColor.systemBlue().colorWithAlphaComponent_(0.25))` — keep alpha 0.2-0.3.

### Event Passthrough for Decorative Views

Decorative subviews intercept mouse events. If the panel has interactive content, override `hitTest_` to return `None`. Not needed if `panel.setIgnoresMouseEvents_(True)`.

## IOSurface Memory Management

See [`dev/memory-leak-debug.md`](memory-leak-debug.md) for full investigation.

**Summary:**
- Simple panels: `release_panel_surfaces(panel)` before `orderOut_()`.
- Reused panels (ChooserPanel): `removeFromSuperview()` on glass view when hiding.
- `orderOut_()` and `setState_(0)` do NOT release the IOSurface.

## Performance

- GPU cost higher than NSVisualEffectView. Apple recommends max 5-10 glass elements.
- High-frequency redraw (e.g. 20Hz recording indicator) needs evaluation.

## Migrated Panels

Recording indicator, streaming overlay, chooser panel.

## References

- [NSGlassEffectView — Apple Developer](https://developer.apple.com/documentation/appkit/nsglasseffectview)
- [WWDC25 Session 310 — Build an AppKit app with the new design](https://developer.apple.com/videos/play/wwdc2025/310/)
