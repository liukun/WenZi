"""Tests for SoundManager."""

import os
from unittest.mock import MagicMock, patch

from wenzi.audio.sound_manager import (
    BUNDLED_SOUNDS_DIR,
    CUSTOM_START_SOUND,
    DEFAULT_START_SOUND,
    SoundManager,
    _resolve_start_sound,
)


class TestResolveStartSound:
    def test_returns_bundled_when_no_custom(self, tmp_path):
        """When no custom sound exists, return the bundled default."""
        config_dir = str(tmp_path / "config")
        path = _resolve_start_sound(config_dir)
        expected = os.path.join(BUNDLED_SOUNDS_DIR, DEFAULT_START_SOUND)
        assert path == expected

    def test_returns_custom_when_exists(self, tmp_path):
        """When user has a custom sound, prefer it over bundled."""
        config_dir = str(tmp_path / "config")
        sounds_dir = os.path.join(config_dir, "sounds")
        os.makedirs(sounds_dir)
        custom_path = os.path.join(sounds_dir, CUSTOM_START_SOUND)
        with open(custom_path, "wb") as f:
            f.write(b"custom sound data")

        path = _resolve_start_sound(config_dir)
        assert path == custom_path

    def test_bundled_sound_file_exists(self):
        """The bundled start_default.wav must be present in the package."""
        bundled_path = os.path.join(BUNDLED_SOUNDS_DIR, DEFAULT_START_SOUND)
        assert os.path.exists(bundled_path), (
            f"Bundled sound file missing: {bundled_path}"
        )


class TestSoundManagerInit:
    def test_default_enabled(self):
        sm = SoundManager()
        assert sm.enabled is True

    def test_custom_disabled(self):
        sm = SoundManager(enabled=False)
        assert sm.enabled is False


class TestSoundManagerEnabled:
    def test_toggle_enabled(self):
        sm = SoundManager(enabled=True)
        sm.enabled = False
        assert sm.enabled is False
        sm.enabled = True
        assert sm.enabled is True


class TestSoundManagerPlay:
    @patch("wenzi.audio.sound_manager.SoundManager._play_on_main_thread")
    def test_play_when_disabled_does_nothing(self, mock_play):
        sm = SoundManager(enabled=False)
        sm.play("start")
        mock_play.assert_not_called()

    @patch("wenzi.audio.sound_manager.SoundManager._play_on_main_thread")
    def test_play_stop_event_does_nothing(self, mock_play):
        sm = SoundManager(enabled=True)
        sm.play("stop")
        mock_play.assert_not_called()

    @patch("wenzi.audio.sound_manager.SoundManager._play_on_main_thread")
    def test_play_unknown_event_does_nothing(self, mock_play):
        sm = SoundManager(enabled=True)
        sm.play("unknown_event")
        mock_play.assert_not_called()

    def test_play_on_main_thread_no_cache_file_not_found(self):
        sm = SoundManager(enabled=True)
        sm._start_sound_path = "/nonexistent/path.wav"
        # Should not raise when no cached sound and file missing
        sm._play_on_main_thread()

    def test_play_on_main_thread_fallback_loads_and_caches(self, tmp_path):
        dummy = tmp_path / "test.wav"
        dummy.write_bytes(b"fake")

        mock_sound_instance = MagicMock()
        mock_nssound = MagicMock()
        mock_nssound.alloc.return_value.initWithContentsOfFile_byReference_.return_value = (
            mock_sound_instance
        )

        mock_appkit = MagicMock()
        mock_appkit.NSSound = mock_nssound

        sm = SoundManager(enabled=True, volume=0.5)
        sm._start_sound_path = str(dummy)
        with patch.dict("sys.modules", {"AppKit": mock_appkit}):
            sm._play_on_main_thread()

        mock_nssound.alloc.return_value.initWithContentsOfFile_byReference_.assert_called_with(
            str(dummy), True
        )
        mock_sound_instance.setVolume_.assert_called_with(0.5)
        mock_sound_instance.play.assert_called_once()
        # Sound should be cached after first play
        assert sm._cached_sound is mock_sound_instance

    def test_play_on_main_thread_uses_cached_sound(self):
        mock_cached = MagicMock()
        sm = SoundManager(enabled=True, volume=0.5)
        sm._cached_sound = mock_cached

        sm._play_on_main_thread()

        mock_cached.stop.assert_called_once()
        mock_cached.play.assert_called_once()

    def test_warmup_caches_nssound(self, tmp_path):
        dummy = tmp_path / "test.wav"
        dummy.write_bytes(b"fake")

        mock_sound_instance = MagicMock()
        mock_nssound = MagicMock()
        mock_nssound.alloc.return_value.initWithContentsOfFile_byReference_.return_value = (
            mock_sound_instance
        )

        mock_appkit = MagicMock()
        mock_appkit.NSSound = mock_nssound

        sm = SoundManager(enabled=True, volume=0.5)
        sm._start_sound_path = str(dummy)
        with patch.dict("sys.modules", {"AppKit": mock_appkit}):
            sm.warmup()

        assert sm._cached_sound is mock_sound_instance
        mock_sound_instance.setVolume_.assert_called_with(0.5)

    def test_warmup_skips_if_already_cached(self):
        sm = SoundManager(enabled=True)
        existing = MagicMock()
        sm._cached_sound = existing
        sm.warmup()
        # Should not replace existing cache
        assert sm._cached_sound is existing
