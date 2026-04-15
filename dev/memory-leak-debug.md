# Memory Leak Debug History

Records all NSGlassEffectView / IOSurface memory leak investigations to prevent duplicate work.

## Background

`NSGlassEffectView` allocates a GPU-backed IOSurface ("CA Whippet Drawable" in vmmap, ~63-72 MB at retina) for behind-window compositing. These are **not released** by `orderOut_` alone. If not properly cleaned up, they accumulate and push process memory past 200 MB.

## Failed Approaches for ChooserPanel

| Approach | Commit | Result |
|----------|--------|--------|
| `setState_(0)` (inactive) | `5d071c6` | CALayer tree intact, surface not deallocated |
| `setState_(0)` + shrink to 1x1 | `58bf0e6` | Same — works for simple panels, not complex hierarchies |
| `release_panel_surfaces()` (setState + shrink helper) | `fce6b55` | Same approach packaged as helper, same result |
| Change recycle mode to `prebuild` | reverted | Unnecessary — IOSurface only allocated on `orderFront_`, not on hidden HTML load |

## The Fix: `removeFromSuperview()` (commit `8927a70`)

Removing the glass view from the view hierarchy severs the CALayer reference chain, letting Core Animation deallocate the compositor surface. Previous approaches left the glass view in-tree with state=0 — the layer chain stayed intact and the surface was never freed.

```python
# _deactivate_glass() — on close
self._glass_view.removeFromSuperview()
panel.setFrame_display_(NSMakeRect(x, y, 1, 1), False)

# _activate_glass() — on show
if self._glass_view.superview() is None:
    panel.contentView().addSubview_(self._glass_view)
self._glass_view.setFrame_(panel.contentView().bounds())
configure_glass_appearance(self._glass_view)
```

The glass view object stays alive via `self._glass_view` — only the AppKit hierarchy link is broken.

## Key Insight: CA Whippet Drawable Lifecycle

IOSurface is **only allocated on `orderFront_`** (panel visible). NOT allocated when:
- Loading HTML in a hidden WKWebView
- Building a panel without showing it
- Setting panel alpha to 0

So `preload_html` recycle mode is safe — verified: memory stays under 90 MB through multiple cycles.

## Investigation Timeline

1. **`5d071c6`** (2026-04-10) — First attempt: `setState_(0/1)` toggle on NSVisualEffectView
2. **`58bf0e6`** (2026-04-10) — `release_panel_surfaces()` helper (setState + shrink 1x1)
3. **`3b10ba1`** (2026-04-10) — Added `debug_scripts/debug_memory.py`
4. **`b2a3b46`** (2026-04-11) — Migrated all panels to NSGlassEffectView (same IOSurface behavior)
5. **`5557206`** (2026-04-11) — Compacted chooser UI to reduce surface area ~42%
6. **`d5e2429`** (2026-04-12) — Fixed WebContent process leak in recycle
7. **`8cfed68`** (2026-04-13) — Added `release_panel_surfaces()` to 7 panels missing cleanup
8. **`fce6b55`** (2026-04-14) — `setState_(0)` on glass view (still didn't work)
9. **`8927a70`** (2026-04-14) — `removeFromSuperview()` — **the fix that works**

## Rules for New Glass Panels

1. **Simple panels** (destroyed on close): `release_panel_surfaces(panel)` before `orderOut_()`.
2. **Reused panels** (kept alive across cycles): `removeFromSuperview()` on hide, `addSubview_()` on show.
3. **Never assume** `orderOut_()` or `setState_(0)` releases IOSurface.

## Remaining

- Python heap slow growth: 29→33 MB over 19 hours (+25K allocs, 14.5 MB fragmentation). Minor.

## Debugging Tools

`vmmap <pid>` (look for "CA Whippet Drawable"), `heap <pid>`, `debug_scripts/debug_memory.py`, Activity Monitor "Real Memory".
