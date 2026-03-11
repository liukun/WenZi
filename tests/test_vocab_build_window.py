"""Tests for the vocabulary build progress window."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_appkit(monkeypatch):
    """Mock AppKit and Foundation modules for headless testing."""
    mock_appkit = MagicMock()
    mock_foundation = MagicMock()
    mock_pyobjctools = MagicMock()
    mock_apphelper = MagicMock()

    # Make callAfter execute the callback immediately
    mock_apphelper.callAfter = lambda fn: fn()
    mock_pyobjctools.AppHelper = mock_apphelper

    monkeypatch.setitem(sys.modules, "AppKit", mock_appkit)
    monkeypatch.setitem(sys.modules, "Foundation", mock_foundation)
    monkeypatch.setitem(sys.modules, "PyObjCTools", mock_pyobjctools)
    monkeypatch.setitem(sys.modules, "PyObjCTools.AppHelper", mock_apphelper)

    # NSMakeRect returns a mock with .size attribute
    def make_rect(x, y, w, h):
        r = MagicMock()
        r.size = MagicMock()
        r.size.width = w
        r.size.height = h
        return r

    mock_foundation.NSMakeRect = make_rect
    mock_foundation.NSAttributedString = MagicMock()

    return mock_appkit, mock_foundation, mock_apphelper


class TestVocabBuildProgressPanel:
    def _make_panel(self):
        from voicetext.vocab_build_window import VocabBuildProgressPanel

        return VocabBuildProgressPanel()

    def test_show_creates_panel(self, _mock_appkit):
        panel = self._make_panel()
        on_cancel = MagicMock()
        panel.show(on_cancel=on_cancel)

        assert panel._panel is not None
        assert panel._status_label is not None
        assert panel._stream_text_view is not None

    def test_update_status(self, _mock_appkit):
        panel = self._make_panel()
        panel.show(on_cancel=MagicMock())

        panel.update_status("Batch 1/3 — extracting...")
        panel._status_label.setStringValue_.assert_called_with("Batch 1/3 — extracting...")

    def test_append_stream_text(self, _mock_appkit):
        panel = self._make_panel()
        panel.show(on_cancel=MagicMock())

        panel.append_stream_text('{"term": "Python"')
        # Verify text storage was appended to
        panel._stream_text_view.textStorage().appendAttributedString_.assert_called()

    def test_clear_stream_text(self, _mock_appkit):
        panel = self._make_panel()
        panel.show(on_cancel=MagicMock())

        panel.clear_stream_text()
        panel._stream_text_view.setString_.assert_called_with("")

    def test_close(self, _mock_appkit):
        panel = self._make_panel()
        panel.show(on_cancel=MagicMock())

        mock_ns_panel = panel._panel
        panel.close()
        mock_ns_panel.orderOut_.assert_called_with(None)
        assert panel._panel is None

    def test_cancel_button_calls_callback(self, _mock_appkit):
        panel = self._make_panel()
        on_cancel = MagicMock()
        panel.show(on_cancel=on_cancel)

        panel.cancelClicked_(None)
        on_cancel.assert_called_once()

    def test_close_when_already_closed(self, _mock_appkit):
        panel = self._make_panel()
        # Close without show - should not raise
        panel.close()
        assert panel._panel is None

    def test_update_status_when_no_label(self, _mock_appkit):
        panel = self._make_panel()
        # Should not raise when panel not shown
        panel.update_status("test")

    def test_append_stream_text_when_no_view(self, _mock_appkit):
        panel = self._make_panel()
        # Should not raise when panel not shown
        panel.append_stream_text("test")

    def test_clear_stream_text_when_no_view(self, _mock_appkit):
        panel = self._make_panel()
        # Should not raise when panel not shown
        panel.clear_stream_text()
