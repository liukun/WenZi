"""Tests for wz.window API."""

from unittest.mock import MagicMock

import pytest

from wenzi.scripting.api.window import (
    WindowAPI,
    _visible_frame_ax,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_ax(monkeypatch, *, pos=(100, 200), size=(800, 600)):
    """Patch AX helpers to return fixed values without real Accessibility."""
    win = MagicMock(name="AXWindow")
    monkeypatch.setattr(
        "wenzi.scripting.api.window._get_focused_window", lambda: win
    )
    monkeypatch.setattr(
        "wenzi.scripting.api.window._get_position",
        lambda w: pos if w is win else None,
    )
    monkeypatch.setattr(
        "wenzi.scripting.api.window._get_size",
        lambda w: size if w is win else None,
    )
    set_pos_calls = []
    set_size_calls = []
    monkeypatch.setattr(
        "wenzi.scripting.api.window._set_position",
        lambda w, x, y: set_pos_calls.append((x, y)),
    )
    monkeypatch.setattr(
        "wenzi.scripting.api.window._set_size",
        lambda w, x, y: set_size_calls.append((x, y)),
    )
    return win, set_pos_calls, set_size_calls


def _mock_screen(x=0, y=0, w=1920, h=1080, vis_x=0, vis_y=0, vis_w=1920, vis_h=1055, name="Built-in"):
    """Create a fake NSScreen-like object."""
    screen = MagicMock()
    frame = MagicMock()
    frame.origin.x = x
    frame.origin.y = y
    frame.size.width = w
    frame.size.height = h
    screen.frame.return_value = frame
    vf = MagicMock()
    vf.origin.x = vis_x
    vf.origin.y = vis_y
    vf.size.width = vis_w
    vf.size.height = vis_h
    screen.visibleFrame.return_value = vf
    screen.localizedName.return_value = name
    return screen


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFocusedFrame:
    def test_returns_dict(self, monkeypatch):
        _mock_ax(monkeypatch, pos=(50, 100), size=(640, 480))
        api = WindowAPI()
        frame = api.focused_frame()
        assert frame == {"x": 50, "y": 100, "w": 640, "h": 480}

    def test_returns_none_when_no_window(self, monkeypatch):
        monkeypatch.setattr(
            "wenzi.scripting.api.window._get_focused_window", lambda: None
        )
        assert WindowAPI().focused_frame() is None


class TestSetFrame:
    def test_sets_position_and_size(self, monkeypatch):
        _, pos_calls, size_calls = _mock_ax(monkeypatch)
        WindowAPI().set_frame(10, 20, 300, 400)
        # Position set twice (before and after resize)
        assert pos_calls == [(10, 20), (10, 20)]
        assert size_calls == [(300, 400)]

    def test_noop_when_no_window(self, monkeypatch):
        monkeypatch.setattr(
            "wenzi.scripting.api.window._get_focused_window", lambda: None
        )
        WindowAPI().set_frame(0, 0, 100, 100)  # should not raise


class TestSnap:
    @pytest.mark.parametrize(
        "position, expected_frac",
        [
            ("left", (0, 0, 0.5, 1)),
            ("right", (0.5, 0, 0.5, 1)),
            ("top", (0, 0, 1, 0.5)),
            ("bottom", (0, 0.5, 1, 0.5)),
            ("full", (0, 0, 1, 1)),
            ("top-left", (0, 0, 0.5, 0.5)),
            ("bottom-right", (0.5, 0.5, 0.5, 0.5)),
        ],
    )
    def test_snap_positions(self, monkeypatch, position, expected_frac):
        win, pos_calls, size_calls = _mock_ax(monkeypatch, pos=(100, 50), size=(800, 600))
        # Mock screen: visible area 1920x1055 starting at (0, 25) in AX coords
        screen = _mock_screen()
        monkeypatch.setattr(
            "wenzi.scripting.api.window._screen_for_window", lambda w: screen
        )
        monkeypatch.setattr(
            "wenzi.scripting.api.window._visible_frame_ax",
            lambda s: (0, 25, 1920, 1055),
        )

        WindowAPI().snap(position)

        fx, fy, fw, fh = expected_frac
        expected_x = 0 + fx * 1920
        expected_y = 25 + fy * 1055
        expected_w = fw * 1920
        expected_h = fh * 1055

        assert size_calls == [(expected_w, expected_h)]
        assert pos_calls == [(expected_x, expected_y), (expected_x, expected_y)]

    def test_unknown_position_warns(self, monkeypatch, caplog):
        _mock_ax(monkeypatch)
        import logging
        with caplog.at_level(logging.WARNING):
            WindowAPI().snap("diagonal")
        assert "Unknown snap position" in caplog.text


class TestCenter:
    def test_centers_on_screen(self, monkeypatch):
        win, pos_calls, _ = _mock_ax(monkeypatch, pos=(0, 0), size=(400, 300))
        monkeypatch.setattr(
            "wenzi.scripting.api.window._screen_for_window", lambda w: MagicMock()
        )
        monkeypatch.setattr(
            "wenzi.scripting.api.window._visible_frame_ax",
            lambda s: (0, 25, 1920, 1055),
        )

        WindowAPI().center()

        # Centered: x = (1920-400)/2, y = 25 + (1055-300)/2
        assert pos_calls == [(760.0, 402.5)]


def _patch_nsscreen(monkeypatch, screens):
    """Patch AppKit.NSScreen so lazy imports inside window.py see the mock."""
    import AppKit as _appkit

    mock_ns = MagicMock()
    mock_ns.mainScreen.return_value = screens[0]
    mock_ns.screens.return_value = screens
    monkeypatch.setattr(_appkit, "NSScreen", mock_ns)
    return mock_ns


class TestScreens:
    def test_returns_screen_info(self, monkeypatch):
        screen = _mock_screen(vis_x=0, vis_y=0, vis_w=1920, vis_h=1055)
        _patch_nsscreen(monkeypatch, [screen])
        monkeypatch.setattr(
            "wenzi.scripting.api.window._visible_frame_ax",
            lambda s: (0, 25, 1920, 1055),
        )

        result = WindowAPI().screens()

        assert len(result) == 1
        assert result[0]["w"] == 1920
        assert result[0]["name"] == "Built-in"


class TestMoveToScreen:
    def test_moves_to_next_screen(self, monkeypatch):
        win, pos_calls, size_calls = _mock_ax(
            monkeypatch, pos=(100, 125), size=(960, 1055)
        )
        s1 = _mock_screen(name="Primary")
        s2 = _mock_screen(name="Secondary")
        _patch_nsscreen(monkeypatch, [s1, s2])

        monkeypatch.setattr(
            "wenzi.scripting.api.window._screen_for_window", lambda w: s1
        )

        def fake_visible(s):
            if s is s1:
                return (0, 25, 1920, 1055)
            return (1920, 25, 1920, 1055)

        monkeypatch.setattr(
            "wenzi.scripting.api.window._visible_frame_ax", fake_visible
        )

        WindowAPI().move_to_screen("next")

        assert len(pos_calls) == 2
        assert len(size_calls) == 1

    def test_noop_single_screen(self, monkeypatch):
        _mock_ax(monkeypatch)
        s1 = _mock_screen()
        _patch_nsscreen(monkeypatch, [s1])
        monkeypatch.setattr(
            "wenzi.scripting.api.window._screen_for_window", lambda w: s1
        )
        WindowAPI().move_to_screen("next")  # should not raise


class TestVisibleFrameAx:
    def test_coordinate_conversion(self, monkeypatch):
        """Cocoa bottom-left origin → AX top-left origin."""
        screen = _mock_screen(
            w=1920, h=1080,
            vis_x=0, vis_y=25, vis_w=1920, vis_h=1055,
        )
        main_screen = _mock_screen(w=1920, h=1080)
        _patch_nsscreen(monkeypatch, [main_screen])

        x, y, w, h = _visible_frame_ax(screen)

        assert x == 0
        # AX y = main_h - cocoa_y - vis_h = 1080 - 25 - 1055 = 0
        assert y == 0
        assert w == 1920
        assert h == 1055
