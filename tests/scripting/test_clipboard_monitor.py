"""Tests for clipboard monitor."""

import json
import os

from unittest.mock import MagicMock, patch

from voicetext.scripting.clipboard_monitor import ClipboardEntry, ClipboardMonitor


class TestClipboardEntry:
    def test_defaults(self):
        entry = ClipboardEntry(text="hello")
        assert entry.text == "hello"
        assert entry.timestamp > 0
        assert entry.source_app == ""
        assert entry.image_path == ""
        assert entry.image_width == 0
        assert entry.image_height == 0
        assert entry.image_size == 0

    def test_with_all_fields(self):
        entry = ClipboardEntry(
            text="test", timestamp=1000.0, source_app="Safari"
        )
        assert entry.text == "test"
        assert entry.timestamp == 1000.0
        assert entry.source_app == "Safari"

    def test_image_entry(self):
        entry = ClipboardEntry(
            image_path="123_abc.png",
            image_width=1920,
            image_height=1080,
            image_size=500000,
            source_app="Safari",
        )
        assert entry.text == ""
        assert entry.image_path == "123_abc.png"
        assert entry.image_width == 1920
        assert entry.image_height == 1080
        assert entry.image_size == 500000


class TestClipboardMonitor:
    def test_add_entry(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello")
        assert len(monitor.entries) == 1
        assert monitor.entries[0].text == "hello"

    def test_add_entry_with_source_app(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello", source_app="Safari")
        assert monitor.entries[0].source_app == "Safari"

    def test_deduplication(self):
        """Consecutive identical texts should not create duplicate entries."""
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello")
        monitor._add_entry("hello")
        assert len(monitor.entries) == 1

    def test_different_texts_not_deduplicated(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello")
        monitor._add_entry("world")
        assert len(monitor.entries) == 2

    def test_expired_entries_trimmed(self):
        """Entries older than max_days should be removed on add."""
        import time as _time

        monitor = ClipboardMonitor(max_days=1)
        # Manually add an old entry (2 days ago)
        old_entry = ClipboardEntry(
            text="old", timestamp=_time.time() - 2 * 86400
        )
        monitor._entries.append(old_entry)

        # Adding a new entry should trim the expired one
        monitor._add_entry("new")
        assert len(monitor.entries) == 1
        assert monitor.entries[0].text == "new"

    def test_newest_first(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("first")
        monitor._add_entry("second")
        monitor._add_entry("third")
        assert monitor.entries[0].text == "third"
        assert monitor.entries[2].text == "first"

    def test_clear(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello")
        monitor.clear()
        assert len(monitor.entries) == 0

    def test_entries_returns_copy(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._add_entry("hello")
        entries = monitor.entries
        entries.clear()
        assert len(monitor.entries) == 1  # Original not affected

    def test_persistence_save_and_load(self, tmp_path):
        persist_path = str(tmp_path / "clipboard.json")

        # Create monitor and add entries
        monitor1 = ClipboardMonitor(max_days=7, persist_path=persist_path)
        monitor1._add_entry("first", source_app="Safari")
        monitor1._add_entry("second")

        # Verify file was written
        assert (tmp_path / "clipboard.json").exists()

        # Load in a new monitor
        monitor2 = ClipboardMonitor(max_days=7, persist_path=persist_path)
        assert len(monitor2.entries) == 2
        assert monitor2.entries[0].text == "second"
        assert monitor2.entries[1].text == "first"
        assert monitor2.entries[1].source_app == "Safari"

    def test_load_corrupt_file(self, tmp_path):
        persist_path = str(tmp_path / "clipboard.json")
        with open(persist_path, "w") as f:
            f.write("not json")

        monitor = ClipboardMonitor(max_days=7, persist_path=persist_path)
        assert len(monitor.entries) == 0

    def test_is_concealed(self):
        """Pasteboard with concealed type markers should be detected."""
        pb = MagicMock()
        pb.types.return_value = [
            "public.utf8-plain-text",
            "org.nspasteboard.ConcealedType",
        ]
        assert ClipboardMonitor._is_concealed(pb) is True

    def test_is_not_concealed(self):
        pb = MagicMock()
        pb.types.return_value = ["public.utf8-plain-text"]
        assert ClipboardMonitor._is_concealed(pb) is False

    def test_is_concealed_none_types(self):
        pb = MagicMock()
        pb.types.return_value = None
        assert ClipboardMonitor._is_concealed(pb) is False

    def test_start_stop(self):
        """Start and stop should not raise."""
        monitor = ClipboardMonitor(max_days=7, poll_interval=10.0)
        # Mock NSPasteboard to avoid actual clipboard access
        with patch("voicetext.scripting.clipboard_monitor.ClipboardMonitor._check_clipboard"):
            monitor.start()
            assert monitor._thread is not None
            assert monitor._thread.is_alive()
            monitor.stop()
            assert monitor._thread is None


class TestImageEntries:
    def _make_png_bytes(self):
        """Create minimal valid PNG bytes for testing."""
        # 1x1 red pixel PNG
        import struct
        import zlib

        def _chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw = b"\x00\xff\x00\x00"
        idat = _chunk(b"IDAT", zlib.compress(raw))
        iend = _chunk(b"IEND", b"")
        return sig + ihdr + idat + iend

    def test_add_image_entry_saves_file(self, tmp_path):
        image_dir = str(tmp_path / "images")
        monitor = ClipboardMonitor(max_days=7, image_dir=image_dir)

        # Mock _save_image to avoid AppKit dependency
        monitor._save_image = MagicMock(
            return_value=("test_123.png", 100, 50, 1234)
        )
        monitor._add_image_entry(b"fake_data", "png", source_app="Safari")

        assert len(monitor.entries) == 1
        entry = monitor.entries[0]
        assert entry.image_path == "test_123.png"
        assert entry.image_width == 100
        assert entry.image_height == 50
        assert entry.image_size == 1234
        assert entry.source_app == "Safari"
        assert entry.text == ""

    def test_image_deduplication(self, tmp_path):
        image_dir = str(tmp_path / "images")
        monitor = ClipboardMonitor(max_days=7, image_dir=image_dir)

        monitor._save_image = MagicMock(
            return_value=("same_file.png", 100, 50, 1234)
        )
        monitor._add_image_entry(b"data1", "png")
        monitor._add_image_entry(b"data2", "png")

        assert len(monitor.entries) == 1

    def test_expired_image_cleanup(self, tmp_path):
        """Expired image entries should have their files deleted."""
        import time as _time

        image_dir = str(tmp_path / "images")
        os.makedirs(image_dir, exist_ok=True)

        # Create a fake image file for the old entry
        with open(os.path.join(image_dir, "old_img.png"), "wb") as f:
            f.write(b"fake")

        monitor = ClipboardMonitor(max_days=1, image_dir=image_dir)

        # Manually add an expired image entry (2 days old)
        monitor._entries.append(
            ClipboardEntry(
                image_path="old_img.png",
                image_width=100,
                image_height=100,
                image_size=4,
                timestamp=_time.time() - 2 * 86400,
            )
        )

        # Adding a new entry should trim the expired one and delete its file
        monitor._add_entry("new text")

        assert len(monitor.entries) == 1
        assert monitor.entries[0].text == "new text"
        assert not os.path.exists(os.path.join(image_dir, "old_img.png"))

    def test_clear_removes_image_files(self, tmp_path):
        image_dir = str(tmp_path / "images")
        os.makedirs(image_dir, exist_ok=True)

        with open(os.path.join(image_dir, "test.png"), "wb") as f:
            f.write(b"fake")

        monitor = ClipboardMonitor(max_days=7, image_dir=image_dir)
        monitor._entries.append(
            ClipboardEntry(image_path="test.png", image_width=100, image_height=100)
        )

        monitor.clear()
        assert len(monitor.entries) == 0
        assert not os.path.exists(os.path.join(image_dir, "test.png"))

    def test_promote_image(self, tmp_path):
        monitor = ClipboardMonitor(max_days=7)
        monitor._entries = [
            ClipboardEntry(text="text1"),
            ClipboardEntry(image_path="img1.png", image_width=100, image_height=100),
            ClipboardEntry(text="text2"),
        ]

        monitor.promote_image("img1.png")
        assert monitor.entries[0].image_path == "img1.png"

    def test_promote_image_not_found(self):
        monitor = ClipboardMonitor(max_days=7)
        monitor._entries = [ClipboardEntry(text="text1")]
        monitor.promote_image("nonexistent.png")  # Should not raise

    def test_persistence_with_image_entries(self, tmp_path):
        persist_path = str(tmp_path / "clipboard.json")
        image_dir = str(tmp_path / "images")
        os.makedirs(image_dir, exist_ok=True)

        # Create the referenced image file
        with open(os.path.join(image_dir, "img1.png"), "wb") as f:
            f.write(b"fake png")

        monitor1 = ClipboardMonitor(
            max_days=7, persist_path=persist_path, image_dir=image_dir
        )
        with monitor1._lock:
            monitor1._entries = [
                ClipboardEntry(
                    image_path="img1.png",
                    image_width=1920,
                    image_height=1080,
                    image_size=500000,
                    source_app="Safari",
                ),
                ClipboardEntry(text="hello"),
            ]
        monitor1._save_to_disk()

        monitor2 = ClipboardMonitor(
            max_days=7, persist_path=persist_path, image_dir=image_dir
        )
        assert len(monitor2.entries) == 2
        assert monitor2.entries[0].image_path == "img1.png"
        assert monitor2.entries[0].image_width == 1920
        assert monitor2.entries[0].image_height == 1080
        assert monitor2.entries[0].image_size == 500000
        assert monitor2.entries[1].text == "hello"

    def test_load_drops_entries_with_missing_image_files(self, tmp_path):
        """Image entries whose files are gone should be filtered out on load."""
        import time as _time

        persist_path = str(tmp_path / "clipboard.json")
        image_dir = str(tmp_path / "images")
        os.makedirs(image_dir, exist_ok=True)

        # Only create one of two referenced image files
        with open(os.path.join(image_dir, "exists.png"), "wb") as f:
            f.write(b"fake png")

        recent_ts = _time.time() - 3600
        data = [
            {"image_path": "missing.png", "image_width": 100, "image_height": 50,
             "timestamp": recent_ts},
            {"text": "hello", "timestamp": recent_ts},
            {"image_path": "exists.png", "image_width": 200, "image_height": 100,
             "timestamp": recent_ts},
        ]
        with open(persist_path, "w") as f:
            json.dump(data, f)

        monitor = ClipboardMonitor(
            max_days=7, persist_path=persist_path, image_dir=image_dir
        )
        assert len(monitor.entries) == 2
        assert monitor.entries[0].text == "hello"
        assert monitor.entries[1].image_path == "exists.png"

    def test_load_trims_expired_entries(self, tmp_path):
        """Entries older than max_days should be removed on load."""
        import time as _time

        persist_path = str(tmp_path / "clipboard.json")
        image_dir = str(tmp_path / "images")
        os.makedirs(image_dir, exist_ok=True)
        with open(os.path.join(image_dir, "old.png"), "wb") as f:
            f.write(b"fake")

        recent_ts = _time.time() - 3600  # 1 hour ago
        old_ts = _time.time() - 10 * 86400  # 10 days ago
        data = [
            {"text": "recent", "timestamp": recent_ts},
            {"text": "old", "timestamp": old_ts},
            {"image_path": "old.png", "image_width": 100, "image_height": 50,
             "timestamp": old_ts},
        ]
        with open(persist_path, "w") as f:
            json.dump(data, f)

        monitor = ClipboardMonitor(
            max_days=7, persist_path=persist_path, image_dir=image_dir
        )
        assert len(monitor.entries) == 1
        assert monitor.entries[0].text == "recent"
        # Expired image file should be cleaned up
        assert not os.path.exists(os.path.join(image_dir, "old.png"))

    def test_load_old_format_backward_compatible(self, tmp_path):
        """Old JSON without image fields should load correctly."""
        import time as _time

        persist_path = str(tmp_path / "clipboard.json")
        recent_ts = _time.time() - 3600  # 1 hour ago (not expired)
        data = [
            {"text": "hello", "timestamp": recent_ts, "source_app": "Safari"},
            {"text": "world", "timestamp": recent_ts},
        ]
        with open(persist_path, "w") as f:
            json.dump(data, f)

        monitor = ClipboardMonitor(max_days=7, persist_path=persist_path)
        assert len(monitor.entries) == 2
        assert monitor.entries[0].image_path == ""
        assert monitor.entries[0].image_width == 0

    def test_save_image_returns_none_on_failure(self, tmp_path):
        image_dir = str(tmp_path / "images")
        monitor = ClipboardMonitor(max_days=7, image_dir=image_dir)
        # Invalid image data
        result = monitor._save_image(b"not an image", "png")
        assert result is None

    def test_add_image_entry_skips_on_save_failure(self, tmp_path):
        image_dir = str(tmp_path / "images")
        monitor = ClipboardMonitor(max_days=7, image_dir=image_dir)
        monitor._save_image = MagicMock(return_value=None)
        monitor._add_image_entry(b"bad", "png")
        assert len(monitor.entries) == 0
