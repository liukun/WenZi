"""Tests for the mouse-side input indicator (pure logic + controller wiring)."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from wenzi.ui import input_indicator as ii


def test_objc_class_names_unique_across_import_order():
    """Regression: the indicator's ObjC subclasses must register even when
    recording_indicator (which defines a same-purpose view) is imported first.

    ObjC class names are global; a duplicate name makes PyObjC raise on the
    second definition, which the module's try/except would null out — leaving
    the indicator silently disabled ("AppKit missing"). Run in a subprocess to
    control import order deterministically.
    """
    try:
        import AppKit  # noqa: F401
    except Exception:
        pytest.skip("AppKit unavailable")
    code = (
        "from wenzi.audio import recording_indicator\n"
        "from wenzi.ui import input_indicator as ii\n"
        "assert ii._InputIndicatorNSView is not None, 'view class collided'\n"
        "assert ii._InputIndicatorHelper is not None, 'helper class collided'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


class TestFirstChar:
    @pytest.mark.parametrize("value,expected", [
        ("ABC", "A"),
        ("拼音 - 简体", "拼"),
        ("Pinyin - Simplified", "P"),
        ("", "?"),
        (None, "?"),
    ])
    def test_first_char(self, value, expected):
        assert ii._first_char(value) == expected


class TestParseHexColor:
    @pytest.mark.parametrize("value,expected", [
        ("#FFFFFF", (1.0, 1.0, 1.0, 1.0)),
        ("FFFFFF", (1.0, 1.0, 1.0, 1.0)),
        ("#000000", (0.0, 0.0, 0.0, 1.0)),
        ("#fff", (1.0, 1.0, 1.0, 1.0)),
    ])
    def test_valid(self, value, expected):
        assert ii._parse_hex_color(value) == expected

    def test_alpha_channel(self):
        r, g, b, a = ii._parse_hex_color("#FF000080")
        assert (r, g, b) == (1.0, 0.0, 0.0)
        assert abs(a - 0.5019607843) < 1e-6

    @pytest.mark.parametrize("value", [
        "red", "#GGGGGG", "#12345", "", None, 123, "#1234567",
    ])
    def test_invalid_returns_none(self, value):
        assert ii._parse_hex_color(value) is None


class TestResolveDisplay:
    def test_uses_configured_text_and_color(self):
        styles = {"com.apple.keylayout.ABC": {"text": "EN", "color": "#5AC8FA"}}
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.keylayout.ABC", "ABC", styles
        )
        assert text == "EN"
        assert color_hex == "#5AC8FA"
        assert alpha is None
        assert has_style is True

    def test_extracts_per_style_alpha(self):
        styles = {"com.apple.keylayout.ABC": {"text": "A", "alpha": 0.6}}
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.keylayout.ABC", "ABC", styles
        )
        assert alpha == 0.6
        assert has_style is True

    def test_bool_alpha_ignored(self):
        """A bool is not a valid alpha (avoid True == 1.0 surprises)."""
        styles = {"com.apple.keylayout.ABC": {"alpha": True}}
        _text, _color, alpha, _has = ii._resolve_display(
            "com.apple.keylayout.ABC", "ABC", styles
        )
        assert alpha is None

    def test_falls_back_to_first_char_of_localized_name(self):
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.inputmethod.SCIM.ITABC", "拼音 - 简体", {}
        )
        assert text == "拼"
        assert color_hex is None
        assert alpha is None
        assert has_style is False

    def test_falls_back_to_source_id_when_no_localized(self):
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.keylayout.US", None, {}
        )
        assert text == "c"  # first char of the source ID
        assert has_style is False

    def test_style_present_but_no_text_uses_fallback_text(self):
        """A style entry with only a color still counts as configured."""
        styles = {"com.apple.keylayout.ABC": {"color": "#FF0000"}}
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.keylayout.ABC", "ABC", styles
        )
        assert text == "A"
        assert color_hex == "#FF0000"
        assert has_style is True

    def test_non_dict_style_treated_as_absent(self):
        styles = {"com.apple.keylayout.ABC": "oops"}
        text, color_hex, alpha, has_style = ii._resolve_display(
            "com.apple.keylayout.ABC", "ABC", styles
        )
        assert text == "A"
        assert color_hex is None
        assert has_style is False

    def test_none_source_id(self):
        text, color_hex, alpha, has_style = ii._resolve_display(None, None, {})
        assert text == "?"
        assert has_style is False


class TestResolveAlpha:
    def test_unconfigured_uses_default_alpha(self):
        assert ii._resolve_alpha(None, has_style=False, default_alpha=0.6) == 0.6

    def test_configured_without_alpha_is_opaque(self):
        assert ii._resolve_alpha(None, has_style=True, default_alpha=0.6) == 1.0

    def test_explicit_style_alpha_wins(self):
        assert ii._resolve_alpha(0.3, has_style=True, default_alpha=0.6) == 0.3
        assert ii._resolve_alpha(0.3, has_style=False, default_alpha=0.6) == 0.3

    @pytest.mark.parametrize("value,expected", [
        (-0.5, 0.0),
        (1.5, 1.0),
        (0.0, 0.0),
        (1.0, 1.0),
    ])
    def test_clamped(self, value, expected):
        assert ii._resolve_alpha(value, has_style=True, default_alpha=1.0) == expected

    def test_non_numeric_default_falls_back_to_opaque(self):
        assert ii._resolve_alpha(None, has_style=False, default_alpha="oops") == 1.0


def _make_controller(config):
    app = MagicMock()
    app._config = config
    return ii.InputIndicatorController(app)


class TestControllerWiring:
    def test_enabled_reads_config(self):
        ctrl = _make_controller({"input_indicator": {"enabled": True}})
        assert ctrl.enabled is True

    def test_disabled_by_default(self):
        ctrl = _make_controller({})
        assert ctrl.enabled is False

    def test_start_noop_when_disabled(self):
        ctrl = _make_controller({"input_indicator": {"enabled": False}})
        ctrl.start()  # must not raise or create anything
        assert ctrl._panel is None
        assert ctrl._started is False

    def test_warns_once_per_unconfigured_source(self, monkeypatch, caplog):
        """An unconfigured input source logs its ID exactly once."""
        ctrl = _make_controller(
            {"input_indicator": {"enabled": True, "styles": {}}}
        )
        # Stub the AppKit/rendering bits so apply_input_source stays pure.
        ctrl._renderer = MagicMock()
        monkeypatch.setattr(ctrl, "_make_color", lambda _hex: "COLOR")
        monkeypatch.setattr(
            "wenzi.input_source.get_current_input_source_info",
            lambda: ("com.apple.keylayout.ABC", "ABC"),
        )

        with caplog.at_level("INFO"):
            ctrl.apply_input_source()
            # Force a re-read by clearing the cache; same source, should NOT warn again.
            ctrl._last_source_id = None
            ctrl.apply_input_source()

        warnings = [r for r in caplog.records if "未配置样式" in r.getMessage()]
        assert len(warnings) == 1
        assert "com.apple.keylayout.ABC" in warnings[0].getMessage()
        ctrl._renderer.set_display.assert_called_with("A", "COLOR")

    def test_no_warning_when_style_configured(self, monkeypatch, caplog):
        ctrl = _make_controller({
            "input_indicator": {
                "enabled": True,
                "styles": {"com.apple.keylayout.ABC": {"text": "EN"}},
            }
        })
        ctrl._renderer = MagicMock()
        monkeypatch.setattr(ctrl, "_make_color", lambda _hex: "COLOR")
        monkeypatch.setattr(
            "wenzi.input_source.get_current_input_source_info",
            lambda: ("com.apple.keylayout.ABC", "ABC"),
        )

        with caplog.at_level("INFO"):
            ctrl.apply_input_source()

        assert not [r for r in caplog.records if "未配置样式" in r.getMessage()]
        ctrl._renderer.set_display.assert_called_once_with("EN", "COLOR")


class TestDeferredHide:
    """on_tick keeps the chip on screen for hide_delay after the cursor hides."""

    def test_hide_deferred_until_delay_elapses(self, monkeypatch):
        ctrl = _make_controller(
            {"input_indicator": {"enabled": True, "hide_delay": 8.0}}
        )
        ctrl._panel = MagicMock()
        ctrl._on_screen = True
        clock = {"t": 100.0}
        monkeypatch.setattr(ii.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(ctrl, "_cursor_visible", lambda: False)

        # First invisible tick arms the deadline but stays on screen.
        ctrl.on_tick()
        ctrl._panel.orderOut_.assert_not_called()
        assert ctrl._on_screen is True
        assert ctrl._hide_at == 108.0

        # Just before the deadline — still visible.
        clock["t"] = 107.9
        ctrl.on_tick()
        ctrl._panel.orderOut_.assert_not_called()
        assert ctrl._on_screen is True

        # Deadline reached — hide now.
        clock["t"] = 108.0
        ctrl.on_tick()
        ctrl._panel.orderOut_.assert_called_once()
        assert ctrl._on_screen is False
        assert ctrl._hide_at is None

    def test_cursor_reappear_cancels_pending_hide(self, monkeypatch):
        ctrl = _make_controller(
            {"input_indicator": {"enabled": True, "hide_delay": 8.0}}
        )
        ctrl._panel = MagicMock()
        ctrl._on_screen = True
        clock = {"t": 100.0}
        visible = {"v": False}
        monkeypatch.setattr(ii.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(ctrl, "_cursor_visible", lambda: visible["v"])

        ctrl.on_tick()  # arm the deadline
        assert ctrl._hide_at is not None

        # Cursor reappears within the window — cancel the pending hide.
        visible["v"] = True
        clock["t"] = 103.0
        ctrl.on_tick()
        assert ctrl._hide_at is None
        ctrl._panel.orderOut_.assert_not_called()

    def test_zero_delay_hides_immediately(self, monkeypatch):
        ctrl = _make_controller(
            {"input_indicator": {"enabled": True, "hide_delay": 0}}
        )
        ctrl._panel = MagicMock()
        ctrl._on_screen = True
        clock = {"t": 100.0}
        monkeypatch.setattr(ii.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(ctrl, "_cursor_visible", lambda: False)

        # Deadline == now, so the next tick after arming hides. With a 0 delay
        # the arm and the elapse happen on consecutive ticks at the same time.
        ctrl.on_tick()  # arms _hide_at = 100.0
        clock["t"] = 100.0
        ctrl.on_tick()  # now >= deadline
        ctrl._panel.orderOut_.assert_called_once()
        assert ctrl._on_screen is False


class TestShowOnSourceChange:
    """A genuine input-source switch surfaces the chip and arms the hide delay."""

    def _ctrl(self, monkeypatch, source):
        ctrl = _make_controller(
            {"input_indicator": {"enabled": True, "hide_delay": 8.0, "styles": {}}}
        )
        ctrl._panel = MagicMock()
        ctrl._renderer = MagicMock()
        monkeypatch.setattr(ctrl, "_make_color", lambda _hex: "COLOR")
        monkeypatch.setattr(ctrl, "_show", MagicMock())  # avoid AppKit
        monkeypatch.setattr(ii.time, "monotonic", lambda: 200.0)
        monkeypatch.setattr(
            "wenzi.input_source.get_current_input_source_info", lambda: source
        )
        return ctrl

    def test_change_reveals_and_arms_hide(self, monkeypatch):
        ctrl = self._ctrl(monkeypatch, ("com.apple.keylayout.ABC", "ABC"))
        ctrl.apply_input_source(show_on_change=True)
        ctrl._show.assert_called_once()
        assert ctrl._hide_at == 208.0

    def test_seed_does_not_reveal(self, monkeypatch):
        ctrl = self._ctrl(monkeypatch, ("com.apple.keylayout.ABC", "ABC"))
        ctrl.apply_input_source()  # default show_on_change=False
        ctrl._show.assert_not_called()
        assert ctrl._hide_at is None

    def test_unchanged_source_does_not_reveal(self, monkeypatch):
        ctrl = self._ctrl(monkeypatch, ("com.apple.keylayout.ABC", "ABC"))
        ctrl._last_source_id = "com.apple.keylayout.ABC"  # same → early return
        ctrl.apply_input_source(show_on_change=True)
        ctrl._show.assert_not_called()
        assert ctrl._hide_at is None
