"""Floating overlay panel for real-time streaming transcription text."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Layout constants
_PANEL_WIDTH = 350
_PANEL_MIN_HEIGHT = 60
_PANEL_MAX_HEIGHT = 160
_CORNER_RADIUS = 10
_PADDING = 12
_FONT_SIZE = 15.0


def _dynamic_bg_color():
    """Create a dynamic background color matching RecordingIndicatorPanel.

    Inverted scheme: dark bg in light mode, light bg in dark mode —
    consistent with other floating overlays in the app.
    """
    from AppKit import NSColor

    def _provider(appearance):
        name = appearance.bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"]
        )
        if name and "Dark" in str(name):
            return NSColor.colorWithSRGBRed_green_blue_alpha_(0.9, 0.9, 0.9, 0.9)
        return NSColor.colorWithSRGBRed_green_blue_alpha_(0.1, 0.1, 0.1, 0.9)

    return NSColor.colorWithName_dynamicProvider_(None, _provider)


def _dynamic_text_color():
    """Create a dynamic text color that contrasts with the background."""
    from AppKit import NSColor

    def _provider(appearance):
        name = appearance.bestMatchFromAppearancesWithNames_(
            ["NSAppearanceNameAqua", "NSAppearanceNameDarkAqua"]
        )
        if name and "Dark" in str(name):
            return NSColor.colorWithSRGBRed_green_blue_alpha_(0.1, 0.1, 0.1, 1.0)
        return NSColor.colorWithSRGBRed_green_blue_alpha_(0.95, 0.95, 0.95, 1.0)

    return NSColor.colorWithName_dynamicProvider_(None, _provider)


# Cached delegate class
_PanelCloseDelegate = None


def _get_panel_close_delegate_class():
    global _PanelCloseDelegate
    if _PanelCloseDelegate is not None:
        return _PanelCloseDelegate

    from Foundation import NSObject
    import objc

    class LiveTranscriptionCloseDelegate(NSObject):
        _panel_ref = None

        @objc.python_method
        def windowWillClose_(self, notification):
            if self._panel_ref is not None:
                self._panel_ref.close()

    _PanelCloseDelegate = LiveTranscriptionCloseDelegate
    return _PanelCloseDelegate


class LiveTranscriptionOverlay:
    """Non-interactive floating overlay showing real-time transcription text.

    Positioned at screen center, below the recording indicator.
    Auto-resizes height to fit text content.
    """

    def __init__(self) -> None:
        self._panel = None
        self._content_view = None
        self._text_field = None
        self._close_delegate = None
        self._current_text = ""

    @property
    def is_visible(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def show(self) -> None:
        """Show the overlay panel."""
        from AppKit import (
            NSColor,
            NSFont,
            NSPanel,
            NSScreen,
            NSStatusWindowLevel,
            NSTextField,
            NSView,
        )
        from Foundation import NSMakeRect

        if self._panel is not None:
            self._panel.orderOut_(None)
            self._panel = None

        # Create borderless panel with clear background (layer handles visuals)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, _PANEL_WIDTH, _PANEL_MIN_HEIGHT),
            0,  # NSBorderlessWindowMask
            2,  # NSBackingStoreBuffered
            False,
        )
        panel.setLevel_(NSStatusWindowLevel + 1)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setIgnoresMouseEvents_(True)
        panel.setHasShadow_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setCollectionBehavior_(1 << 4)  # canJoinAllSpaces

        # Content view with rounded background via layer
        content = NSView.alloc().initWithFrame_(
            NSMakeRect(0, 0, _PANEL_WIDTH, _PANEL_MIN_HEIGHT)
        )
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(_CORNER_RADIUS)
        content.layer().setMasksToBounds_(True)

        bg_color = _dynamic_bg_color()
        content.layer().setBackgroundColor_(bg_color.CGColor())

        # Text field — wrapping label for multi-line support
        text_field = NSTextField.wrappingLabelWithString_("")
        text_field.setFrame_(NSMakeRect(
            _PADDING, _PADDING,
            _PANEL_WIDTH - 2 * _PADDING,
            _PANEL_MIN_HEIGHT - 2 * _PADDING,
        ))
        text_field.setFont_(NSFont.systemFontOfSize_(_FONT_SIZE))
        text_field.setTextColor_(_dynamic_text_color())
        text_field.setDrawsBackground_(False)
        text_field.setMaximumNumberOfLines_(0)  # unlimited

        content.addSubview_(text_field)
        panel.setContentView_(content)

        self._text_field = text_field
        self._content_view = content
        self._panel = panel
        self._current_text = ""

        # Center on screen
        screen = NSScreen.mainScreen()
        if screen:
            screen_frame = screen.frame()
            cx = screen_frame.origin.x + screen_frame.size.width / 2 - _PANEL_WIDTH / 2
            cy = screen_frame.origin.y + screen_frame.size.height / 2 - _PANEL_MIN_HEIGHT / 2
            panel.setFrameOrigin_((cx, cy))

        panel.orderFrontRegardless()
        logger.debug("Live transcription overlay shown")

    def hide(self) -> None:
        """Hide the overlay without destroying it."""
        if self._panel is not None:
            self._panel.orderOut_(None)

    def update_text(self, text: str) -> None:
        """Update the displayed transcription text and auto-resize."""
        if self._text_field is None:
            return

        from Foundation import NSMakeRect

        self._current_text = text
        self._text_field.setStringValue_(text)

        # Auto-resize height based on text content
        self._text_field.sizeToFit()
        text_height = self._text_field.frame().size.height
        new_height = max(_PANEL_MIN_HEIGHT, min(_PANEL_MAX_HEIGHT, text_height + 2 * _PADDING))

        if self._panel is not None:
            frame = self._panel.frame()
            # Adjust from bottom (keep top edge fixed)
            old_height = frame.size.height
            frame.origin.y += old_height - new_height
            frame.size.height = new_height
            self._panel.setFrame_display_(frame, True)

            # Resize content view to match
            if self._content_view is not None:
                self._content_view.setFrame_(
                    NSMakeRect(0, 0, _PANEL_WIDTH, new_height)
                )

            # Reposition text field
            self._text_field.setFrame_(NSMakeRect(
                _PADDING, _PADDING,
                _PANEL_WIDTH - 2 * _PADDING,
                new_height - 2 * _PADDING,
            ))

    def close(self) -> None:
        """Close and destroy the overlay."""
        if self._panel is not None:
            self._panel.orderOut_(None)
            self._panel = None
        self._content_view = None
        self._text_field = None
        self._close_delegate = None
        self._current_text = ""
        logger.debug("Live transcription overlay closed")
