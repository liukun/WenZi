"""Tests for wenzi.ui.web_utils — cleanup_webview and lightweight config."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from wenzi.ui.web_utils import cleanup_webview


def _make_mock_webkit():
    """Build a mock WebKit module with the classes lightweight_webview_config needs."""
    mock_webkit = MagicMock()

    mock_config = MagicMock(name="WKWebViewConfig")
    mock_webkit.WKWebViewConfiguration.alloc.return_value.init.return_value = mock_config

    mock_store = MagicMock(name="nonPersistentStore")
    mock_webkit.WKWebsiteDataStore.nonPersistentDataStore.return_value = mock_store

    return mock_webkit, mock_config, mock_store


class TestCleanupWebview:
    def test_none_webview_is_noop(self):
        cleanup_webview(None)  # should not raise

    def test_removes_handler_and_scripts(self):
        wv = MagicMock()
        ucc = wv.configuration().userContentController()
        cleanup_webview(wv, handler_name="action")
        ucc.removeScriptMessageHandlerForName_.assert_called_once_with("action")
        ucc.removeAllUserScripts.assert_called_once()

    def test_clears_nav_delegate_and_loads_blank(self):
        wv = MagicMock()
        cleanup_webview(wv)
        wv.setNavigationDelegate_.assert_called_once_with(None)
        wv.stopLoading_.assert_called_once_with(None)
        wv.loadHTMLString_baseURL_.assert_called_once_with("", None)

    def test_handler_name_none_skips_handler_removal(self):
        wv = MagicMock()
        ucc = wv.configuration().userContentController()
        cleanup_webview(wv, handler_name=None)
        ucc.removeScriptMessageHandlerForName_.assert_not_called()
        # removeAllUserScripts is still called
        ucc.removeAllUserScripts.assert_called_once()

    def test_handler_exception_swallowed(self):
        wv = MagicMock()
        wv.configuration().userContentController().removeScriptMessageHandlerForName_.side_effect = Exception("boom")
        cleanup_webview(wv)  # should not raise
        # stopLoading_ / loadHTMLString_ are still called
        wv.stopLoading_.assert_called_once_with(None)


class TestLightweightWebviewConfig:
    def test_returns_config(self):
        mock_webkit, mock_config, _ = _make_mock_webkit()
        with patch.dict("sys.modules", {"WebKit": mock_webkit}):
            from wenzi.ui.web_utils import _reset_shared_state, lightweight_webview_config

            _reset_shared_state()
            config = lightweight_webview_config()
            assert config is mock_config

    def test_uses_non_persistent_data_store_by_default(self):
        mock_webkit, mock_config, mock_store = _make_mock_webkit()
        with patch.dict("sys.modules", {"WebKit": mock_webkit}):
            from wenzi.ui.web_utils import _reset_shared_state, lightweight_webview_config

            _reset_shared_state()
            lightweight_webview_config()
            mock_config.setWebsiteDataStore_.assert_called_once_with(mock_store)

    def test_non_persistent_store_is_cached(self):
        mock_webkit, mock_config, _ = _make_mock_webkit()
        with patch.dict("sys.modules", {"WebKit": mock_webkit}):
            from wenzi.ui.web_utils import _reset_shared_state, lightweight_webview_config

            _reset_shared_state()
            lightweight_webview_config()
            lightweight_webview_config()
            # nonPersistentDataStore() should only be called once
            mock_webkit.WKWebsiteDataStore.nonPersistentDataStore.assert_called_once()

    def test_network_true_skips_non_persistent_store(self):
        mock_webkit, mock_config, _ = _make_mock_webkit()
        with patch.dict("sys.modules", {"WebKit": mock_webkit}):
            from wenzi.ui.web_utils import _reset_shared_state, lightweight_webview_config

            _reset_shared_state()
            lightweight_webview_config(network=True)
            mock_config.setWebsiteDataStore_.assert_not_called()

    def test_no_process_pool_set(self):
        """WKProcessPool is deprecated — config should NOT set one."""
        mock_webkit, mock_config, _ = _make_mock_webkit()
        with patch.dict("sys.modules", {"WebKit": mock_webkit}):
            from wenzi.ui.web_utils import _reset_shared_state, lightweight_webview_config

            _reset_shared_state()
            lightweight_webview_config()
            mock_config.setProcessPool_.assert_not_called()
