# UI Patterns — macOS Statusbar App

This app is a macOS statusbar (accessory) app with no foreground presence. These patterns apply to all UI code.

## Topmost Alert Dialogs

Standard modal dialogs won't appear. Use `self._topmost_alert()` + `self._restore_accessory()` instead. It activates the app, sets `NSStatusWindowLevel`, and runs a modal `NSAlert`.

## Notifications — Prefer `wz.alert`

Use `wz.alert(text)` for transient events. Do **not** use `send_notification()` unless the user explicitly asks — system notifications persist in Notification Center and require bundle setup.

## Dark Mode

- Use semantic colors (`labelColor`, `textBackgroundColor`, etc.), never `blackColor`/`whiteColor`.
- Custom colors: `dynamic_color(light_rgba, dark_rgba)` from `ui_helpers.py`.
- Never use deprecated `colorWithCalibratedRed_green_blue_alpha_`.
- Reference: `ui/result_window_web.py`.

## See Also

- **NSPanel from menu callbacks**, **ObjC class uniqueness**, **arbitrary AppKit attrs** — covered in [`dev/wkwebview-pitfalls.md`](wkwebview-pitfalls.md) #6-#8
