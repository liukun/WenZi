"""Tests for voice input setup flow (Siri unavailable / no fallback)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from wenzi.transcription.apple import (
    SIRI_SETUP_DONT_ASK,
    SIRI_SETUP_LATER,
    SIRI_SETUP_OPEN_SETTINGS,
)


class TestSiriSetupConstants:
    """Verify Siri setup dialog return value constants."""

    def test_open_settings(self):
        assert SIRI_SETUP_OPEN_SETTINGS == "open_settings"

    def test_later(self):
        assert SIRI_SETUP_LATER == "later"

    def test_dont_ask(self):
        assert SIRI_SETUP_DONT_ASK == "dont_ask"


class TestHandleNoVoiceBackend:
    """Tests for WenZiApp._handle_no_voice_backend."""

    def _make_app(self):
        app = MagicMock()
        app._config = {"asr": {}}
        app._config_path = "/tmp/config.json"
        app._voice_input_available = True
        app._hotkey_listener = MagicMock()
        return app

    def test_previously_disabled_skips_prompt(self):
        """If voice_input_disabled is already set, skip dialog."""
        from wenzi.app import WenZiApp

        app = self._make_app()
        app._config["asr"]["voice_input_disabled"] = True

        with patch("wenzi.app.save_config"):
            WenZiApp._handle_no_voice_backend(app)

        assert app._voice_input_available is False
        assert app._set_status.call_args[0][0] == "WZ"

    def test_user_chooses_open_settings(self):
        """Open Settings: opens URL, voice input disabled, hotkeys stay."""
        from wenzi.app import WenZiApp

        app = self._make_app()

        with patch(
            "wenzi.transcription.apple.prompt_siri_setup",
            return_value=SIRI_SETUP_OPEN_SETTINGS,
        ), patch("subprocess.Popen") as mock_popen, \
             patch("wenzi.app.save_config"):
            WenZiApp._handle_no_voice_backend(app)

        mock_popen.assert_called_once()
        assert app._voice_input_available is False
        assert app._set_status.call_args[0][0] == "WZ"

    def test_user_chooses_later(self):
        """Set Up Later: voice input disabled, hotkeys stay, no save."""
        from wenzi.app import WenZiApp

        app = self._make_app()

        with patch(
            "wenzi.transcription.apple.prompt_siri_setup",
            return_value=SIRI_SETUP_LATER,
        ), patch("wenzi.app.save_config") as mock_save:
            WenZiApp._handle_no_voice_backend(app)

        mock_save.assert_not_called()
        assert app._voice_input_available is False
        assert "voice_input_disabled" not in app._config["asr"]

    def test_user_chooses_dont_ask(self):
        """Don't Ask Again: persists preference, stops hotkeys."""
        from wenzi.app import WenZiApp

        app = self._make_app()

        with patch(
            "wenzi.transcription.apple.prompt_siri_setup",
            return_value=SIRI_SETUP_DONT_ASK,
        ), patch("wenzi.app.save_config") as mock_save:
            WenZiApp._handle_no_voice_backend(app)

        assert app._config["asr"]["voice_input_disabled"] is True
        mock_save.assert_called_once()
        assert app._voice_input_available is False


class TestTryEnableVoiceInput:
    """Tests for RecordingController._try_enable_voice_input."""

    def test_init_succeeds_enables_voice(self):
        """If initialize() succeeds, voice input becomes available."""
        from wenzi.controllers.recording_controller import RecordingController

        app = MagicMock()
        app._voice_input_available = False
        app._transcriber.initialize.return_value = None
        ctrl = RecordingController(app)

        with patch("threading.Thread") as mock_thread:
            ctrl._try_enable_voice_input()
            target = mock_thread.call_args[1].get("target") or mock_thread.call_args[0][0]
            if callable(target):
                target()

        app._transcriber.initialize.assert_called_once()
        assert app._voice_input_available is True

    def test_init_fails_prompts_siri(self):
        """If initialize() fails, show Siri prompt."""
        from wenzi.controllers.recording_controller import RecordingController

        app = MagicMock()
        app._voice_input_available = False
        app._transcriber.initialize.side_effect = RuntimeError("Siri disabled")
        ctrl = RecordingController(app)

        with patch("threading.Thread") as mock_thread, \
             patch(
                 "wenzi.transcription.apple.prompt_enable_siri"
             ) as mock_prompt:
            ctrl._try_enable_voice_input()
            target = mock_thread.call_args[1].get("target") or mock_thread.call_args[0][0]
            if callable(target):
                target()

        mock_prompt.assert_called_once()
        assert app._voice_input_available is False


class TestHotkeyPressVoiceCheck:
    """Tests for the voice input check in on_hotkey_press."""

    def test_hotkey_press_skips_when_voice_unavailable(self):
        """Hotkey press should not start recording when voice is unavailable."""
        from wenzi.controllers.recording_controller import RecordingController

        app = MagicMock()
        app._config_degraded = False
        app._voice_input_available = False
        ctrl = RecordingController(app)

        with patch.object(ctrl, "_try_enable_voice_input") as mock_try:
            ctrl.on_hotkey_press("fn")
            mock_try.assert_called_once()

        # Should NOT have proceeded to recording
        app._set_status.assert_not_called()

    def test_hotkey_press_proceeds_when_voice_available(self):
        """Hotkey press should start recording when voice is available."""
        from wenzi.controllers.recording_controller import RecordingController

        app = MagicMock()
        app._config_degraded = False
        app._voice_input_available = True
        app._busy = False
        app._config = {"hotkeys": {"fn": True}}
        ctrl = RecordingController(app)

        with patch.object(ctrl, "_start_recording_and_update_indicator"):
            ctrl.on_hotkey_press("fn")

        # Should have proceeded to recording status
        app._set_status.assert_called()
