"""Tests for WebViewPanel — core panel class with JS bridge communication.

UI/WKWebView parts are not testable in CI — these tests cover the
pure-Python logic: bridge event/call routing, handler registration,
lifecycle state management.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from wenzi.scripting.ui.webview_panel import WebViewPanel


def _make_panel(**kwargs) -> WebViewPanel:
    """Create a WebViewPanel with eval_js mocked (no WKWebView)."""
    panel = WebViewPanel(title="Test", html="<p>hi</p>", **kwargs)
    panel._webview = MagicMock()
    panel._panel = MagicMock()
    panel._open = True
    return panel


# ---------------------------------------------------------------------------
# Construction defaults
# ---------------------------------------------------------------------------


class TestWebViewPanelDefaults:
    def test_default_dimensions(self):
        p = WebViewPanel(title="T", html="<b>x</b>")
        assert p._width == 900
        assert p._height == 700

    def test_custom_dimensions(self):
        p = WebViewPanel(title="T", html="<b>x</b>", width=400, height=300)
        assert p._width == 400
        assert p._height == 300

    def test_default_resizable(self):
        p = WebViewPanel(title="T", html="<b>x</b>")
        assert p._resizable is True

    def test_default_allowed_read_paths(self):
        p = WebViewPanel(title="T", html="<b>x</b>")
        assert p._allowed_read_paths == []

    def test_stores_title_and_html(self):
        p = WebViewPanel(title="My Title", html="<div>content</div>")
        assert p._title == "My Title"
        assert p._html == "<div>content</div>"


# ---------------------------------------------------------------------------
# Bridge: on() / handle() registration
# ---------------------------------------------------------------------------


class TestWebViewPanelBridge:
    def test_on_registers_event_handler(self):
        panel = _make_panel()
        cb = MagicMock()
        panel.on("my_event", cb)
        assert "my_event" in panel._event_handlers
        assert cb in panel._event_handlers["my_event"]

    def test_on_multiple_handlers_same_event(self):
        panel = _make_panel()
        cb1 = MagicMock()
        cb2 = MagicMock()
        panel.on("evt", cb1)
        panel.on("evt", cb2)
        assert len(panel._event_handlers["evt"]) == 2

    def test_handle_decorator_registers(self):
        panel = _make_panel()

        @panel.handle("do_stuff")
        def handler(data):
            return "ok"

        assert "do_stuff" in panel._call_handlers
        assert panel._call_handlers["do_stuff"] is handler

    def test_handle_js_message_routes_event(self):
        panel = _make_panel()
        cb = MagicMock()
        panel.on("ping", cb)

        panel._handle_js_message({"type": "event", "name": "ping", "data": {"x": 1}})
        cb.assert_called_once_with({"x": 1})

    def test_handle_js_message_routes_event_multiple_handlers(self):
        panel = _make_panel()
        cb1 = MagicMock()
        cb2 = MagicMock()
        panel.on("ping", cb1)
        panel.on("ping", cb2)

        panel._handle_js_message({"type": "event", "name": "ping", "data": 42})
        cb1.assert_called_once_with(42)
        cb2.assert_called_once_with(42)

    def test_handle_js_message_event_no_handler_no_error(self):
        """Events with no registered handler should be silently ignored."""
        panel = _make_panel()
        # Should not raise
        panel._handle_js_message({"type": "event", "name": "unknown", "data": None})

    def test_handle_js_message_routes_call(self):
        """Call messages should dispatch to _run_call_handler on a background thread."""
        panel = _make_panel()
        handler = MagicMock(return_value="result")
        panel._call_handlers["greet"] = handler

        with patch.object(panel, "_run_call_handler") as mock_run:
            panel._handle_js_message(
                {"type": "call", "name": "greet", "data": "hello", "callId": "c1"}
            )
            mock_run.assert_called_once_with("greet", "hello", "c1")

    def test_handle_js_message_call_no_handler_rejects(self):
        """Call with no registered handler should resolve with error."""
        panel = _make_panel()

        with patch.object(panel, "_reject_call") as mock_reject:
            panel._handle_js_message(
                {"type": "call", "name": "missing", "data": None, "callId": "c2"}
            )
            mock_reject.assert_called_once()
            args = mock_reject.call_args
            assert args[0][0] == "c2"
            assert "missing" in args[0][1]

    def test_send_calls_eval_js(self):
        panel = _make_panel()
        panel.send("myEvent", {"key": "val"})

        panel._webview.evaluateJavaScript_completionHandler_.assert_called_once()
        js_code = panel._webview.evaluateJavaScript_completionHandler_.call_args[0][0]
        assert "myEvent" in js_code
        assert "val" in js_code

    def test_send_ignored_when_closed(self):
        panel = _make_panel()
        panel._open = False
        panel.send("myEvent", {"key": "val"})
        panel._webview.evaluateJavaScript_completionHandler_.assert_not_called()

    def test_eval_js_ignored_when_closed(self):
        panel = _make_panel()
        panel._open = False
        panel.eval_js("alert(1)")
        panel._webview.evaluateJavaScript_completionHandler_.assert_not_called()

    def test_set_html_updates_stored_html(self):
        panel = _make_panel()
        panel.set_html("<p>new</p>")
        assert panel._html == "<p>new</p>"

    def test_run_call_handler_success(self):
        """_run_call_handler should call handler and resolve on success."""
        panel = _make_panel()
        handler = MagicMock(return_value={"status": "ok"})
        panel._call_handlers["action"] = handler

        with patch.object(panel, "_resolve_call") as mock_resolve:
            panel._run_call_handler("action", {"input": 1}, "c5")
            handler.assert_called_once_with({"input": 1})
            mock_resolve.assert_called_once_with("c5", {"status": "ok"})

    def test_run_call_handler_error(self):
        """_run_call_handler should reject on handler exception."""
        panel = _make_panel()
        handler = MagicMock(side_effect=ValueError("boom"))
        panel._call_handlers["bad"] = handler

        with patch.object(panel, "_reject_call") as mock_reject:
            panel._run_call_handler("bad", None, "c6")
            mock_reject.assert_called_once()
            assert "c6" == mock_reject.call_args[0][0]
            assert "boom" in mock_reject.call_args[0][1]

    def test_resolve_call_evals_js(self):
        panel = _make_panel()
        panel._resolve_call("c10", {"msg": "done"})

        panel._webview.evaluateJavaScript_completionHandler_.assert_called_once()
        js_code = panel._webview.evaluateJavaScript_completionHandler_.call_args[0][0]
        assert "c10" in js_code
        assert "_resolve" in js_code

    def test_reject_call_evals_js(self):
        panel = _make_panel()
        panel._reject_call("c11", "something failed")

        panel._webview.evaluateJavaScript_completionHandler_.assert_called_once()
        js_code = panel._webview.evaluateJavaScript_completionHandler_.call_args[0][0]
        assert "c11" in js_code
        assert "_reject" in js_code


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestWebViewPanelLifecycle:
    def test_close_silences_subsequent_sends(self):
        panel = _make_panel()
        with patch.dict("sys.modules", {"AppKit": MagicMock()}):
            panel.close()
        assert panel._open is False
        panel.send("evt", {})
        panel._webview.evaluateJavaScript_completionHandler_.assert_not_called()

    def test_double_close_is_noop(self):
        panel = _make_panel()
        with patch.dict("sys.modules", {"AppKit": MagicMock()}):
            panel.close()
            # Second close should not raise (already not open)
            panel.close()
        assert panel._open is False

    def test_initial_state_is_not_open(self):
        """Before show() is called, the panel should not be open."""
        p = WebViewPanel(title="T", html="<b>x</b>")
        assert p._open is False

    def test_close_rejects_pending_calls(self):
        """Closing should reject all pending JS calls."""
        panel = _make_panel()
        panel._pending_calls["c1"] = True
        panel._pending_calls["c2"] = True

        with patch.dict("sys.modules", {"AppKit": MagicMock()}):
            panel.close()

        # After close, pending calls dict should be cleared
        assert len(panel._pending_calls) == 0
