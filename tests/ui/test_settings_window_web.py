"""Tests for the WebView-based settings panel."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from tests.conftest import mock_panel_close_delegate


@pytest.fixture(autouse=True)
def _mock_appkit(mock_appkit_modules, monkeypatch):
    """Mock AppKit, Foundation, and WebKit modules for headless testing."""
    mock_webkit = MagicMock()
    monkeypatch.setitem(sys.modules, "WebKit", mock_webkit)

    import wenzi.ui.settings_window_web as _sw

    _sw._PanelCloseDelegate = None
    mock_panel_close_delegate(monkeypatch, _sw)

    # Mock message handler class
    mock_handler_cls = MagicMock()
    mock_handler_instance = MagicMock()
    mock_handler_cls.alloc.return_value.init.return_value = mock_handler_instance
    monkeypatch.setattr(_sw, "_get_message_handler_class", lambda: mock_handler_cls)

    return mock_appkit_modules


def _make_state():
    """Create a minimal settings state dict for testing."""
    return {
        "language": "auto",
        "hotkeys": {"fn": True, "right_command": False},
        "sound_enabled": True,
        "visual_indicator": True,
        "preview": True,
        "current_preset_id": "funasr-paraformer",
        "current_remote_asr": None,
        "stt_presets": [
            ("funasr-paraformer", "FunASR Paraformer", True),
            ("apple-speech", "Apple Speech", True),
        ],
        "stt_remote_models": [],
        "llm_models": [
            ("ollama", "qwen2.5:7b", "ollama / qwen2.5:7b"),
        ],
        "current_llm": ("ollama", "qwen2.5:7b"),
        "enhance_modes": [
            ("proofread", "Proofread", 10),
            ("format", "Format", 30),
        ],
        "current_enhance_mode": "proofread",
        "model_timeout": 10,
        "thinking": False,
        "vocab_enabled": True,
        "vocab_count": 42,
        "auto_build": True,
        "history_enabled": False,
        "history_max_entries": 100,
        "history_refresh_threshold": 50,
        "input_context_level": "basic",
        "config_dir": "/tmp/test-config",
        "scripting_enabled": False,
        "launcher": {
            "enabled": True,
            "hotkey": {"key": "space", "modifiers": ["option"]},
            "sources": {},
        },
        "last_tab": "general",
    }


def _make_callbacks():
    """Create a dict of mock callbacks matching SettingsController."""
    names = [
        "on_hotkey_toggle", "on_hotkey_mode_select", "on_hotkey_delete",
        "on_record_hotkey", "on_restart_key_select", "on_cancel_key_select",
        "on_scripting_toggle", "on_sound_toggle", "on_visual_toggle",
        "on_device_name_toggle", "on_preview_toggle",
        "on_stt_select", "on_stt_remote_select",
        "on_stt_add_provider", "on_stt_remove_provider",
        "on_llm_select", "on_llm_add_provider", "on_llm_remove_provider",
        "on_model_timeout",
        "on_enhance_mode_select", "on_enhance_mode_edit", "on_enhance_add_mode",
        "on_thinking_toggle", "on_vocab_toggle", "on_auto_build_toggle",
        "on_history_toggle", "on_history_max_entries",
        "on_history_refresh_threshold", "on_input_context_change",
        "on_vocab_build_model_select", "on_vocab_build",
        "on_tab_change", "on_reveal_config_folder",
        "on_config_dir_browse", "on_config_dir_reset",
        "on_launcher_toggle", "on_launcher_hotkey_record",
        "on_launcher_hotkey_clear", "on_launcher_source_toggle",
        "on_launcher_prefix_change", "on_launcher_usage_learning_toggle",
        "on_launcher_switch_english_toggle", "on_launcher_refresh_icons",
        "on_launcher_source_hotkey_record", "on_launcher_source_hotkey_clear",
        "on_new_snippet_hotkey_record", "on_new_snippet_hotkey_clear",
        "on_language_change", "_reopen",
    ]
    return {name: MagicMock(name=name) for name in names}


class TestSettingsWebPanelInit:
    def test_init_defaults(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        assert panel._panel is None
        assert panel._webview is None
        assert not panel.is_visible

    def test_show_creates_panel(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        panel.show(_make_state(), _make_callbacks())
        assert panel._panel is not None
        assert panel._webview is not None

    def test_show_stores_callbacks(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        callbacks = _make_callbacks()
        panel.show(_make_state(), callbacks)
        assert panel._callbacks is callbacks

    def test_close_clears_delegate(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        panel.show(_make_state(), _make_callbacks())
        panel.close()
        assert panel._close_delegate is None

    def test_is_visible_after_show(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        panel.show(_make_state(), _make_callbacks())
        # Mock panel.isVisible() returns MagicMock (truthy)
        assert panel.is_visible

    def test_close_then_reopen(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        panel.show(_make_state(), _make_callbacks())
        panel.close()
        assert panel._panel is None
        # Reopen should work
        panel.show(_make_state(), _make_callbacks())
        assert panel._panel is not None

    def test_message_after_close_ignored(self):
        from wenzi.ui.settings_window_web import SettingsWebPanel

        panel = SettingsWebPanel()
        cbs = _make_callbacks()
        panel.show(_make_state(), cbs)
        panel.close()
        # Should not raise or call callback
        panel._handle_js_message({"type": "callback", "name": "on_sound_toggle", "args": [True]})
        cbs["on_sound_toggle"].assert_not_called()
