# WKWebView Pitfalls in PyObjC Statusbar Apps

These pitfalls apply to any WKWebView-based UI panel in this project.

## 1. JS Call Queue — Page Load Race

JS calls during page load are **silently dropped**. Gate all JS behind a `_page_loaded` flag with a pending queue:

```python
def _eval_js(self, js_code: str) -> None:
    if self._webview is None:
        return
    if not self._page_loaded:
        self._pending_js.append(js_code)
        return
    self._webview.evaluateJavaScript_completionHandler_(js_code, None)
```

Flush in `webView:didFinishNavigation:`.

## 2. Atomic JS Flush

Flushing queued JS one-by-one is unsafe — WKWebView may interleave callbacks between evaluations. Combine all pending JS into one `;`-joined string:

```python
def _on_page_loaded(self) -> None:
    pending = self._pending_js[:]
    self._pending_js.clear()
    self._page_loaded = True
    if pending and self._webview is not None:
        self._webview.evaluateJavaScript_completionHandler_(";".join(pending), None)
```

## 3. Edit Menu — Cmd+C/V/A Not Working

Statusbar apps have no Edit menu. WKWebView needs it for keyboard shortcuts. Call `_ensure_edit_menu()` (from `result_window_web.py`) in `_build_panel()`.

## 4. WKScriptMessageHandler Protocol Binding

PyObjC needs explicit protocol conformance — implicit method-name matching doesn't work:

```python
WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")

class MyHandler(NSObject, protocols=[WKScriptMessageHandler]):
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        ...
```

Must `import WebKit` first to register the protocol.

## 5. NSDictionary != Python dict

`message.body()` returns ObjC types. JSON-roundtrip to get Python natives:

```python
raw = message.body()
json_data, _ = NSJSONSerialization.dataWithJSONObject_options_error_(raw, 0, None)
body = json.loads(bytes(json_data))
```

## 6. ObjC Class Name Global Uniqueness

ObjC class names are process-global. Two modules defining `class PanelCloseDelegate(NSObject)` will crash. Prefix with module name: `SettingsPanelCloseDelegate`, etc. Use lazy-cached factory:

```python
_MyDelegate = None
def _get_delegate_class():
    global _MyDelegate
    if _MyDelegate is None:
        class MyUniqueDelegate(NSObject): ...
        _MyDelegate = MyUniqueDelegate
    return _MyDelegate
```

## 7. Statusbar App Window Lifecycle

Menu callbacks briefly activate the app. If `show()` is deferred via `callAfter`, the window never appears. Always show **synchronously**:

**`show()`:** (1) `NSApp.setActivationPolicy_(0)` → (2) build panel → (3) `makeKeyAndOrderFront_` → (4) `activateIgnoringOtherApps_`

**`close()`:** (1) `orderOut_` → (2) `NSApp.setActivationPolicy_(1)`

## 8. No Arbitrary Attributes on AppKit Objects

`btn._my_data = "foo"` raises `AttributeError` at runtime (works with MagicMock in tests). Use `dict` keyed by `id(obj)` instead.

## 9. innerHTML Inline Handlers Are Dead

Inline `onclick`/`onchange` in HTML inserted via `innerHTML` **don't fire**. Use event delegation on the static container with `data-*` attributes:

```javascript
container.addEventListener('click', function(e) {
  var el = e.target.closest('[data-action="my-action"]');
  if (el) postCallback('my_action', el.dataset.key);
});
```

## 10. Update CONFIG Before Re-rendering

If `_updateState()` sets DOM values then calls a render function that rebuilds from `CONFIG`, the render overwrites the DOM. Update `CONFIG` first:

```javascript
if (state.restart_key !== undefined) CONFIG.restart_key = state.restart_key;
renderHotkeys();  // now uses new value
```

## 11. JS Native Dialogs Don't Work

`alert()`, `confirm()`, `prompt()` are silently no-ops without `WKUIDelegate`. Use custom HTML modals instead.

## 12. Audio — Use `wz.playAudio()`, Not `new Audio()`

`new Audio().play()` triggers macOS Now Playing. Route through native bridge:
- WebView panels: `wz.playAudio(url)`
- Chooser preview (no `wz` bridge): `webkit.messageHandlers.chooser.postMessage({type: 'playAudio', url: url})`

ChooserPanel uses `AVAudioPlayer` (not `NSSound`, which interferes with compositing).

## Checklist for New WKWebView Panels

- [ ] `_eval_js` with `_page_loaded` gate + `_pending_js` queue
- [ ] `_on_page_loaded` with atomic `;`-joined flush
- [ ] `WKNavigationDelegate` (lazy-cached, unique class name)
- [ ] `WKScriptMessageHandler` with `objc.protocolNamed` (lazy-cached, unique name)
- [ ] `PanelCloseDelegate` (lazy-cached, unique name)
- [ ] `_ensure_edit_menu()` if panel has editable fields
- [ ] JSON-roundtrip all `message.body()`
- [ ] Show panel synchronously (no `callAfter`)
- [ ] `prefers-color-scheme: dark` CSS for dark mode
- [ ] Reset `_page_loaded = False` + clear `_pending_js` in `close()`
- [ ] Event delegation for `innerHTML` content — never inline handlers
- [ ] Never use `alert()` / `confirm()` / `prompt()`
- [ ] Update `CONFIG` before render functions in `_updateState()`
- [ ] `wz.playAudio()` for audio, never `new Audio()`
