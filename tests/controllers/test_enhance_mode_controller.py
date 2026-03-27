"""Tests for EnhanceModeController."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wenzi.controllers.enhance_mode_controller import EnhanceModeController


@pytest.fixture
def mock_app():
    """Create a minimal mock app for EnhanceModeController."""
    app = MagicMock(spec=[])
    app._config = {
        "ai_enhance": {"enabled": True, "mode": "proofread"},
        "output": {"preview": True},
    }
    app._config_path = "/tmp/test_config.json"
    app._config_dir = "/tmp"
    app._data_dir = "/tmp"
    app._cache_dir = "/tmp"
    app._enhancer = MagicMock()
    app._enhancer.thinking = False
    app._enhancer.history_enabled = False
    app._enhancer.provider_name = "openai"
    app._enhancer.model_name = "gpt-4o"
    app._enhance_mode = "proofread"
    app._enhance_menu_items = {}
    app._enhance_controller = MagicMock()
    app._enhance_history_item = MagicMock()
    app._enhance_thinking_item = MagicMock()
    app._menu_builder = MagicMock()
    app._preview_enabled = True
    app._current_status = "statusbar.status.ready"
    return app


@pytest.fixture
def ctrl(mock_app):
    return EnhanceModeController(mock_app)


class TestOnEnhanceModeSelect:
    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_selects_mode(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        sender._enhance_mode = "translate"
        mock_app._enhance_menu_items = {"proofread": MagicMock(), "translate": MagicMock()}

        ctrl.on_enhance_mode_select(sender)

        assert mock_app._enhance_mode == "translate"
        assert mock_app._enhance_menu_items["translate"].state == 1
        assert mock_app._enhance_menu_items["proofread"].state == 0
        mock_save.assert_called_once()

    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_selects_off(self, mock_save, ctrl, mock_app):
        from wenzi.enhance.enhancer import MODE_OFF

        sender = MagicMock()
        sender._enhance_mode = MODE_OFF
        mock_app._enhance_menu_items = {MODE_OFF: MagicMock()}

        ctrl.on_enhance_mode_select(sender)

        assert mock_app._enhancer._enabled is False


class TestOnEnhanceThinkingToggle:
    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_toggle_on(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        mock_app._enhancer.thinking = False

        ctrl.on_enhance_thinking_toggle(sender)

        assert mock_app._enhancer.thinking is True
        assert sender.state == 1
        mock_save.assert_called_once()

    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_toggle_off(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        mock_app._enhancer.thinking = True

        ctrl.on_enhance_thinking_toggle(sender)

        assert mock_app._enhancer.thinking is False
        assert sender.state == 0

    def test_no_enhancer(self, ctrl, mock_app):
        mock_app._enhancer = None
        sender = MagicMock()
        ctrl.on_enhance_thinking_toggle(sender)
        # Should not raise


class TestHistoryToggle:
    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_toggle_on(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        mock_app._enhancer.history_enabled = False

        ctrl.on_history_toggle(sender)

        assert mock_app._enhancer.history_enabled is True
        assert sender.state == 1
        mock_save.assert_called_once()

    def test_no_enhancer(self, ctrl, mock_app):
        mock_app._enhancer = None
        sender = MagicMock()
        ctrl.on_history_toggle(sender)


class TestPreviewToggle:
    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_toggle_off(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        mock_app._preview_enabled = True

        ctrl.on_preview_toggle(sender)

        assert mock_app._preview_enabled is False
        assert sender.state == 0
        mock_save.assert_called_once()

    @patch("wenzi.controllers.enhance_mode_controller.save_config")
    def test_toggle_on(self, mock_save, ctrl, mock_app):
        sender = MagicMock()
        mock_app._preview_enabled = False

        ctrl.on_preview_toggle(sender)

        assert mock_app._preview_enabled is True
        assert sender.state == 1


class TestAddModeTemplate:
    def test_template_exists(self):
        assert EnhanceModeController._ADD_MODE_TEMPLATE is not None
        assert "My New Mode" in EnhanceModeController._ADD_MODE_TEMPLATE
