"""Mouse-following input-source indicator.

Shows a small label next to the mouse cursor displaying the current input
method. The label follows the mouse while the cursor is visible. When the
cursor hides (e.g. while typing) the label does *not* vanish in lockstep —
it stays put for ``input_indicator.hide_delay`` seconds (default 8) and only
then hides. If the cursor reappears within that window the pending hide is
cancelled and following resumes immediately. Switching the input source also
surfaces the chip and re-arms the same delay, so a method change is visible
even mid-typing.

Per-input-source styles (text + color) can be configured under the
``input_indicator.styles`` config key, keyed by input source ID. When the
current input source has no configured style, the source ID is logged once
(to make configuration easy) and the label falls back to the first character
of the localized input source name.

Drawing uses a plain translucent rounded rectangle (not NSGlassEffectView):
the chip is tiny and repositions ~30x/second, so a glass surface would churn
IOSurface backing needlessly. A persistent panel is reused across show/hide.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Refresh / follow interval — 30 Hz.
_REFRESH_INTERVAL = 1.0 / 30.0

# Chip dimensions (matches the Hammerspoon original).
_PANEL_WIDTH = 28
_PANEL_HEIGHT = 24
_CORNER_RADIUS = 8.0
_FONT_SIZE = 14.0

# Distributed notification posted when the selected keyboard input source
# changes (Carbon's kTISNotifySelectedKeyboardInputSourceChanged).
_INPUT_SOURCE_CHANGED = "com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged"


# ---------------------------------------------------------------------------
# Pure helpers (no AppKit) — unit-testable
# ---------------------------------------------------------------------------

def _first_char(s: str | None) -> str:
    """Return the first character of ``s`` (Unicode aware), or ``"?"``."""
    if not s:
        return "?"
    return s[0]


def _parse_hex_color(s: object) -> tuple[float, float, float, float] | None:
    """Parse ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA`` into an RGBA 0..1 tuple.

    Returns ``None`` for anything that is not a valid hex color string.
    """
    if not isinstance(s, str):
        return None
    h = s.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) not in (6, 8):
        return None
    try:
        vals = [int(h[i:i + 2], 16) / 255.0 for i in range(0, len(h), 2)]
    except ValueError:
        return None
    if len(vals) == 3:
        vals.append(1.0)
    return (vals[0], vals[1], vals[2], vals[3])


def _resolve_display(
    source_id: str | None,
    localized: str | None,
    styles: dict,
) -> tuple[str, str | None, float | None, bool]:
    """Resolve the label text, color hex, and alpha for an input source.

    Returns ``(text, color_hex_or_None, alpha_or_None, has_style)``. When no
    style entry exists, ``text`` falls back to the first character of the
    localized name (or the source ID), ``color_hex``/``alpha`` are ``None``
    (caller applies defaults), and ``has_style`` is ``False``. ``alpha`` is the
    style's explicit per-source opacity (0..1) if set, else ``None``.
    """
    style = styles.get(source_id) if (source_id and isinstance(styles, dict)) else None
    if not isinstance(style, dict):
        style = None

    text: str | None = None
    color_hex: str | None = None
    alpha: float | None = None
    if style is not None:
        t = style.get("text")
        if isinstance(t, str) and t:
            text = t
        c = style.get("color")
        if isinstance(c, str) and c:
            color_hex = c
        a = style.get("alpha")
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            alpha = float(a)

    if not text:
        text = _first_char(localized or source_id or "?")
    return text, color_hex, alpha, (style is not None)


def _resolve_alpha(
    style_alpha: float | None,
    has_style: bool,
    default_alpha: object,
) -> float:
    """Resolve whole-chip opacity, clamped to 0..1.

    Priority: explicit per-style ``alpha`` > ``1.0`` for any other configured
    style > ``default_alpha`` for unconfigured sources. Falls back to ``1.0``
    if the resolved value is not a valid number.
    """
    if style_alpha is not None:
        alpha = style_alpha
    elif has_style:
        alpha = 1.0
    else:
        alpha = default_alpha
    try:
        alpha = float(alpha)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, alpha))


# ---------------------------------------------------------------------------
# Drawing (AppKit) — guarded so the module imports without AppKit (tests)
# ---------------------------------------------------------------------------

class _IndicatorRenderer:
    """Holds the current text/color and draws the chip into its NSView."""

    def __init__(self) -> None:
        self._text: str = "?"
        self._color = None  # NSColor
        self._view = None  # _IndicatorNSView

    def create_view(self, width: int, height: int):
        from Foundation import NSMakeRect

        view = _InputIndicatorNSView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        view._renderer = self
        self._view = view
        return view

    def set_display(self, text: str, color) -> None:
        self._text = text
        self._color = color
        if self._view is not None:
            self._view.setNeedsDisplay_(True)

    def draw(self) -> None:
        from AppKit import (
            NSBezierPath,
            NSColor,
            NSFont,
            NSFontAttributeName,
            NSForegroundColorAttributeName,
            NSMutableParagraphStyle,
            NSParagraphStyleAttributeName,
            NSShadow,
            NSShadowAttributeName,
        )
        from Foundation import NSMakeRect, NSString

        if self._view is None:
            return
        bounds = self._view.bounds()

        # Translucent rounded background.
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.3).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            bounds, _CORNER_RADIUS, _CORNER_RADIUS
        ).fill()

        # Centered text with a soft shadow for legibility on any background.
        shadow = NSShadow.alloc().init()
        shadow.setShadowBlurRadius_(2.0)
        shadow.setShadowOffset_((0.0, 0.0))
        shadow.setShadowColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 1))

        para = NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(1)  # NSTextAlignmentCenter

        font = NSFont.fontWithName_size_("Helvetica", _FONT_SIZE) or NSFont.systemFontOfSize_(_FONT_SIZE)
        attrs = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: self._color or NSColor.whiteColor(),
            NSParagraphStyleAttributeName: para,
            NSShadowAttributeName: shadow,
        }

        ns = NSString.stringWithString_(self._text or "?")
        size = ns.sizeWithAttributes_(attrs)
        ty = (bounds.size.height - size.height) / 2.0
        ns.drawInRect_withAttributes_(
            NSMakeRect(0, ty, bounds.size.width, size.height), attrs
        )


try:
    import objc
    from AppKit import NSView
    from Foundation import NSObject

    # NOTE: ObjC class names are global — must not collide with any other
    # registered class (e.g. recording_indicator's _IndicatorNSView). Keep
    # these names unique to this module.
    class _InputIndicatorNSView(NSView):
        _renderer = objc.ivar()

        def drawRect_(self, rect):
            if self._renderer is not None:
                self._renderer.draw()

        def isOpaque(self):
            return False

    class _InputIndicatorHelper(NSObject):
        """ObjC target for the follow timer and the input-source notification."""

        _controller = objc.ivar()

        def tick_(self, _timer):
            if self._controller is not None:
                self._controller.on_tick()

        def inputSourceChanged_(self, _note):
            if self._controller is not None:
                self._controller.apply_input_source(show_on_change=True)

except Exception:  # pragma: no cover - AppKit unavailable (e.g. test env)
    _InputIndicatorNSView = None
    _InputIndicatorHelper = None


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class InputIndicatorController:
    """Lifecycle + follow loop for the mouse-side input indicator."""

    def __init__(self, app) -> None:
        self._app = app
        self._panel = None
        self._timer = None
        self._helper = None
        self._renderer: _IndicatorRenderer | None = None
        self._started = False
        self._on_screen = False
        self._hide_at: float | None = None  # monotonic deadline for a pending hide
        self._last_source_id: str | None = None
        self._warned_ids: set[str] = set()

        cfg = self._cfg()
        self._enabled = bool(cfg.get("enabled", False))

    # -- config -----------------------------------------------------------
    def _cfg(self) -> dict:
        return self._app._config.get("input_indicator", {}) or {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        """Create the panel and begin following the cursor (if enabled)."""
        if not self._enabled or self._started:
            return
        if _InputIndicatorNSView is None or _InputIndicatorHelper is None:
            logger.debug("Input indicator unavailable (AppKit missing)")
            return
        try:
            from AppKit import NSColor, NSPanel, NSStatusWindowLevel
            from Foundation import (
                NSDistributedNotificationCenter,
                NSMakeRect,
                NSTimer,
            )

            self._renderer = _IndicatorRenderer()
            view = self._renderer.create_view(_PANEL_WIDTH, _PANEL_HEIGHT)

            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, _PANEL_WIDTH, _PANEL_HEIGHT),
                0,  # NSBorderlessWindowMask
                2,  # NSBackingStoreBuffered
                False,
            )
            panel.setLevel_(NSStatusWindowLevel + 1)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setIgnoresMouseEvents_(True)
            panel.setHasShadow_(False)
            panel.setHidesOnDeactivate_(False)
            # canJoinAllSpaces | stationary | fullScreenAuxiliary
            panel.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))
            panel.setContentView_(view)
            self._panel = panel
            self._on_screen = False

            self._helper = _InputIndicatorHelper.alloc().init()
            self._helper._controller = self

            # Seed the label and listen for future input-source changes.
            self._last_source_id = None
            self.apply_input_source()
            NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
                self._helper, b"inputSourceChanged:", _INPUT_SOURCE_CHANGED, None
            )

            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                _REFRESH_INTERVAL, self._helper, b"tick:", None, True
            )
            self._started = True
            logger.debug("Input indicator started")
        except Exception:
            logger.error("Failed to start input indicator", exc_info=True)
            self.stop()

    def stop(self) -> None:
        """Tear down the timer, observer, and panel."""
        try:
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None
            if self._helper is not None:
                try:
                    from Foundation import NSDistributedNotificationCenter

                    NSDistributedNotificationCenter.defaultCenter().removeObserver_(
                        self._helper
                    )
                except Exception:
                    logger.debug("Failed to remove input-source observer", exc_info=True)
                self._helper._controller = None
                self._helper = None
            if self._renderer is not None and self._renderer._view is not None:
                self._renderer._view._renderer = None
            if self._panel is not None:
                self._panel.orderOut_(None)
                self._panel = None
            self._renderer = None
            self._on_screen = False
            self._hide_at = None
            self._last_source_id = None
            self._warned_ids.clear()
            self._started = False
            logger.debug("Input indicator stopped")
        except Exception:
            logger.warning("Failed to stop input indicator", exc_info=True)

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if self._enabled:
            self.start()
        else:
            self.stop()

    def reload_config(self) -> None:
        """Apply config changes after a reload (enable flag + styles)."""
        new_enabled = bool(self._cfg().get("enabled", False))
        was_running = self._started
        self.set_enabled(new_enabled)
        # If it was already running and stays enabled, set_enabled's start() was
        # a no-op — refresh styles/colors live on the next source read.
        if new_enabled and was_running:
            self._warned_ids.clear()
            self._last_source_id = None
            self.apply_input_source()

    # -- menu -------------------------------------------------------------
    def on_menu_toggle(self, sender) -> None:
        from wenzi.config import save_config

        app = self._app
        new_val = not self._enabled
        sender.state = 1 if new_val else 0
        app._config.setdefault("input_indicator", {})["enabled"] = new_val
        save_config(app._config, app._config_path)
        self.set_enabled(new_val)

    # -- runtime ----------------------------------------------------------
    def _cursor_visible(self) -> bool:
        try:
            from wenzi import _cgeventtap as cg

            return cg.CGCursorIsVisible()
        except Exception:
            return True

    def _hide_delay(self) -> float:
        """Seconds to keep the chip on screen after the cursor hides."""
        try:
            return max(0.0, float(self._cfg().get("hide_delay", 8.0)))
        except (TypeError, ValueError):
            return 8.0

    def _show(self) -> None:
        """Position the chip at the cursor and order it front (idempotent)."""
        from AppKit import NSEvent

        cfg = self._cfg()
        mouse = NSEvent.mouseLocation()
        self._panel.setFrameOrigin_(
            (mouse.x + cfg.get("offset_x", 14), mouse.y + cfg.get("offset_y", -30))
        )
        if not self._on_screen:
            self._panel.orderFront_(None)
            self._on_screen = True

    def on_tick(self) -> None:
        """Timer callback: follow the cursor and mirror its visibility.

        When the cursor hides the chip lingers for ``hide_delay`` seconds
        before hiding, rather than disappearing in lockstep with the cursor.
        """
        if self._panel is None:
            return
        if not self._cursor_visible():
            if self._on_screen:
                if self._hide_at is None:
                    self._hide_at = time.monotonic() + self._hide_delay()
                elif time.monotonic() >= self._hide_at:
                    self._panel.orderOut_(None)
                    self._on_screen = False
                    self._hide_at = None
            return

        # Cursor visible: cancel any pending hide and resume following.
        self._hide_at = None
        try:
            self._show()
        except Exception:
            logger.debug("Input indicator tick failed", exc_info=True)

    def apply_input_source(self, show_on_change: bool = False) -> None:
        """Recompute the label text/color for the current input source.

        With ``show_on_change`` set, a genuine source switch also surfaces the
        chip (even while the cursor is hidden) and re-arms the hide delay.
        """
        if self._renderer is None:
            return
        try:
            from wenzi.input_source import get_current_input_source_info

            source_id, localized = get_current_input_source_info()
            if source_id == self._last_source_id:
                return
            self._last_source_id = source_id

            cfg = self._cfg()
            styles = cfg.get("styles", {}) or {}
            text, color_hex, style_alpha, has_style = _resolve_display(
                source_id, localized, styles
            )

            color = self._make_color(color_hex or cfg.get("default_color", "#FFFFFF"))
            self._renderer.set_display(text, color)

            alpha = _resolve_alpha(style_alpha, has_style, cfg.get("default_alpha", 1.0))
            if self._panel is not None:
                self._panel.setAlphaValue_(alpha)

            if not has_style and source_id and source_id not in self._warned_ids:
                self._warned_ids.add(source_id)
                logger.info(
                    "[input_indicator] 未配置样式: id=%s name=%s", source_id, localized
                )

            if show_on_change and self._panel is not None:
                self._show()
                self._hide_at = time.monotonic() + self._hide_delay()
        except Exception:
            logger.debug("Failed to apply input source", exc_info=True)

    @staticmethod
    def _make_color(hex_str):
        from AppKit import NSColor

        rgba = _parse_hex_color(hex_str)
        if rgba is None:
            return NSColor.whiteColor()
        return NSColor.colorWithSRGBRed_green_blue_alpha_(*rgba)
