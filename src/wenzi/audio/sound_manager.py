"""Sound feedback manager for WenZi recording events."""

from __future__ import annotations

import logging
import os

from wenzi.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

# Bundled default sound shipped with the package
BUNDLED_SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")
DEFAULT_START_SOUND = "start_default.wav"

# User-custom sound in ~/.config/WenZi/sounds/
USER_SOUNDS_DIR = os.path.join(DEFAULT_CONFIG_DIR, "sounds")
CUSTOM_START_SOUND = "start_custom.wav"


def _resolve_start_sound(config_dir: str | None = None) -> str:
    """Return the path to the start sound file.

    Priority:
    1. User-custom sound: ~/.config/WenZi/sounds/start_custom.wav
    2. Bundled default:   <package>/sounds/start_default.wav
    """
    if config_dir:
        user_dir = os.path.join(config_dir, "sounds")
    else:
        user_dir = USER_SOUNDS_DIR
    user_dir = os.path.expanduser(user_dir)

    custom_path = os.path.join(user_dir, CUSTOM_START_SOUND)
    if os.path.exists(custom_path):
        logger.debug("Using custom start sound: %s", custom_path)
        return custom_path

    bundled_path = os.path.join(BUNDLED_SOUNDS_DIR, DEFAULT_START_SOUND)
    logger.debug("Using bundled start sound: %s", bundled_path)
    return bundled_path


class SoundManager:
    """Play sound feedback for recording events."""

    def __init__(
        self,
        enabled: bool = True,
        volume: float = 0.4,
        config_dir: str | None = None,
    ) -> None:
        self._enabled = enabled
        self._volume = volume
        self._start_sound_path = _resolve_start_sound(config_dir)
        self._cached_sound: object = None  # Cached NSSound instance

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def warmup(self) -> None:
        """Pre-load the NSSound object on the main thread.

        Call via AppHelper.callAfter() after the event loop starts to
        eliminate first-play latency.
        """
        if self._cached_sound is not None:
            return
        try:
            from AppKit import NSSound

            if not os.path.exists(self._start_sound_path):
                return
            sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                self._start_sound_path, True
            )
            if sound is not None:
                sound.setVolume_(self._volume)
                self._cached_sound = sound
                logger.debug("NSSound pre-loaded: %s", self._start_sound_path)
        except Exception as e:
            logger.debug("NSSound warmup failed: %s", e)

    def play(self, event: str) -> None:
        """Play the sound for the given event. Only 'start' is supported."""
        if not self._enabled:
            return

        if event != "start":
            return

        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._play_on_main_thread)
        except Exception as e:
            logger.warning("Failed to schedule sound playback: %s", e)

    def _play_on_main_thread(self) -> None:
        """Actually play the sound file. Must be called on the main thread."""
        try:
            if self._cached_sound is not None:
                # Stop any ongoing playback and replay from the beginning
                self._cached_sound.stop()
                self._cached_sound.play()
                return

            # Fallback: load on demand if warmup was not called
            from AppKit import NSSound

            if not os.path.exists(self._start_sound_path):
                logger.warning("Sound file not found: %s", self._start_sound_path)
                return

            sound = NSSound.alloc().initWithContentsOfFile_byReference_(
                self._start_sound_path, True
            )
            if sound is None:
                logger.warning("Failed to load sound: %s", self._start_sound_path)
                return
            sound.setVolume_(self._volume)
            sound.play()
            self._cached_sound = sound
        except Exception as e:
            logger.warning("Failed to play sound: %s", e)
