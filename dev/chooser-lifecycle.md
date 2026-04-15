# Launcher (Chooser) Panel Lifecycle

The chooser panel (`ChooserPanel`) uses a **hide/reuse** strategy for performance. WKWebView creation + HTML loading is expensive (~200-500ms), so the panel is kept alive across open/close cycles.

## Close Behavior

`close()` hides the panel (`orderOut_`), breaks `_panel_ref` back-references to prevent retain cycles, then detaches the glass view from the hierarchy to release IOSurface memory. Sets `_page_loaded = False`.

**Critical:** Do NOT set `self._panel = None` or `self._webview = None` in `close()` — this would break the reuse path and force a cold start on every open.

To prevent retain cycles while hidden, nil out `_panel_ref` on the message handler, navigation delegate, and panel delegate instead.

## Destroy Behavior

`destroy()` fully tears down the panel and webview. Only called during `engine.reload()` when HTML/i18n may have changed.

## Show Paths

1. **Hot path** (`_page_loaded` is True) — reconnects refs and resets UI via JS. Fastest, no HTML reload.
2. **Warm path** (panel + webview alive, `_page_loaded` is False) — reconnects refs and reloads cached HTML. Panel hidden (alpha=0) until `_on_page_loaded` reveals it (alpha=1).
3. **Cold path** (no panel) — builds everything from scratch.

## Recycle Mechanism

After close, a 60s timer fires `_do_recycle()` which destroys the old panel/webview and builds a new one. Default mode is `preload_html` (builds panel + loads HTML for fast re-show).

## IOSurface Memory Management

The glass view is detached from the view hierarchy on close (`removeFromSuperview()`) and re-added on show (`addSubview_()`). This is required to release the CA Whippet Drawable IOSurface (~63 MB+ at retina). See [`dev/memory-leak-debug.md`](memory-leak-debug.md) for full investigation history.
