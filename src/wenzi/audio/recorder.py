"""Audio recording using AVAudioEngine (macOS AVFoundation)."""

from __future__ import annotations

import array
import io
import logging
import queue
import struct
import threading
import time
import wave

from AVFoundation import AVAudioEngine, AVCaptureDevice, AVMediaTypeAudio
from Foundation import NSNotificationCenter

logger = logging.getLogger(__name__)

# Notification name (string constant; not always in the PyObjC bindings).
_ENGINE_CONFIG_CHANGE = "AVAudioEngineConfigurationChangeNotification"


def list_input_devices() -> list[dict]:
    """Return a list of available audio input devices.

    Each dict has keys: ``uid`` (str) and ``name`` (str).
    The ``uid`` is stable across reboots and suitable for config storage.
    """
    try:
        devices = AVCaptureDevice.devicesWithMediaType_(AVMediaTypeAudio)
    except Exception:
        logger.warning("Failed to enumerate audio devices", exc_info=True)
        return []
    result: list[dict] = []
    for d in devices:
        uid = str(d.uniqueID())
        name = str(d.localizedName())
        if uid and name:
            result.append({"uid": uid, "name": name})
    return result


def default_input_device_name() -> str | None:
    """Return the localized name of the current system default input device."""
    try:
        d = AVCaptureDevice.defaultDeviceWithMediaType_(AVMediaTypeAudio)
        return str(d.localizedName()) if d else None
    except Exception:
        return None


