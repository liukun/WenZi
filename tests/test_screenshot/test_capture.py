"""Tests for wenzi.screenshot.capture.

All ScreenCaptureKit and Quartz calls are mocked so these tests run headless
without macOS APIs.  The module is imported *after* the mocks are installed
via monkeypatch on sys.modules.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers to build fake CGWindowList entries
# ---------------------------------------------------------------------------

def _make_window(
    *,
    layer: int = 0,
    width: float = 200.0,
    height: float = 150.0,
    x: float = 0.0,
    y: float = 0.0,
    title: str = "Window",
    app: str = "App",
    window_id: int = 1,
) -> Dict[str, Any]:
    """Build a fake CGWindowInfo dict matching macOS key names."""
    return {
        "kCGWindowLayer": layer,
        "kCGWindowBounds": {"X": x, "Y": y, "Width": width, "Height": height},
        "kCGWindowName": title,
        "kCGWindowOwnerName": app,
        "kCGWindowNumber": window_id,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_quartz(monkeypatch):
    """Install a mock Quartz module before any test-local imports."""
    mock_quartz = MagicMock()
    mock_quartz.kCGWindowListOptionAll = 0
    mock_quartz.kCGNullWindowID = 0
    monkeypatch.setitem(sys.modules, "Quartz", mock_quartz)
    return mock_quartz


@pytest.fixture(autouse=True)
def _fresh_capture_module(monkeypatch):
    """Remove cached capture module so each test gets a fresh import."""
    monkeypatch.delitem(sys.modules, "wenzi.screenshot.capture", raising=False)
    monkeypatch.delitem(sys.modules, "wenzi.screenshot", raising=False)


# ---------------------------------------------------------------------------
# _collect_window_metadata tests
# ---------------------------------------------------------------------------

class TestCollectWindowMetadata:
    """Tests for window filtering and sorting logic."""

    def _run(self, windows: List[Dict[str, Any]], monkeypatch) -> List[Dict[str, Any]]:
        """Set up Quartz mock with *windows* and call _collect_window_metadata."""
        import Quartz
        Quartz.CGWindowListCopyWindowInfo.return_value = windows  # type: ignore[attr-defined]

        from wenzi.screenshot.capture import _collect_window_metadata
        return _collect_window_metadata()

    def test_visible_window_is_included(self, monkeypatch):
        win = _make_window(layer=0, width=300, height=200, title="Safari", app="Safari")
        result = self._run([win], monkeypatch)
        assert len(result) == 1
        assert result[0]["title"] == "Safari"
        assert result[0]["app"] == "Safari"
        assert result[0]["layer"] == 0
        assert result[0]["bounds"] == {"x": 0.0, "y": 0.0, "width": 300.0, "height": 200.0}

    def test_negative_layer_excluded(self, monkeypatch):
        """Windows with layer < 0 (background/desktop) must be filtered out."""
        win = _make_window(layer=-1, title="Desktop", app="Finder")
        result = self._run([win], monkeypatch)
        assert result == []

    def test_too_small_width_excluded(self, monkeypatch):
        win = _make_window(width=5, height=200, title="Tiny", app="App")
        result = self._run([win], monkeypatch)
        assert result == []

    def test_too_small_height_excluded(self, monkeypatch):
        win = _make_window(width=200, height=5, title="Thin", app="App")
        result = self._run([win], monkeypatch)
        assert result == []

    def test_exactly_minimum_size_included(self, monkeypatch):
        """Windows exactly 10×10 must NOT be filtered out."""
        win = _make_window(width=10, height=10, title="Tiny OK", app="App")
        result = self._run([win], monkeypatch)
        assert len(result) == 1

    def test_empty_title_and_app_excluded(self, monkeypatch):
        """Windows with both empty title and empty ownerName are excluded."""
        win = _make_window(title="", app="", layer=0, width=200, height=200)
        result = self._run([win], monkeypatch)
        assert result == []

    def test_empty_title_but_has_app_included(self, monkeypatch):
        """A window with no title but a valid app name must be kept."""
        win = _make_window(title="", app="Finder", layer=0, width=200, height=200)
        result = self._run([win], monkeypatch)
        assert len(result) == 1
        assert result[0]["app"] == "Finder"

    def test_has_title_but_empty_app_included(self, monkeypatch):
        win = _make_window(title="My Window", app="", layer=0, width=200, height=200)
        result = self._run([win], monkeypatch)
        assert len(result) == 1
        assert result[0]["title"] == "My Window"

    def test_none_title_treated_as_empty(self, monkeypatch):
        """kCGWindowName may be None (not set); treat as empty string."""
        win = _make_window(title="", app="App", layer=0, width=200, height=200)
        win["kCGWindowName"] = None  # Override with None
        result = self._run([win], monkeypatch)
        assert len(result) == 1

    def test_sort_higher_layer_first(self, monkeypatch):
        """Windows must be sorted: higher layer first."""
        wins = [
            _make_window(layer=0, width=200, height=200, title="Back", app="A", window_id=1),
            _make_window(layer=5, width=200, height=200, title="Front", app="B", window_id=2),
            _make_window(layer=2, width=200, height=200, title="Mid", app="C", window_id=3),
        ]
        result = self._run(wins, monkeypatch)
        assert [w["title"] for w in result] == ["Front", "Mid", "Back"]

    def test_sort_within_same_layer_smaller_area_first(self, monkeypatch):
        """Within the same layer, smaller area must come before larger area."""
        wins = [
            _make_window(layer=0, width=800, height=600, title="Big", app="A", window_id=1),
            _make_window(layer=0, width=100, height=100, title="Small", app="B", window_id=2),
            _make_window(layer=0, width=400, height=300, title="Mid", app="C", window_id=3),
        ]
        result = self._run(wins, monkeypatch)
        assert [w["title"] for w in result] == ["Small", "Mid", "Big"]

    def test_empty_window_list(self, monkeypatch):
        result = self._run([], monkeypatch)
        assert result == []

    def test_none_window_list(self, monkeypatch):
        """CGWindowListCopyWindowInfo may return None; handle gracefully."""
        import Quartz
        Quartz.CGWindowListCopyWindowInfo.return_value = None  # type: ignore[attr-defined]

        from wenzi.screenshot.capture import _collect_window_metadata
        result = _collect_window_metadata()
        assert result == []

    def test_missing_bounds_key(self, monkeypatch):
        """Windows with missing bounds dict should be treated as 0×0 and filtered."""
        win = {
            "kCGWindowLayer": 0,
            "kCGWindowName": "Broken",
            "kCGWindowOwnerName": "App",
            "kCGWindowNumber": 99,
            # No "kCGWindowBounds" key
        }
        import Quartz
        Quartz.CGWindowListCopyWindowInfo.return_value = [win]  # type: ignore[attr-defined]
        from wenzi.screenshot.capture import _collect_window_metadata
        result = _collect_window_metadata()
        # 0×0 is smaller than _MIN_WIN_SIZE, so it must be excluded
        assert result == []

    def test_window_id_preserved(self, monkeypatch):
        win = _make_window(window_id=42, title="ID Test", app="App")
        result = self._run([win], monkeypatch)
        assert result[0]["window_id"] == 42


# ---------------------------------------------------------------------------
# _capture_displays_sync tests
# ---------------------------------------------------------------------------

class TestCaptureDisplaysSync:
    """Tests for the Quartz display capture wrapper."""

    def _setup_quartz(self, display_ids: List[int], image_per_display=True):
        """Configure mock Quartz for CGGetOnlineDisplayList + CGDisplayCreateImage."""
        import sys
        quartz = sys.modules["Quartz"]

        # CGGetOnlineDisplayList returns (err, display_id_array, count)
        quartz.CGGetOnlineDisplayList.return_value = (0, display_ids, len(display_ids))

        # CGDisplayCreateImage returns a fake image or None
        if image_per_display:
            quartz.CGDisplayCreateImage.side_effect = lambda did: MagicMock(name=f"Image-{did}")
        else:
            quartz.CGDisplayCreateImage.return_value = None

    def test_single_display(self, monkeypatch):
        self._setup_quartz([1])
        from wenzi.screenshot.capture import _capture_displays_sync
        result = _capture_displays_sync()
        assert 1 in result
        assert result[1] is not None

    def test_multiple_displays(self, monkeypatch):
        self._setup_quartz([1, 2, 3])
        from wenzi.screenshot.capture import _capture_displays_sync
        result = _capture_displays_sync()
        assert set(result.keys()) == {1, 2, 3}

    def test_no_displays_returns_empty(self, monkeypatch):
        self._setup_quartz([])
        from wenzi.screenshot.capture import _capture_displays_sync
        result = _capture_displays_sync()
        assert result == {}

    def test_none_image_excluded_from_results(self, monkeypatch):
        """When CGDisplayCreateImage returns None, display should be excluded."""
        self._setup_quartz([1, 2], image_per_display=False)
        from wenzi.screenshot.capture import _capture_displays_sync
        result = _capture_displays_sync()
        assert result == {}

    def test_error_raises_runtime_error(self, monkeypatch):
        import sys
        quartz = sys.modules["Quartz"]
        quartz.CGGetOnlineDisplayList.return_value = (-1, None, 0)

        from wenzi.screenshot.capture import _capture_displays_sync
        with pytest.raises(RuntimeError, match="CGGetOnlineDisplayList failed"):
            _capture_displays_sync()


# ---------------------------------------------------------------------------
# capture_screen integration tests
# ---------------------------------------------------------------------------

class TestCaptureScreen:
    """End-to-end tests for the public capture_screen() function."""

    def _install_full_mocks(self, monkeypatch, display_ids: List[int]):
        """Set up Quartz mocks for a full capture_screen() call."""
        import sys

        quartz = sys.modules["Quartz"]
        # Window metadata mock
        quartz.CGWindowListCopyWindowInfo.return_value = [
            _make_window(title="Test App", app="Test", layer=0, width=400, height=300)
        ]
        # Display capture mock
        quartz.CGGetOnlineDisplayList.return_value = (0, display_ids, len(display_ids))
        quartz.CGDisplayCreateImage.side_effect = lambda did: MagicMock(name=f"Image-{did}")

    def test_returns_expected_shape(self, monkeypatch, tmp_path):
        monkeypatch.setattr("wenzi.config.DEFAULT_CACHE_DIR", str(tmp_path))
        self._install_full_mocks(monkeypatch, [1])

        from wenzi.screenshot.capture import capture_screen
        result = capture_screen()

        assert "displays" in result
        assert "windows" in result
        assert isinstance(result["displays"], dict)
        assert isinstance(result["windows"], list)

    def test_display_count_matches(self, monkeypatch, tmp_path):
        monkeypatch.setattr("wenzi.config.DEFAULT_CACHE_DIR", str(tmp_path))
        self._install_full_mocks(monkeypatch, [1, 2])

        from wenzi.screenshot.capture import capture_screen
        result = capture_screen()
        assert len(result["displays"]) == 2

    def test_windows_list_populated(self, monkeypatch, tmp_path):
        monkeypatch.setattr("wenzi.config.DEFAULT_CACHE_DIR", str(tmp_path))
        self._install_full_mocks(monkeypatch, [1])

        from wenzi.screenshot.capture import capture_screen
        result = capture_screen()
        assert len(result["windows"]) == 1
        assert result["windows"][0]["title"] == "Test App"

    def test_tmp_dir_created(self, monkeypatch, tmp_path):
        monkeypatch.setattr("wenzi.config.DEFAULT_CACHE_DIR", str(tmp_path))
        self._install_full_mocks(monkeypatch, [1])

        from wenzi.screenshot.capture import capture_screen
        capture_screen()

        expected_dir = tmp_path / "screenshot_tmp"
        assert expected_dir.is_dir()
