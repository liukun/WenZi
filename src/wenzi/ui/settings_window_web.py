"""WebView-based settings panel.

Uses WKWebView + WKScriptMessageHandler for a modern HTML/CSS/JS settings UI.
Drop-in replacement for the native PyObjC SettingsPanel.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bridge JavaScript injected at document start
# ---------------------------------------------------------------------------
_BRIDGE_JS = """\
(function() {
    window._postMessage = function(msg) {
        window.webkit.messageHandlers.wz.postMessage(msg);
    };
    // Forward console to Python logger
    var _origConsole = {log: console.log.bind(console), warn: console.warn.bind(console), error: console.error.bind(console)};
    function _forward(level, args) {
        try {
            var msg = Array.from(args).map(function(a) { return typeof a === 'object' ? JSON.stringify(a) : String(a); }).join(' ');
            window.webkit.messageHandlers.wz.postMessage({type: 'console', level: level, message: msg});
        } catch(e) {}
    }
    console.log = function() { _origConsole.log.apply(null, arguments); _forward('info', arguments); };
    console.warn = function() { _origConsole.warn.apply(null, arguments); _forward('warning', arguments); };
    console.error = function() { _origConsole.error.apply(null, arguments); _forward('error', arguments); };
})();
"""

# ---------------------------------------------------------------------------
# Minimal placeholder HTML template (replaced in later tasks)
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Settings</title>
<script>var __STATE__ = __CONFIG__;</script>
</head>
<body>
<p>Settings panel placeholder</p>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Close delegate (lazy-created to avoid PyObjC import at module level)
# ---------------------------------------------------------------------------
_PanelCloseDelegate = None


def _get_panel_close_delegate_class():
    global _PanelCloseDelegate
    if _PanelCloseDelegate is None:
        from Foundation import NSObject

        class SettingsWebPanelCloseDelegate(NSObject):
            _panel_ref = None

            def windowWillClose_(self, notification):
                if self._panel_ref is not None:
                    self._panel_ref.close()

        _PanelCloseDelegate = SettingsWebPanelCloseDelegate
    return _PanelCloseDelegate


# ---------------------------------------------------------------------------
# WKScriptMessageHandler (lazy-created)
# ---------------------------------------------------------------------------
_MessageHandler = None


def _get_message_handler_class():
    global _MessageHandler
    if _MessageHandler is None:
        import objc
        from Foundation import NSObject

        # Load WebKit framework first so the protocol is available
        import WebKit  # noqa: F401

        WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")
        logger.debug("WKScriptMessageHandler protocol: %s", WKScriptMessageHandler)

        class SettingsWebMessageHandler(
            NSObject, protocols=[WKScriptMessageHandler]
        ):
            _panel_ref = None

            def userContentController_didReceiveScriptMessage_(
                self, controller, message
            ):
                if self._panel_ref is None:
                    return
                raw = message.body()
                # WKWebView returns NSDictionary with ObjC value types;
                # JSON roundtrip converts everything to native Python types
                try:
                    from Foundation import NSJSONSerialization
                    json_data, _ = (
                        NSJSONSerialization
                        .dataWithJSONObject_options_error_(raw, 0, None)
                    )
                    body = json.loads(bytes(json_data))
                except Exception:
                    logger.warning("Cannot convert message body: %r", raw)
                    return
                self._panel_ref._handle_js_message(body)

        _MessageHandler = SettingsWebMessageHandler
    return _MessageHandler


# ---------------------------------------------------------------------------
# Panel class
# ---------------------------------------------------------------------------


class SettingsWebPanel:
    """WKWebView-based settings panel.

    Drop-in replacement for the native PyObjC SettingsPanel, with the same
    public API surface.
    """

    _PANEL_WIDTH = 750
    _PANEL_HEIGHT = 560

    def __init__(self) -> None:
        self._panel = None
        self._webview = None
        self._close_delegate = None
        self._message_handler = None
        self._callbacks: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_visible(self) -> bool:
        """Return True if the panel is currently visible."""
        if self._panel is None:
            return False
        return bool(self._panel.isVisible())

    def show(self, state: dict, callbacks: dict) -> None:
        """Show the settings panel with the given state and callbacks."""
        self._callbacks = callbacks
        self._build_panel(state)

        self._panel.makeKeyAndOrderFront_(None)

        from AppKit import NSApp

        NSApp.activateIgnoringOtherApps_(True)

    def close(self) -> None:
        """Close the panel and release resources."""
        if self._panel is not None:
            self._panel.setDelegate_(None)
            self._close_delegate = None
            self._panel.orderOut_(None)
            self._panel = None
        self._webview = None
        self._message_handler = None
        self._callbacks = None

        from AppKit import NSApp

        NSApp.setActivationPolicy_(1)  # Accessory (statusbar-only)

    def update_state(self, state: dict) -> None:
        """Push updated state to the webview (stub for Task 4)."""
        pass

    # ------------------------------------------------------------------
    # Callbacks from JavaScript
    # ------------------------------------------------------------------

    def _handle_js_message(self, body: dict) -> None:
        """Dispatch messages from JavaScript."""
        if not self.is_visible:
            return

        msg_type = body.get("type", "")
        logger.debug("Handling JS message: type=%s body=%s", msg_type, body)

        if msg_type == "console":
            level = body.get("level", "info")
            message = body.get("message", "")
            getattr(logger, level, logger.info)("[WebView] %s", message)
            return

        if msg_type == "callback":
            name = body.get("name", "")
            args = body.get("args", [])
            if self._callbacks and name in self._callbacks:
                cb = self._callbacks[name]
                try:
                    cb(*args)
                except Exception:
                    logger.exception("Callback %s raised", name)
            else:
                logger.warning("Unknown callback: %s", name)
            return

        logger.warning("Unknown JS message type: %s", msg_type)

    # ------------------------------------------------------------------
    # State preparation (stub for Task 3)
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_state(state: dict) -> dict:
        """Convert state for JSON serialization (pass-through for now)."""
        return state

    # ------------------------------------------------------------------
    # Panel construction
    # ------------------------------------------------------------------

    def _build_panel(self, state: dict) -> None:
        """Build NSPanel + WKWebView and load the HTML template."""
        from AppKit import (
            NSApp,
            NSBackingStoreBuffered,
            NSClosableWindowMask,
            NSPanel,
            NSResizableWindowMask,
            NSScreen,
            NSStatusWindowLevel,
            NSTitledWindowMask,
        )
        from Foundation import NSMakeRect
        from WebKit import (
            WKUserContentController,
            WKUserScript,
            WKWebView,
            WKWebViewConfiguration,
        )

        from wenzi.ui.result_window_web import _ensure_edit_menu

        # Enable Cmd+C/V/A via Edit menu in the responder chain
        _ensure_edit_menu()

        NSApp.setActivationPolicy_(0)  # Regular (foreground)

        if self._panel is not None:
            # Reuse existing panel — just reload content
            self._load_html(state)
            return

        # Create NSPanel
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, self._PANEL_WIDTH, self._PANEL_HEIGHT),
            NSTitledWindowMask | NSClosableWindowMask | NSResizableWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setTitle_("Settings")

        # Close delegate
        delegate_cls = _get_panel_close_delegate_class()
        delegate = delegate_cls.alloc().init()
        delegate._panel_ref = self
        panel.setDelegate_(delegate)
        self._close_delegate = delegate

        # WKWebView with message handler and bridge script
        config = WKWebViewConfiguration.alloc().init()
        content_controller = WKUserContentController.alloc().init()

        handler_cls = _get_message_handler_class()
        handler = handler_cls.alloc().init()
        handler._panel_ref = self
        content_controller.addScriptMessageHandler_name_(handler, "wz")

        # Inject bridge JS at document start
        bridge_script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
            _BRIDGE_JS,
            0,  # WKUserScriptInjectionTimeAtDocumentStart
            True,
        )
        content_controller.addUserScript_(bridge_script)

        config.setUserContentController_(content_controller)

        webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self._PANEL_WIDTH, self._PANEL_HEIGHT),
            config,
        )
        webview.setAutoresizingMask_(0x12)  # width + height sizable
        webview.setValue_forKey_(False, "drawsBackground")
        panel.contentView().addSubview_(webview)

        self._panel = panel
        self._webview = webview
        self._message_handler = handler

        # Center on screen
        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.visibleFrame()
            pf = panel.frame()
            x = sf.origin.x + (sf.size.width - pf.size.width) / 2
            y = sf.origin.y + (sf.size.height - pf.size.height) / 2
            panel.setFrameOrigin_((x, y))
        else:
            panel.center()

        self._load_html(state)

    def _load_html(self, state: dict) -> None:
        """Load the HTML template with the given state into the webview."""
        from Foundation import NSURL

        config_data = self._prepare_state(state)
        html_content = _HTML_TEMPLATE.replace(
            "__CONFIG__", json.dumps(config_data, ensure_ascii=False)
        )
        self._webview.loadHTMLString_baseURL_(
            html_content, NSURL.fileURLWithPath_("/")
        )