def _resolve_device_id(uid: str) -> int | None:
    """Find the CoreAudio AudioDeviceID for an AVCaptureDevice UID.

    AVAudioEngine's input node uses CoreAudio device IDs internally.
    We bridge from AVCaptureDevice UID → AudioDeviceID via the
    ``transportType`` + private ``_audioDeviceID`` selector, falling
    back to a CoreAudio property lookup.
    """
    import ctypes
    import ctypes.util

    _ca = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio"))

    # AudioObjectPropertyAddress
    class _Addr(ctypes.Structure):
        _fields_ = [
            ("mSelector", ctypes.c_uint32),
            ("mScope", ctypes.c_uint32),
            ("mElement", ctypes.c_uint32),
        ]

    _ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
    _ca.AudioObjectGetPropertyDataSize.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Addr),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
    ]
    _ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
    _ca.AudioObjectGetPropertyData.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Addr),
        ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]

    _cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    _cf.CFStringGetLength.restype = ctypes.c_long
    _cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
    _cf.CFStringGetCString.restype = ctypes.c_bool
    _cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
    ]
    _cf.CFRelease.restype = None
    _cf.CFRelease.argtypes = [ctypes.c_void_p]

    kSys = 1  # kAudioObjectSystemObject
    kDevs = 0x64657623  # 'dev#'
    kUID = 0x75696420  # 'uid '
    kGlob = 0x676C6F62  # 'glob'
    kUTF8 = 0x08000100

    # Get all device IDs
    addr = _Addr(kDevs, kGlob, 0)
    size = ctypes.c_uint32(0)
    if _ca.AudioObjectGetPropertyDataSize(kSys, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
        return None
    n = size.value // 4
    ids = (ctypes.c_uint32 * n)()
    if _ca.AudioObjectGetPropertyData(kSys, ctypes.byref(addr), 0, None, ctypes.byref(size), ids) != 0:
        return None

    # Match UID
    for did in ids:
        addr2 = _Addr(kUID, kGlob, 0)
        sz = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        cf_str = ctypes.c_void_p()
        if _ca.AudioObjectGetPropertyData(did, ctypes.byref(addr2), 0, None, ctypes.byref(sz), ctypes.byref(cf_str)) != 0:
            continue
        if not cf_str.value:
            continue
        try:
            length = _cf.CFStringGetLength(cf_str) * 4 + 1
            buf = ctypes.create_string_buffer(length)
            if _cf.CFStringGetCString(cf_str, buf, length, kUTF8):
                if buf.value.decode("utf-8") == uid:
                    return int(did)
        finally:
            _cf.CFRelease(cf_str)
    return None


class Recorder:
    """Record audio from the microphone using AVAudioEngine. Thread-safe start/stop."""

    # RMS threshold for silence detection (int16 range: 0-32768).
    # Typical quiet room noise is ~100-300, speech is ~1000+.
    DEFAULT_SILENCE_RMS = 20
    # Reference RMS for normalizing current_level to 0.0-1.0 range.
    # Normal speech (~1000-3000 RMS) maps to roughly 0.5-1.0.
    _LEVEL_REFERENCE_RMS = 800.0
    # Max seconds _starting may remain True before it is considered stuck
    # and forcibly reset, allowing a new start() to proceed.
    _STARTING_STALE_SECS = 10.0

    def __init__(
        self,
        sample_rate: int = 16000,
        block_ms: int = 20,
        device: str | None = None,
        max_session_bytes: int = 20 * 1024 * 1024,
        silence_rms: int = DEFAULT_SILENCE_RMS,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_ms = block_ms
        self.device = device
        self.max_session_bytes = max_session_bytes
        self.silence_rms = silence_rms

        self._queue: queue.Queue[bytes] = queue.Queue()
        self._engine: AVAudioEngine | None = None
        self._hw_sample_rate: float = 0.0
        self._resample_ratio: float = 0.0
        self._lock = threading.Lock()
        self._recording = False
        # Non-None while start() is in progress (value = monotonic timestamp).
        self._starting_since: float | None = None
        self._total_bytes = 0
        self._current_rms: float = 0.0
        self._on_audio_chunk: callable | None = None
        self._last_device_name: str | None = None
        self._query_device_name_enabled: bool = True
        self._config_observer = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def last_device_name(self) -> str | None:
        """Return the last known input device name, or None."""
        return self._last_device_name

    @property
    def current_level(self) -> float:
        """Return current audio level normalized to 0.0-1.0.

        Uses ``_LEVEL_REFERENCE_RMS`` (800) as reference so normal
        speech (~1000-3000 RMS) maps to roughly 0.5-1.0.
        """
        return min(1.0, self._current_rms / self._LEVEL_REFERENCE_RMS)

    def start(self) -> str | None:
        """Start recording. Returns the input device name, or None.

        Engine creation happens **outside** the lock so that a hung
        AVFoundation call cannot deadlock subsequent ``stop()`` /
        ``is_recording`` calls.  ``_starting_since`` prevents
        concurrent ``start()`` calls from racing.
        """
        # --- Phase 1: claim the "starting" slot (lock held briefly) -----
        with self._lock:
            if self._recording:
                return self._last_device_name
            if self._starting_since is not None:
                elapsed = time.monotonic() - self._starting_since
                if elapsed > self._STARTING_STALE_SECS:
                    logger.warning(
                        "Previous start() appears stuck (%.0fs), resetting",
                        elapsed,
                    )
                    self._starting_since = None
                else:
                    return self._last_device_name
            self._starting_since = time.monotonic()
            self._flush()
            self._total_bytes = 0

        # --- Phase 2: create AVAudioEngine and audio graph (lock free) --
        try:
            engine = AVAudioEngine.alloc().init()
            input_node = engine.inputNode()

            # Set input device if specified
            if self.device is not None:
                dev_id = _resolve_device_id(self.device)
                if dev_id is not None:
                    try:
                        au = input_node.AUAudioUnit()
                        au.setDeviceID_error_(dev_id, None)
                        logger.info("Set input device to uid=%s (id=%d)", self.device, dev_id)
                    except Exception:
                        logger.warning(
                            "Failed to set device uid=%s, using system default",
                            self.device,
                            exc_info=True,
                        )
                else:
                    logger.warning(
                        "Device uid=%s not found, using system default", self.device
                    )
            hw_fmt = input_node.outputFormatForBus_(0)
            self._hw_sample_rate = hw_fmt.sampleRate()
            self._resample_ratio = self._hw_sample_rate / self.sample_rate

            # Install tap on input node at its native format;
            # resampling to self.sample_rate happens in _tap_callback.
            def tap_block(buf, when):
                self._tap_callback(buf)

            input_node.installTapOnBus_bufferSize_format_block_(
                0,
                int(self._hw_sample_rate * self.block_ms / 1000),
                hw_fmt,
                tap_block,
            )

            engine.prepare()
            ok, err = engine.startAndReturnError_(None)
            if not ok:
                logger.error("AVAudioEngine start failed: %s", err)
                input_node.removeTapOnBus_(0)
                with self._lock:
                    self._starting_since = None
                return None

        except Exception:
            logger.error("Failed to create audio engine", exc_info=True)
            with self._lock:
                self._starting_since = None
            return None

        # --- Phase 3: device name query ---------------------------------
        device_name: str | None = None
        if self._query_device_name_enabled:
            device_name = self._query_device_name()

        # --- Phase 4: register for config change notifications ----------
        observer = (
            NSNotificationCenter.defaultCenter()
            .addObserverForName_object_queue_usingBlock_(
                _ENGINE_CONFIG_CHANGE,
                engine,
                None,
                lambda note: self._on_config_change(),
            )
        )

        # --- Phase 5: commit (lock held briefly) ------------------------
        with self._lock:
            self._engine = engine
            self._recording = True
            self._starting_since = None
            self._last_device_name = device_name
            self._config_observer = observer
            logger.info(
                "Recording started (sr=%d, hw=%.0f Hz, device=%s)",
                self.sample_rate,
                self._hw_sample_rate,
                device_name or "unknown",
            )
            return device_name

    def stop(self) -> bytes | None:
        """Stop recording and return WAV data as bytes, or None if nothing recorded."""
        with self._lock:
            if not self._recording:
                return None

            self._recording = False
            self._current_rms = 0.0
            engine = self._engine
            self._engine = None
            observer = self._config_observer
            self._config_observer = None

        # Break circular references
        self.clear_on_audio_chunk()

        # Stop engine and remove tap
        if engine is not None:
            try:
                engine.inputNode().removeTapOnBus_(0)
            except Exception as e:
                logger.warning("Error removing tap: %s", e)
            engine.stop()

        # Remove notification observer
        if observer is not None:
            NSNotificationCenter.defaultCenter().removeObserver_(observer)

        # Collect all buffered frames
        frames: list[bytes] = []
        while not self._queue.empty():
            try:
                frames.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not frames:
            logger.warning("No audio frames captured")
            self._flush()
            return None

        audio_bytes = b"".join(frames)
        n_samples = len(audio_bytes) // 2
        duration = n_samples / self.sample_rate
        rms = _rms_int16(audio_bytes)
        logger.info(
            "Recording stopped, captured %d samples (%.1fs), RMS=%d",
            n_samples,
            duration,
            rms,
        )

        if rms < self.silence_rms:
            logger.warning(
                "Audio below silence threshold (RMS=%d < %d), discarding",
                rms,
                self.silence_rms,
            )
            self._flush()
            return None

        # Encode as WAV in memory
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_bytes)
        return buf.getvalue()

    def set_on_audio_chunk(self, cb: callable) -> None:
        """Set a callback invoked with each audio chunk (bytes, raw int16 PCM)."""
        self._on_audio_chunk = cb

    def clear_on_audio_chunk(self) -> None:
        """Remove the audio chunk callback."""
        self._on_audio_chunk = None

    def _tap_callback(self, buffer) -> None:
        """Process audio from the AVAudioEngine tap.

        Called on a real-time audio thread.  Exceptions MUST be caught
        because an unhandled exception propagates through PyObjC and
        crashes the process.
        """
        try:
            if not self._recording:
                return

            in_frames = buffer.frameLength()
            if in_frames == 0:
                return

            # Read float32 samples from the native-rate input buffer
            channel0 = buffer.floatChannelData()[0]
            raw = bytes(channel0.as_buffer(in_frames))
            floats = struct.unpack(f"<{in_frames}f", raw)

            # Resample to target rate via linear interpolation
            ratio = self._resample_ratio
            out_count = int(in_frames / ratio)
            resampled = _resample_linear(floats, in_frames, out_count, ratio)

            # RMS from float32 data
            if out_count > 0:
                sum_sq = sum(s * s for s in resampled)
                self._current_rms = (sum_sq / out_count) ** 0.5 * 32768

            # Convert float32 → int16 bytes
            int16_data = struct.pack(
                f"<{out_count}h",
                *(max(-32768, min(32767, int(s * 32768))) for s in resampled),
            )

            byte_len = len(int16_data)
            if self._total_bytes + byte_len > self.max_session_bytes:
                logger.warning("Max session size reached, dropping frames")
                return

            self._total_bytes += byte_len
            try:
                self._queue.put_nowait(int16_data)
            except queue.Full:
                logger.warning("Audio queue full, dropping frame")

            cb = self._on_audio_chunk
            if cb is not None:
                try:
                    cb(int16_data)
                except Exception:
                    logger.debug("Audio chunk callback error", exc_info=True)

        except Exception:
            logger.debug("Tap callback error", exc_info=True)

    def mark_tainted(self) -> None:
        """No-op. Kept for backward compatibility with RecordingFlow."""

    def _on_config_change(self) -> None:
        """Handle AVAudioEngine configuration change (device added/removed)."""
        logger.info("Audio engine configuration changed")
        # If not recording, nothing to do — next start() creates a fresh engine.
        # If recording, the engine has already stopped; we cannot seamlessly
        # restart mid-session without losing audio.  Log it and let the
        # current session end naturally when stop() is called.
        if self._recording:
            logger.warning(
                "Audio configuration changed during recording; "
                "current session may have gaps"
            )

    def _query_device_name(self) -> str | None:
        """Return the name of the current input device, or None."""
        if self.device:
            for d in list_input_devices():
                if d["uid"] == self.device:
                    return d["name"]
        return default_input_device_name()

    def _flush(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


def _rms_int16(data: bytes) -> int:
    """Compute RMS of raw int16 PCM bytes."""
    n = len(data) // 2
    if n == 0:
        return 0
    arr = array.array("h", data)
    sum_sq = sum(s * s for s in arr)
    return int((sum_sq / n) ** 0.5)


def _resample_linear(
    samples: tuple[float, ...],
    in_count: int,
    out_count: int,
    ratio: float,
) -> list[float]:
    """Resample float32 audio via linear interpolation.

    Works for any sample-rate ratio (integer or fractional).
    """
    if out_count == 0 or in_count == 0:
        return []
    last = in_count - 1
    result: list[float] = []
    for i in range(out_count):
        src = i * ratio
        idx = int(src)
        if idx >= last:
            result.append(samples[last])
        else:
            frac = src - idx
            result.append(samples[idx] + (samples[idx + 1] - samples[idx]) * frac)
    return result
