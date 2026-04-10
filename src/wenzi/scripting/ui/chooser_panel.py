"""Chooser panel — Alfred/Raycast-style quick launcher.

Uses NSPanel + native AppKit views (NSTextField, NSTableView) for a
search-and-filter UI.  Keyboard-driven: type to filter, ↑↓ to navigate,
Enter to execute.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Dict, List, NamedTuple, Optional

from wenzi.i18n import t
from wenzi.scripting.sources import ChooserItem, ChooserSource
from wenzi.ui_helpers import get_frontmost_app, reactivate_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Borderless key-capable NSPanel subclass (lazy-created)
# ---------------------------------------------------------------------------
_KeyablePanel = None


def _get_keyable_panel_class():
    """Return an NSPanel subclass that can become key window when borderless."""
    global _KeyablePanel
    if _KeyablePanel is not None:
        return _KeyablePanel

    from AppKit import NSPanel

    class ChooserKeyablePanel(NSPanel):
        def canBecomeKeyWindow(self):
            return True

    _KeyablePanel = ChooserKeyablePanel
    return _KeyablePanel


# ---------------------------------------------------------------------------
# Panel delegate for resign-key (lazy-created)
# ---------------------------------------------------------------------------
_PanelDelegate = None


def _get_panel_delegate_class():
    """Return an NSObject subclass that closes the panel on focus loss."""
    global _PanelDelegate
    if _PanelDelegate is not None:
        return _PanelDelegate

    from Foundation import NSObject

    class ChooserPanelDelegate(NSObject):
        _panel_ref = None

        def windowDidResignKey_(self, notification):
            if self._panel_ref is not None:
                self._panel_ref._maybe_close()

        def windowDidBecomeKey_(self, notification):
            if self._panel_ref is not None:
                self._panel_ref._exit_calc_mode()

    _PanelDelegate = ChooserPanelDelegate
    return _PanelDelegate


# ---------------------------------------------------------------------------
# NSTextField delegate for search input (lazy-created)
# ---------------------------------------------------------------------------
_SearchFieldDelegate = None


def _get_search_field_delegate_class():
    """NSTextField delegate that forwards text changes to the panel."""
    global _SearchFieldDelegate
    if _SearchFieldDelegate is not None:
        return _SearchFieldDelegate

    import objc
    from Foundation import NSObject

    NSControlTextEditingDelegate = objc.protocolNamed(
        "NSControlTextEditingDelegate"
    )

    class ChooserSearchFieldDelegate(
        NSObject, protocols=[NSControlTextEditingDelegate]
    ):
        _panel_ref = None

        def controlTextDidChange_(self, notification):
            if self._panel_ref is not None:
                field = notification.object()
                text = str(field.stringValue())
                self._panel_ref._on_search_changed(text)

        def control_textView_doCommandBySelector_(
            self, control, textView, selector
        ):
            """Handle special keys in the search field."""
            if self._panel_ref is None:
                return False
            sel = str(selector)
            panel = self._panel_ref
            if sel == "moveUp:":
                panel._on_arrow_up()
                return True
            if sel == "moveDown:":
                panel._on_arrow_down()
                return True
            if sel == "insertNewline:":
                panel._on_enter()
                return True
            if sel == "cancelOperation:":
                panel._on_escape()
                return True
            if sel == "insertTab:":
                panel._on_tab()
                return True
            if sel == "deleteBackward:":
                # Let the field handle it normally (we just need to
                # detect Cmd+Delete for item deletion)
                return False
            return False

    _SearchFieldDelegate = ChooserSearchFieldDelegate
    return _SearchFieldDelegate


# ---------------------------------------------------------------------------
# NSTableView data source + delegate (lazy-created)
# ---------------------------------------------------------------------------
_TableDelegate = None


def _get_table_delegate_class():
    """Combined NSTableViewDataSource + NSTableViewDelegate."""
    global _TableDelegate
    if _TableDelegate is not None:
        return _TableDelegate

    import objc
    from Foundation import NSObject

    NSTableViewDataSource = objc.protocolNamed("NSTableViewDataSource")
    NSTableViewDelegate = objc.protocolNamed("NSTableViewDelegate")

    class ChooserTableDelegate(
        NSObject,
        protocols=[NSTableViewDataSource, NSTableViewDelegate],
    ):
        _panel_ref = None

        def numberOfRowsInTableView_(self, tableView):
            if self._panel_ref is None:
                return 0
            return len(self._panel_ref._current_items)

        def tableView_viewForTableColumn_row_(self, tableView, column, row):
            if self._panel_ref is None:
                return None
            return self._panel_ref._make_cell(tableView, row)

        def tableView_heightOfRow_(self, tableView, row):
            return 40.0

        def tableView_shouldSelectRow_(self, tableView, row):
            return True

        def tableView_rowViewForRow_(self, tableView, row):
            """Return a row view with selection border pre-applied."""
            from AppKit import NSColor, NSTableRowView
            from Foundation import NSMakeRect

            rv = NSTableRowView.alloc().initWithFrame_(NSMakeRect(0, 0, 0, 0))
            rv.setSelectionHighlightStyle_(-1)  # none — we draw our own
            rv.setWantsLayer_(True)
            # Apply border immediately if this row is selected
            if self._panel_ref is not None and row == self._panel_ref._selected_index:
                rv.layer().setBorderColor_(
                    NSColor.controlAccentColor().CGColor()
                )
                rv.layer().setBorderWidth_(1.5)
                rv.layer().setCornerRadius_(6.0)
            return rv

        def tableViewSelectionDidChange_(self, notification):
            if self._panel_ref is None:
                return
            tv = notification.object()
            row = tv.selectedRow()
            if row >= 0:
                self._panel_ref._selected_index = row
            self._panel_ref._update_selection_appearance(tv)

    _TableDelegate = ChooserTableDelegate
    return _TableDelegate


# ---------------------------------------------------------------------------
# Debounce timer helper (lazy-created)
# ---------------------------------------------------------------------------
_DebounceTimerHelper = None


def _get_debounce_timer_helper_class():
    """Return an NSObject subclass for NSTimer callbacks."""
    global _DebounceTimerHelper
    if _DebounceTimerHelper is not None:
        return _DebounceTimerHelper

    from Foundation import NSObject

    class ChooserDebounceTimerHelper(NSObject):
        _callback = None

        def fire_(self, _timer):
            if self._callback is not None:
                self._callback()

    _DebounceTimerHelper = ChooserDebounceTimerHelper
    return _DebounceTimerHelper


class _DebounceEntry(NamedTuple):
    """Per-source debounce state: timer, helper ref, and search args."""
    timer: object  # NSTimer
    helper: object  # NSObject helper (prevents GC)
    source: ChooserSource
    query: str
    generation: int


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class ChooserPanel:
    """Alfred/Raycast-style search launcher panel.

    Manages an NSPanel with native AppKit views, dispatches search queries to
    registered ChooserSource instances, and executes item actions.
    """

    _PANEL_WIDTH = 600
    _PANEL_WIDTH_WIDE = 960  # with preview panel
    _SEARCH_HEIGHT = 30  # 10px top + 24px field - 4px overlap
    _FOOTER_HEIGHT = 24
    _PANEL_COLLAPSED_HEIGHT = 30 + 24  # search + footer
    _PANEL_EXPANDED_HEIGHT = 400
    _PANEL_COMPACT_HEIGHT = 120
    _LIST_WIDTH = 520  # left list width when preview is visible
    _ROW_HEIGHT = 40
    _MAX_TOTAL_RESULTS = 50
    _DEFERRED_ACTION_DELAY = 0.15  # seconds to let previous app regain focus
    _DEFAULT_ASYNC_DEBOUNCE = 0.15  # seconds
    _DEFAULT_ASYNC_TIMEOUT = 5.0  # seconds

    def __init__(self, usage_tracker=None) -> None:
        self._panel = None
        self._search_field = None
        self._search_field_delegate = None
        self._table_view = None
        self._table_delegate = None
        self._scroll_view = None
        self._panel_delegate = None
        self._footer_left = None
        self._footer_right = None
        self._context_label = None
        self._context_text_view = None
        self._context_container = None
        self._empty_label = None
        self._spinner = None
        self._create_btn = None
        self._create_hint = None

        self._preview_scroll = None
        self._preview_text_view = None

        self._sources: Dict[str, ChooserSource] = {}
        self._current_items: List[ChooserItem] = []
        self._items_version: int = 0
        self._selected_index: int = -1
        self._prev_selected_row: int = -1
        self._closing: bool = False
        self._last_query: str = ""

        self._usage_tracker = usage_tracker
        self._query_history = None
        self._history_index: int = -1
        self._in_history_mode: bool = False
        self._on_close: Optional[Callable] = None
        self._pending_initial_query: Optional[str] = None
        self._pending_placeholder: Optional[str] = None
        self._event_callback: Optional[Callable] = None
        self._snippet_expander = None
        self._previous_app = None
        self._ql_panel = None
        self._calc_mode: bool = False
        self._calc_sticky: bool = False
        self._esc_tap = None
        self._esc_source = None
        self._show_preview: bool = False
        self._compact_results: bool = False
        self._switch_english: bool = True
        self._saved_input_source: Optional[str] = None
        self._active_source: Optional[ChooserSource] = None
        self._context_text: Optional[str] = None
        self._exclusive_source: Optional[str] = None
        self._search_generation: int = 0
        self._pending_async_count: int = 0
        self._loading_visible: bool = False
        self._debounce_state: Dict[str, _DebounceEntry] = {}
        self._is_expanded: bool = False
        self._delete_confirm_index: int = -1
        self._delete_confirm_timer = None

    # ------------------------------------------------------------------
    # Panel resize
    # ------------------------------------------------------------------

    def _update_panel_size(self) -> None:
        """Recalculate and apply panel size based on current state."""
        if self._panel is None:
            return
        if not self._is_expanded:
            h = self._PANEL_COLLAPSED_HEIGHT
        elif self._compact_results:
            h = self._PANEL_COMPACT_HEIGHT
        else:
            h = self._PANEL_EXPANDED_HEIGHT
        w = self._PANEL_WIDTH_WIDE if self._show_preview else self._PANEL_WIDTH
        self._apply_frame(w, h)
        self._update_preview_visibility()

    def _center_on_main_screen(self) -> None:
        """Reposition the panel to center-top of the current main screen."""
        if self._panel is None:
            return
        from wenzi.ui_helpers import screen_under_mouse

        screen = screen_under_mouse()
        if not screen:
            return
        sf = screen.frame()
        pf = self._panel.frame()
        x = sf.origin.x + (sf.size.width - pf.size.width) / 2
        y = sf.origin.y + sf.size.height - pf.size.height - 200
        self._panel.setFrameOrigin_((x, y))

    # ------------------------------------------------------------------
    # Panel reuse helpers
    # ------------------------------------------------------------------

    def _reconnect_panel_refs(self) -> None:
        """Restore _panel_ref back-references broken by close()."""
        if self._search_field_delegate is not None:
            self._search_field_delegate._panel_ref = self
        if self._table_delegate is not None:
            self._table_delegate._panel_ref = self
        if self._panel_delegate is not None:
            self._panel_delegate._panel_ref = self

    def _reset_panel_ui(
        self,
        initial_query: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> None:
        """Reset the UI state for a reused panel."""
        if self._search_field is not None:
            if initial_query:
                self._set_search_text(initial_query)
                self._pending_initial_query = None
            else:
                self._search_field.setStringValue_("")
            if placeholder:
                self._search_field.setPlaceholderString_(placeholder)
                self._pending_placeholder = None

        self._current_items = []
        self._selected_index = -1
        self._is_expanded = False
        self._show_preview = False
        self._compact_results = False
        self._reload_table()
        self._update_context_block()
        self._set_create_button_visible(False)
        self._update_footer_hints({})
        self._update_prefix_hints()
        self._update_panel_size()

    # ------------------------------------------------------------------
    # Source management
    # ------------------------------------------------------------------

    def register_source(self, source: ChooserSource) -> None:
        """Register a data source."""
        self._sources[source.name] = source
        logger.info("Chooser source registered: %s", source.name)

    def unregister_source(self, name: str) -> None:
        """Remove a data source by name."""
        self._sources.pop(name, None)

    def reset(self) -> None:
        """Clear all sources and reset trackers."""
        self._sources.clear()
        self._usage_tracker = None
        self._query_history = None

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _fire_event(self, event: str, *args) -> None:
        """Notify the API layer about a panel event."""
        if self._event_callback is not None:
            try:
                self._event_callback(event, *args)
            except Exception:
                logger.exception("Panel event callback error (%s)", event)

    def _maybe_close(self) -> None:
        """Close unless one of our panels (chooser or QL) is still key."""
        if self._closing:
            return

        def _check():
            if self._closing or self._panel is None:
                return
            try:
                from AppKit import NSApp

                key = NSApp.keyWindow()
                if key is not None and key == self._panel:
                    return
                if self._ql_panel is not None and self._ql_panel.is_key_window:
                    return
            except Exception:
                pass

            if self._should_pin_for_calc():
                self._enter_calc_mode()
                return

            self.close()

        from PyObjCTools import AppHelper

        AppHelper.callLater(0.1, _check)

    # ------------------------------------------------------------------
    # Calculator pin mode
    # ------------------------------------------------------------------

    def _has_calc_results(self) -> bool:
        """Check if current results include calculator items."""
        return any(item.item_id.startswith("calc:") for item in self._current_items)

    def _should_pin_for_calc(self) -> bool:
        """Whether the panel should stay visible for calculator use."""
        return self._has_calc_results() or self._calc_sticky

    def _enter_calc_mode(self) -> None:
        """Keep the panel open despite losing focus, and listen for ESC."""
        if self._calc_mode:
            return
        self._calc_mode = True
        self._previous_app = None
        self._start_esc_tap()
        logger.debug("Entered calculator pin mode")

    def _exit_calc_mode(self) -> None:
        """Stop the ESC listener and reset the calc-mode flag."""
        if not self._calc_mode:
            return
        self._calc_mode = False
        self._stop_esc_tap()
        logger.debug("Exited calculator pin mode")

    def _start_esc_tap(self) -> None:
        """Create a CGEventTap on the main run loop that swallows ESC."""
        try:
            import Quartz
        except ImportError:
            logger.warning("Quartz not available, cannot create ESC tap")
            self.close()
            return

        _kCGEventKeyDown = Quartz.kCGEventKeyDown
        _kCGKeyboardEventKeycode = Quartz.kCGKeyboardEventKeycode
        _ESC_KEYCODE = 53

        def _esc_callback(proxy, event_type, event, refcon):
            try:
                if event_type == Quartz.kCGEventTapDisabledByTimeout:
                    if self._esc_tap is not None:
                        Quartz.CGEventTapEnable(self._esc_tap, True)
                    return event
                if event_type == _kCGEventKeyDown:
                    keycode = Quartz.CGEventGetIntegerValueField(
                        event,
                        _kCGKeyboardEventKeycode,
                    )
                    if keycode == _ESC_KEYCODE:
                        if self._esc_tap is not None:
                            Quartz.CGEventTapEnable(self._esc_tap, False)
                        from PyObjCTools import AppHelper

                        AppHelper.callAfter(self.close)
                        return None
            except Exception:
                logger.warning("ESC tap callback error", exc_info=True)
            return event

        mask = Quartz.CGEventMaskBit(_kCGEventKeyDown)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            _esc_callback,
            None,
        )
        if tap is None:
            logger.warning("Failed to create ESC event tap — closing panel instead")
            self.close()
            return

        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetMain()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(tap, True)

        self._esc_tap = tap
        self._esc_source = source
        logger.debug("ESC event tap started on main run loop")

    def _stop_esc_tap(self) -> None:
        """Disable and remove the ESC event tap."""
        if self._esc_tap is None:
            return
        try:
            import Quartz

            Quartz.CGEventTapEnable(self._esc_tap, False)
            if self._esc_source is not None:
                loop = Quartz.CFRunLoopGetMain()
                Quartz.CFRunLoopRemoveSource(
                    loop,
                    self._esc_source,
                    Quartz.kCFRunLoopDefaultMode,
                )
        except Exception:
            logger.warning("Failed to stop ESC tap", exc_info=True)
        self._esc_tap = None
        self._esc_source = None
        logger.debug("ESC event tap stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_visible(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def show(
        self,
        on_close: Optional[Callable] = None,
        initial_query: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> None:
        """Show the chooser panel. Must run on main thread."""
        self._on_close = on_close
        self._pending_initial_query = initial_query
        self._pending_placeholder = placeholder

        if self._panel is not None and self._panel.isVisible():
            if initial_query:
                self._set_search_text(initial_query)
                self._on_search_changed(initial_query)
            elif self._search_field is not None:
                field_editor = self._panel.fieldEditor_forObject_(
                    True, self._search_field
                )
                if field_editor:
                    field_editor.selectAll_(None)
            self._panel.makeKeyAndOrderFront_(None)
            from AppKit import NSApp

            NSApp.activateIgnoringOtherApps_(True)
            return

        self._previous_app = get_frontmost_app()

        if self._panel is not None:
            # Reuse hidden panel
            self._reconnect_panel_refs()
            self._reset_panel_ui(initial_query, placeholder)
            self._center_on_main_screen()
        else:
            # First show — build from scratch
            self._build_panel()

        self._panel.makeKeyAndOrderFront_(None)

        from AppKit import NSApp

        NSApp.activateIgnoringOtherApps_(True)

        if self._snippet_expander is not None:
            self._snippet_expander.suppress()

        if self._switch_english:
            from wenzi.input_source import (
                get_current_input_source,
                is_english_input_source,
                select_english_input_source,
            )

            current = get_current_input_source()
            if current and not is_english_input_source(current):
                self._saved_input_source = current
                select_english_input_source()
            else:
                self._saved_input_source = None

        # Apply initial query after panel is visible
        if initial_query and self._search_field is not None:
            self._set_search_text(initial_query)
            self._on_search_changed(initial_query)

        # Apply placeholder
        if placeholder and self._search_field is not None:
            self._search_field.setPlaceholderString_(placeholder)
            self._pending_placeholder = None

        # Ensure footer hints are populated
        self._push_action_hints()
        self._update_prefix_hints()
        self._update_context_block()

        self._fire_event("open")

    def show_universal_action(
        self,
        context_text: str,
        exclusive_source: Optional[str] = None,
        on_close: Optional[Callable] = None,
        initial_query: Optional[str] = None,
        placeholder: Optional[str] = None,
    ) -> None:
        """Show the chooser in Universal Action mode with a context block."""
        self._context_text = context_text
        self._exclusive_source = exclusive_source
        self.show(on_close=on_close, initial_query=initial_query, placeholder=placeholder)

    def close(self) -> None:
        """Hide the chooser panel, preserving views for fast re-show."""
        if self._closing:
            return
        self._closing = True
        self._context_text = None
        self._exclusive_source = None

        self._cancel_all_debounce_timers()

        if self._snippet_expander is not None:
            self._snippet_expander.resume()
        self._calc_sticky = False
        self._exit_calc_mode()

        if self._ql_panel is not None:
            self._ql_panel.close()
            self._ql_panel = None

        # Break back-references to prevent retain cycles while hidden
        if self._search_field_delegate is not None:
            self._search_field_delegate._panel_ref = None
        if self._table_delegate is not None:
            self._table_delegate._panel_ref = None
        if self._panel_delegate is not None:
            self._panel_delegate._panel_ref = None

        if self._panel is not None:
            self._panel.orderOut_(None)

        self._current_items = []
        self._selected_index = -1
        self._history_index = -1
        self._in_history_mode = False
        self._show_preview = False
        self._compact_results = False
        self._is_expanded = False
        self._closing = False
        self._clear_delete_confirm()

        if self._saved_input_source is not None:
            from wenzi.input_source import select_input_source

            select_input_source(self._saved_input_source)
            self._saved_input_source = None

        from PyObjCTools import AppHelper

        previous_app = self._previous_app
        self._previous_app = None

        AppHelper.callAfter(reactivate_app, previous_app)

        self._fire_event("close")

        callback = self._on_close
        self._on_close = None
        if callback is not None:
            callback()

    def destroy(self) -> None:
        """Fully destroy the panel, releasing all resources."""
        self.close()

        if self._panel is not None:
            self._panel.setDelegate_(None)
            self._panel.orderOut_(None)
        self._panel = None
        self._search_field = None
        self._search_field_delegate = None
        self._table_view = None
        self._table_delegate = None
        self._scroll_view = None
        self._panel_delegate = None
        self._footer_left = None
        self._footer_right = None
        self._context_label = None
        self._context_text_view = None
        self._context_container = None
        self._empty_label = None
        self._spinner = None
        self._create_btn = None
        self._create_hint = None

        self._preview_scroll = None
        self._preview_text_view = None

    def toggle(self, on_close: Optional[Callable] = None) -> None:
        """Toggle the chooser panel visibility."""
        if self.is_visible:
            self.close()
        else:
            self.show(on_close=on_close)

    # ------------------------------------------------------------------
    # Search logic
    # ------------------------------------------------------------------

    def _do_search(self, query: str) -> None:
        """Run a search against sources and push results."""
        self._last_query = query
        self._search_generation += 1
        generation = self._search_generation
        source = None

        if self._exclusive_source and self._exclusive_source in self._sources:
            source = self._sources[self._exclusive_source]
        else:
            for src in self._sources.values():
                if src.prefix:
                    trigger = src.prefix + " "
                    if query.startswith(trigger):
                        source = src
                        query = query[len(trigger):]
                        break

        prev_source = self._active_source
        self._active_source = source
        if source != prev_source:
            has_create = source is not None and source.create_action is not None
            self._set_create_button_visible(has_create)
            show_right = source is None
            if self._footer_right is not None:
                self._footer_right.setHidden_(not show_right)

        if source is None:
            if not query.strip():
                self._current_items = []
                self._pending_async_count = 0
                self._calc_sticky = False
                self._compact_results = False
                self._show_preview = False
                self._is_expanded = False
                self._selected_index = -1
                self._reload_table()
                self._update_footer_hints({})
                self._set_loading(False)
                self._update_panel_size()
                return

        # Partition sources into sync and async
        if source is not None:
            if source.is_async:
                sync_sources = []
                async_sources = [source]
            else:
                sync_sources = [source]
                async_sources = []
        else:
            sorted_sources = sorted(
                self._sources.values(),
                key=lambda s: s.priority,
                reverse=True,
            )
            sync_sources: list = []
            async_sources: list = []
            for s in sorted_sources:
                if s.prefix is None and s.search is not None:
                    (async_sources if s.is_async else sync_sources).append(s)

        # Phase 1: Run sync sources immediately
        all_items: list = []
        for src in sync_sources:
            try:
                all_items.extend(src.search(query))
            except Exception:
                logger.exception("Chooser source %s search error", src.name)
        self._current_items = all_items[: self._MAX_TOTAL_RESULTS]

        if self._usage_tracker and self._current_items:
            self._boost_by_usage(query)

        # Update calculator sticky mode
        if self._has_calc_results():
            self._calc_sticky = True
        elif not any(ch.isdigit() for ch in query):
            self._calc_sticky = False

        show_preview = source.show_preview if source is not None else False
        if not self._compact_results:
            compact = bool(self._current_items) and all(
                item.item_id.startswith("calc:") for item in self._current_items
            )
        else:
            compact = True
        self._compact_results = compact
        self._show_preview = show_preview

        # Update UI
        self._selected_index = 0 if self._current_items else -1
        self._is_expanded = bool(self._current_items)
        self._reload_table()
        self._push_action_hints(source=source)
        self._update_panel_size()

        # Phase 2: Launch async sources
        self._cancel_all_debounce_timers()
        if async_sources:
            immediate = []
            debounced = []
            for asrc in async_sources:
                delay = self._get_debounce_delay(asrc)
                if delay > 0:
                    debounced.append((asrc, delay))
                else:
                    immediate.append(asrc)

            self._pending_async_count = len(immediate)
            if immediate:
                self._set_loading(True)
                for asrc in immediate:
                    self._launch_async_search(asrc, query, generation)

            if debounced:
                self._pending_async_count += len(debounced)
                self._set_loading(True)
                for asrc, delay in debounced:
                    self._schedule_debounced_search(asrc, query, generation, delay)
        else:
            self._set_loading(False)

    def _boost_by_usage(self, query: str) -> None:
        """Re-sort items by usage frequency while preserving source order."""
        tracker = self._usage_tracker
        scored = []
        for i, item in enumerate(self._current_items):
            usage = tracker.score(query, item.item_id) if item.item_id else 0
            scored.append((-usage, i, item))
        scored.sort(key=lambda x: (x[0], x[1]))
        self._current_items = [item for _, _, item in scored]

    @staticmethod
    def _default_action_hints():
        return {
            "enter": t("chooser.action.open"),
            "cmd_enter": t("chooser.action.reveal"),
        }

    _HINT_KEY_TO_MODIFIER = {
        "cmd_enter": "cmd",
        "alt_enter": "alt",
        "shift": "shift",
        "ctrl_enter": "ctrl",
    }

    @classmethod
    def _action_hints_to_modifier_map(cls, hints: dict) -> dict:
        """Convert action_hints keys to modifier→label map for JS."""
        return {
            mod: hints[key]
            for key, mod in cls._HINT_KEY_TO_MODIFIER.items()
            if hints.get(key)
        }

    def _push_action_hints(self, source=None) -> None:
        """Update footer hints based on active source."""
        if source is not None and source.action_hints:
            hints = source.action_hints
        elif self._compact_results and "calculator" in self._sources:
            hints = self._sources["calculator"].action_hints or self._default_action_hints()
        else:
            hints = self._default_action_hints()
        self._update_footer_hints(hints)

    # ------------------------------------------------------------------
    # Async source search
    # ------------------------------------------------------------------

    def _set_loading(self, visible: bool) -> None:
        """Update the loading spinner."""
        if visible == self._loading_visible:
            return
        self._loading_visible = visible
        if self._spinner is not None:
            if visible:
                self._spinner.startAnimation_(None)
                self._spinner.setHidden_(False)
            else:
                self._spinner.stopAnimation_(None)
                self._spinner.setHidden_(True)

    def _get_timeout(self, source: ChooserSource) -> float:
        if source.search_timeout is not None:
            return source.search_timeout
        return self._DEFAULT_ASYNC_TIMEOUT

    def _get_debounce_delay(self, source: ChooserSource) -> float:
        if source.debounce_delay is not None:
            return source.debounce_delay
        return self._DEFAULT_ASYNC_DEBOUNCE

    def _launch_async_search(
        self,
        source: ChooserSource,
        query: str,
        generation: int,
    ) -> None:
        """Submit an async source search to the shared event loop."""
        import wenzi.async_loop as _aloop

        timeout = self._get_timeout(source)

        async def _run():
            try:
                return await asyncio.wait_for(
                    source.search(query),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Async source %s timed out after %.1fs",
                    source.name,
                    timeout,
                )
                return []
            except asyncio.CancelledError:
                return []
            except Exception:
                logger.exception("Async source %s search error", source.name)
                return []

        def _on_future_done(future):
            try:
                items = future.result() or []
            except Exception:
                items = []
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._merge_async_results, source, items, generation)

        try:
            loop = _aloop.get_loop()
            future = asyncio.run_coroutine_threadsafe(_run(), loop)
            future.add_done_callback(_on_future_done)
        except RuntimeError:
            logger.error("Async loop unavailable for source %s", source.name)
            self._pending_async_count = max(0, self._pending_async_count - 1)
            if self._pending_async_count == 0:
                self._set_loading(False)

    def _merge_async_results(
        self,
        source: ChooserSource,
        items: list,
        generation: int,
    ) -> None:
        """Merge async source results on the main thread."""
        if generation != self._search_generation:
            return

        self._pending_async_count = max(0, self._pending_async_count - 1)

        pushed = False
        if items:
            remaining = self._MAX_TOTAL_RESULTS - len(self._current_items)
            if remaining > 0:
                self._current_items.extend(items[:remaining])

            if self._usage_tracker and self._current_items:
                self._boost_by_usage(self._last_query)

            # Preserve selection
            old_sel = self._selected_index
            self._is_expanded = bool(self._current_items)
            self._reload_table()
            if old_sel >= 0:
                self._selected_index = min(old_sel, len(self._current_items) - 1)
            elif self._current_items:
                self._selected_index = 0
            self._select_row(self._selected_index)
            self._push_action_hints(
                source=source if self._active_source is source else None
            )
            self._update_panel_size()
            pushed = True

        if self._pending_async_count == 0:
            if generation == self._search_generation:
                self._set_loading(False)
            if not pushed:
                self._reload_table()
                self._push_action_hints(source=self._active_source)
                self._update_panel_size()

    # ------------------------------------------------------------------
    # Debounced async search
    # ------------------------------------------------------------------

    def _cancel_all_debounce_timers(self) -> None:
        for entry in self._debounce_state.values():
            entry.timer.invalidate()
        self._debounce_state.clear()

    def _schedule_debounced_search(
        self,
        source: ChooserSource,
        query: str,
        generation: int,
        delay: float,
    ) -> None:
        name = source.name

        old = self._debounce_state.pop(name, None)
        if old is not None:
            old.timer.invalidate()

        HelperClass = _get_debounce_timer_helper_class()
        helper = HelperClass.alloc().init()
        helper._callback = lambda n=name: self._execute_debounced_search(n)

        from Foundation import NSTimer

        timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay,
            helper,
            b"fire:",
            None,
            False,
        )

        self._debounce_state[name] = _DebounceEntry(
            timer=timer,
            helper=helper,
            source=source,
            query=query,
            generation=generation,
        )

    def _execute_debounced_search(self, source_name: str) -> None:
        entry = self._debounce_state.pop(source_name, None)
        if entry is None:
            return
        if entry.generation != self._search_generation:
            return
        self._launch_async_search(entry.source, entry.query, entry.generation)

    # ------------------------------------------------------------------
    # Keyboard event handlers (called from search field delegate)
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        """Handle search field text change."""
        if self._in_history_mode:
            self._in_history_mode = False
            self._history_index = -1
        self._do_search(text)

    def _on_arrow_up(self) -> None:
        """Handle ↑ key."""
        if self._in_history_mode or (
            self._get_search_text() == "" and not self._current_items
        ):
            self._history_navigate(1)
            return
        if self._selected_index > 0:
            self._selected_index -= 1
            self._select_row(self._selected_index)

    def _on_arrow_down(self) -> None:
        """Handle ↓ key."""
        if self._in_history_mode:
            self._history_navigate(-1)
            return
        if self._selected_index < len(self._current_items) - 1:
            self._selected_index += 1
            self._select_row(self._selected_index)

    def _on_enter(self, modifier: Optional[str] = None) -> None:
        """Handle Enter key."""
        self._in_history_mode = False
        if 0 <= self._selected_index < len(self._current_items):
            self._execute_item(
                self._selected_index,
                modifier=modifier,
            )

    def _on_escape(self) -> None:
        """Handle Escape key."""
        if self._ql_panel is not None and self._ql_panel.is_visible:
            self._ql_panel.close()
            return
        self.close()

    def _on_tab(self) -> None:
        """Handle Tab key."""
        if 0 <= self._selected_index < len(self._current_items):
            self._handle_tab_complete(self._selected_index)

    def _get_search_text(self) -> str:
        """Get the current search field text."""
        if self._search_field is not None:
            return str(self._search_field.stringValue())
        return ""

    def _set_search_text(self, text: str) -> None:
        """Set search field text with cursor at end (no selection)."""
        if self._search_field is None or self._panel is None:
            return
        self._search_field.setStringValue_(text)
        # Move cursor to end instead of selecting all
        editor = self._panel.fieldEditor_forObject_(True, self._search_field)
        if editor:
            from Foundation import NSRange

            editor.setSelectedRange_(NSRange(len(text), 0))

    # ------------------------------------------------------------------
    # History navigation
    # ------------------------------------------------------------------

    def _history_navigate(self, direction: int) -> None:
        """Navigate query history. direction=1 means older, -1 means newer."""
        if self._query_history is None:
            return
        history = self._query_history.entries()
        if not history:
            return

        new_index = self._history_index + direction
        if new_index < 0:
            self._history_index = -1
            self._in_history_mode = False
            if self._search_field is not None:
                self._search_field.setStringValue_("")
            self._current_items = []
            self._selected_index = -1
            self._is_expanded = False
            self._reload_table()
            self._update_panel_size()
            return
        if new_index >= len(history):
            return

        self._history_index = new_index
        self._in_history_mode = True
        query = history[new_index]
        self._set_search_text(query)
        self._do_search(query)

    # ------------------------------------------------------------------
    # Tab completion
    # ------------------------------------------------------------------

    def _handle_tab_complete(self, index: int) -> None:
        """Handle Tab key: call active source's complete callback."""
        query = self._last_query or ""

        source = None
        prefix_str = ""
        for src in self._sources.values():
            if src.prefix:
                trigger = src.prefix + " "
                if query.startswith(trigger):
                    source = src
                    prefix_str = trigger
                    break

        if source is None or source.complete is None:
            return

        stripped_query = query[len(prefix_str):]
        if not (0 <= index < len(self._current_items)):
            return

        item = self._current_items[index]
        try:
            completed = source.complete(stripped_query, item)
        except Exception:
            logger.exception("Tab complete error for source %s", source.name)
            return

        if completed is None:
            return

        new_query = prefix_str + completed
        self._set_search_text(new_query)
        self._on_search_changed(new_query)

    # ------------------------------------------------------------------
    # Create item
    # ------------------------------------------------------------------

    def _handle_create_item(self) -> None:
        """Dispatch the create action for the active source."""
        source = self._active_source
        if source is None or source.create_action is None:
            return

        query = self._get_search_text().strip()
        space_idx = query.find(" ")
        stripped = query[space_idx + 1:].strip() if space_idx >= 0 else ""

        self.close()

        from PyObjCTools import AppHelper

        def _run_create():
            try:
                source.create_action(stripped)
            except Exception:
                logger.exception(
                    "Chooser create action failed for source %r",
                    source.name,
                )

        AppHelper.callAfter(_run_create)

    # ------------------------------------------------------------------
    # Delete item
    # ------------------------------------------------------------------

    def _delete_item(self, index: int, version: int = 0) -> None:
        """Delete an item and refresh the list."""
        if version and version != self._items_version:
            return
        if 0 <= index < len(self._current_items):
            item = self._current_items[index]
            if item.delete_action is not None:
                try:
                    item.delete_action()
                except Exception:
                    logger.exception(
                        "Chooser delete action failed for %r",
                        item.title,
                    )
                self._fire_event(
                    "delete",
                    {
                        "title": item.title,
                        "subtitle": item.subtitle,
                        "item_id": item.item_id,
                    },
                )
                self._current_items.pop(index)
                self._items_version += 1
                self._selected_index = min(index, len(self._current_items) - 1)
                self._reload_table()
                self._select_row(self._selected_index)

    def _clear_delete_confirm(self) -> None:
        """Clear the delete confirmation state."""
        if self._delete_confirm_timer is not None:
            self._delete_confirm_timer.invalidate()
            self._delete_confirm_timer = None
        self._delete_confirm_index = -1

    # ------------------------------------------------------------------
    # Execute item
    # ------------------------------------------------------------------

    def _execute_item(
        self,
        index: int,
        version: int = 0,
        modifier: Optional[str] = None,
    ) -> None:
        """Execute item action."""
        if version and version != self._items_version:
            logger.debug("Stale execute (v%d != v%d), ignored", version, self._items_version)
            return
        if 0 <= index < len(self._current_items):
            item = self._current_items[index]

            action = item.action
            if modifier and item.modifiers and modifier in item.modifiers:
                mod_action = item.modifiers[modifier]
                if mod_action.action is not None:
                    action = mod_action.action

            if self._usage_tracker and item.item_id:
                self._usage_tracker.record(self._last_query, item.item_id)

            if self._query_history and self._last_query and self._last_query.strip():
                self._query_history.record(self._last_query)

            self._fire_event(
                "select",
                {
                    "title": item.title,
                    "subtitle": item.subtitle,
                    "item_id": item.item_id,
                },
            )

            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.close)
            if action is not None:
                import threading

                def _deferred():
                    import time

                    time.sleep(self._DEFERRED_ACTION_DELAY)
                    try:
                        action()
                    except Exception:
                        logger.exception("Chooser action failed for %r", item.title)

                threading.Thread(target=_deferred, daemon=True).start()

    def _reveal_item(self, index: int, version: int = 0) -> None:
        """Execute the secondary action (Cmd+Enter)."""
        if version and version != self._items_version:
            return
        if 0 <= index < len(self._current_items):
            item = self._current_items[index]
            from PyObjCTools import AppHelper

            if item.reveal_path:
                import subprocess

                subprocess.Popen(  # noqa: S603
                    ["open", "-R", item.reveal_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                AppHelper.callAfter(self.close)
            elif item.secondary_action is not None:
                AppHelper.callAfter(self.close)
                try:
                    item.secondary_action()
                except Exception:
                    logger.exception("Chooser secondary action failed for %r", item.title)

    def _toggle_quicklook(self, is_open: bool, index: int) -> None:
        """Toggle Quick Look preview for the selected item."""
        if is_open:
            if 0 <= index < len(self._current_items):
                item = self._current_items[index]
                path = item.reveal_path
                if path and os.path.exists(path):
                    if self._ql_panel is None:
                        from wenzi.scripting.ui.quicklook_panel import QuickLookPanel

                        self._ql_panel = QuickLookPanel(
                            on_resign_key=self._maybe_close,
                            on_shift_toggle=self._on_ql_shift_toggle,
                        )
                    self._ql_panel.show(path, anchor_panel=self._panel)
                    return
        if self._ql_panel is not None:
            self._ql_panel.close()

    def _on_ql_shift_toggle(self) -> None:
        """Called when Shift is tapped while the QL panel has focus."""
        if self._ql_panel is not None:
            self._ql_panel.close()

    def _update_quicklook(self, index: int) -> None:
        """Update Quick Look preview when navigating with ↑↓."""
        if self._ql_panel is None or not self._ql_panel.is_visible:
            return
        if 0 <= index < len(self._current_items):
            item = self._current_items[index]
            path = item.reveal_path
            if path and os.path.exists(path):
                self._ql_panel.update(path)


    # ------------------------------------------------------------------
    # Native UI helpers
    # ------------------------------------------------------------------

    def _reload_table(self) -> None:
        """Reload the table view data and update empty state."""
        self._items_version += 1
        if self._table_view is not None:
            self._table_view.sizeLastColumnToFit()
            self._table_view.reloadData()
            if self._selected_index >= 0:
                # Select row — border is already applied in
                # tableView_rowViewForRow_ at creation time.
                from Foundation import NSIndexSet

                self._table_view.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(self._selected_index), False
                )
                self._table_view.scrollRowToVisible_(self._selected_index)
        # Toggle empty label vs table
        has_items = bool(self._current_items)
        query = self._get_search_text().strip()
        if self._scroll_view is not None:
            self._scroll_view.setHidden_(not has_items)
        if self._empty_label is not None:
            if not has_items and (query or self._exclusive_source):
                self._empty_label.setStringValue_(t("chooser.empty.no_results"))
                self._empty_label.setHidden_(False)
            elif not has_items:
                self._empty_label.setStringValue_(t("chooser.empty.type_to_search"))
                self._empty_label.setHidden_(not self._is_expanded)
            else:
                self._empty_label.setHidden_(True)
        if self._show_preview:
            self._update_preview_content()

    def _select_row(self, row: int) -> None:
        """Select a row in the table view and scroll it visible."""
        if self._table_view is None or row < 0:
            return
        from Foundation import NSIndexSet

        self._table_view.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(row), False
        )
        self._table_view.scrollRowToVisible_(row)
        self._update_selection_appearance(self._table_view)

    def _update_selection_appearance(self, tableView) -> None:
        """Apply selection border — only touches the old and new rows (O(1))."""
        if tableView is None:
            return
        from AppKit import NSColor

        accent = NSColor.controlAccentColor()
        selected = tableView.selectedRow()
        prev = self._prev_selected_row
        self._prev_selected_row = selected

        for row in (prev, selected):
            if row < 0:
                continue
            rv = tableView.rowViewAtRow_makeIfNecessary_(row, False)
            if rv is None:
                continue
            rv.setWantsLayer_(True)
            layer = rv.layer()
            if row == selected:
                layer.setBorderColor_(accent.CGColor())
                layer.setBorderWidth_(1.5)
                layer.setCornerRadius_(6.0)
            else:
                layer.setBorderWidth_(0)
                layer.setCornerRadius_(0)

        if self._show_preview:
            self._update_preview_content()

    def _set_create_button_visible(self, visible: bool) -> None:
        """Show/hide the create button."""
        if self._create_btn is not None:
            self._create_btn.setHidden_(not visible)
        if self._create_hint is not None:
            self._create_hint.setHidden_(not visible)

    def _update_preview_visibility(self) -> None:
        """Show/hide the preview panel based on _show_preview state."""
        if self._preview_scroll is None:
            return
        visible = self._show_preview and self._is_expanded
        self._preview_scroll.setHidden_(not visible)
        if visible:
            self._sync_preview_text_width()
            self._update_preview_content()

    def _sync_preview_text_width(self) -> None:
        """Match the text view width to the scroll view's content area."""
        if self._preview_scroll is None or self._preview_text_view is None:
            return
        content_size = self._preview_scroll.contentSize()
        tv = self._preview_text_view
        frame = tv.frame()
        if round(frame.size.width) != round(content_size.width):
            from Foundation import NSMakeRect
            tv.setFrame_(NSMakeRect(0, 0, content_size.width, frame.size.height))
            tv.textContainer().setContainerSize_(
                (content_size.width - 24, 1e7)  # 24 = 2 * textContainerInset width
            )

    def _update_preview_content(self) -> None:
        """Update preview text for the currently selected item."""
        if self._preview_text_view is None:
            return
        if not (0 <= self._selected_index < len(self._current_items)):
            self._preview_text_view.setString_("")
            return
        item = self._current_items[self._selected_index]
        preview = item.preview
        if preview is not None:
            if callable(preview):
                try:
                    preview = preview()
                except Exception:
                    preview = None
                item.preview = preview  # cache
        if preview is None:
            self._preview_text_view.setString_("")
            return
        if isinstance(preview, dict):
            content = preview.get("content", "")
            self._preview_text_view.setString_(str(content))
        else:
            self._preview_text_view.setString_(str(preview))

    def _update_context_block(self) -> None:
        """Show/hide the Universal Action context block."""
        if self._context_container is None:
            return
        if self._context_text is not None:
            self._context_container.setHidden_(False)
            if self._context_label is not None:
                self._context_label.setStringValue_(t("chooser.ua.context_label"))
            if self._context_text_view is not None:
                self._context_text_view.setStringValue_(self._context_text)
        else:
            self._context_container.setHidden_(True)

    def _update_footer_hints(self, hints: dict) -> None:
        """Update footer left with action hints."""
        if self._footer_left is None:
            return
        parts = ["↑↓ " + t("chooser.footer.navigate")]
        if hints.get("enter"):
            parts.append("↵ " + hints["enter"])
        if hints.get("cmd_enter"):
            parts.append("⌘↵ " + hints["cmd_enter"])
        if hints.get("alt_enter"):
            parts.append("⌥↵ " + hints["alt_enter"])
        if hints.get("delete"):
            parts.append("⌘⌫ " + hints["delete"])
        if hints.get("shift"):
            parts.append("⇧ " + hints["shift"])
        if hints.get("tab"):
            parts.append("⇥ " + hints["tab"])
        parts.append("Esc " + t("chooser.footer.close"))
        self._footer_left.setStringValue_("  ".join(parts))

    def _update_prefix_hints(self) -> None:
        """Update footer right with prefix source hints."""
        if self._footer_right is None:
            return
        hints = []
        for src in self._sources.values():
            if src.prefix:
                label = src.display_name or src.name
                hints.append(f"{src.prefix} {label}")
        self._footer_right.setStringValue_("  ".join(hints))

    # ------------------------------------------------------------------
    # Cell construction for NSTableView
    # ------------------------------------------------------------------

    def _make_cell(self, tableView, row: int):
        """Build a cell view for the given row."""
        from AppKit import (
            NSColor,
            NSFont,
            NSImage,
            NSImageView,
            NSLineBreakByTruncatingTail,
            NSTextField,
        )
        from Foundation import NSMakeRect

        if row < 0 or row >= len(self._current_items):
            return None

        item = self._current_items[row]

        # Read actual column width (auto-sized by NSTableView to fit clip view)
        cols = tableView.tableColumns()
        cw = int(cols[0].width()) if cols and len(cols) > 0 else self._PANEL_WIDTH
        shortcut_w = 36
        shortcut_x = cw - shortcut_w - 6
        text_w = shortcut_x - 4 - 50  # 50 = icon area left edge

        # Reuse or create cell
        cell_id = "ChooserCell"
        cell = tableView.makeViewWithIdentifier_owner_(cell_id, None)
        if cell is None:
            from AppKit import NSTableCellView

            cell = NSTableCellView.alloc().initWithFrame_(
                NSMakeRect(0, 0, cw, self._ROW_HEIGHT)
            )
            cell.setIdentifier_(cell_id)

            # Icon image view
            icon_view = NSImageView.alloc().initWithFrame_(
                NSMakeRect(10, 4, 32, 32)
            )
            icon_view.setTag_(100)
            cell.addSubview_(icon_view)

            # Title
            title_field = NSTextField.labelWithString_("")
            title_field.setFrame_(NSMakeRect(50, 18, text_w, 18))
            title_field.setFont_(NSFont.systemFontOfSize_weight_(14, 0.3))
            title_field.setLineBreakMode_(NSLineBreakByTruncatingTail)
            title_field.setTextColor_(NSColor.labelColor())
            title_field.setTag_(101)
            cell.addSubview_(title_field)

            # Subtitle
            sub_field = NSTextField.labelWithString_("")
            sub_field.setFrame_(NSMakeRect(50, 2, text_w, 14))
            sub_field.setFont_(NSFont.systemFontOfSize_(11))
            sub_field.setLineBreakMode_(NSLineBreakByTruncatingTail)
            sub_field.setTextColor_(NSColor.secondaryLabelColor())
            sub_field.setTag_(102)
            cell.addSubview_(sub_field)

            # Shortcut hint (⌘N)
            shortcut_field = NSTextField.labelWithString_("")
            shortcut_field.setFrame_(NSMakeRect(shortcut_x, 12, shortcut_w, 14))
            shortcut_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, 0.0))
            shortcut_field.setAlignment_(2)  # right
            shortcut_field.setTextColor_(NSColor.tertiaryLabelColor())
            shortcut_field.setTag_(104)
            cell.addSubview_(shortcut_field)

            # Badge on icon corner
            badge_icon_field = NSTextField.labelWithString_("")
            badge_icon_field.setFrame_(NSMakeRect(30, 0, 16, 14))
            badge_icon_field.setFont_(NSFont.systemFontOfSize_weight_(9, 0.6))
            badge_icon_field.setAlignment_(1)  # center
            badge_icon_field.setTextColor_(NSColor.whiteColor())
            badge_icon_field.setBackgroundColor_(NSColor.systemBlueColor())
            badge_icon_field.setDrawsBackground_(True)
            badge_icon_field.setBezeled_(False)
            badge_icon_field.setTag_(105)
            cell.addSubview_(badge_icon_field)

        # Populate cell
        icon_view = cell.viewWithTag_(100)
        title_field = cell.viewWithTag_(101)
        sub_field = cell.viewWithTag_(102)
        shortcut_field = cell.viewWithTag_(104)
        badge_icon_field = cell.viewWithTag_(105)

        # Re-layout for current width (reused cells may have different width)
        title_field.setFrame_(NSMakeRect(50, 18 if item.subtitle else 11, text_w, 18))
        sub_field.setFrame_(NSMakeRect(50, 2, text_w, 14))
        shortcut_field.setFrame_(NSMakeRect(shortcut_x, 12, shortcut_w, 14))

        title_field.setStringValue_(item.title)

        if item.subtitle:
            sub_field.setStringValue_(item.subtitle)
            sub_field.setHidden_(False)
        else:
            sub_field.setHidden_(True)

        if item.icon:
            icon_url = item.icon
            if icon_url.startswith("file://"):
                img = NSImage.alloc().initWithContentsOfFile_(icon_url[7:])
            elif icon_url.startswith("data:"):
                from Foundation import NSData

                try:
                    _, b64data = icon_url.split(",", 1)
                    import base64

                    raw = base64.b64decode(b64data)
                    data = NSData.dataWithBytes_length_(raw, len(raw))
                    img = NSImage.alloc().initWithData_(data)
                except Exception:
                    img = None
            else:
                img = NSImage.alloc().initWithContentsOfFile_(icon_url)
            if img is not None:
                icon_view.setImage_(img)
                icon_view.setHidden_(False)
            else:
                icon_view.setImage_(None)
                icon_view.setHidden_(True)
        else:
            icon_view.setImage_(None)
            icon_view.setHidden_(True)

        if item.icon_badge:
            badge_icon_field.setStringValue_(item.icon_badge)
            badge_icon_field.setHidden_(False)
        else:
            badge_icon_field.setHidden_(True)

        if row < 9:
            shortcut_field.setStringValue_(f"⌘{row + 1}")
            shortcut_field.setHidden_(False)
        else:
            shortcut_field.setHidden_(True)

        return cell

    # ------------------------------------------------------------------
    # Panel construction (native AppKit)
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_edit_menu() -> None:
        from wenzi.ui.result_window_web import _ensure_edit_menu

        _ensure_edit_menu()

    def _build_panel(self) -> None:
        """Create NSPanel + native AppKit views."""
        from AppKit import (
            NSBackingStoreBuffered,
            NSColor,
            NSFont,
            NSLineBreakByTruncatingTail,
            NSProgressIndicator,
            NSProgressIndicatorSpinningStyle,
            NSScrollView,
            NSStatusWindowLevel,
            NSTableColumn,
            NSTableView,
            NSTextField,
            NSVisualEffectView,
        )
        from Foundation import NSMakeRect

        PanelClass = _get_keyable_panel_class()
        initial_width = self._PANEL_WIDTH
        initial_height = self._PANEL_COLLAPSED_HEIGHT

        panel = PanelClass.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, initial_width, initial_height),
            0,  # Borderless
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel + 1)
        panel.setOpaque_(False)
        panel.setHasShadow_(True)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setMovableByWindowBackground_(False)
        panel.setCollectionBehavior_(1 << 4)  # canJoinAllSpaces
        panel.setBackgroundColor_(NSColor.clearColor())

        self._ensure_edit_menu()

        # Panel delegate (close on focus loss)
        delegate_cls = _get_panel_delegate_class()
        delegate = delegate_cls.alloc().init()
        delegate._panel_ref = self
        panel.setDelegate_(delegate)
        self._panel_delegate = delegate

        # Replace contentView with NSVisualEffectView directly — same as
        # macOS system menus.  The ve_view IS the contentView; all child
        # views are added to it at full opacity while the view itself
        # provides the frosted-glass blur.
        ve_view = NSVisualEffectView.alloc().initWithFrame_(
            panel.contentView().bounds()
        )
        ve_view.setAutoresizingMask_(0x12)
        ve_view.setBlendingMode_(0)  # behindWindow
        ve_view.setMaterial_(5)  # menu — same as system menus
        ve_view.setState_(1)  # active
        ve_view.setWantsLayer_(True)
        ve_view.layer().setCornerRadius_(12.0)
        ve_view.layer().setMasksToBounds_(True)
        panel.setContentView_(ve_view)
        container = ve_view  # all child views go here

        # We'll use a vertical layout tracked manually.
        # Layout origin: top-left in flipped coordinates is easier,
        # but NSView is not flipped by default. We'll compute from top.
        y_cursor = [0]  # mutable for closure; tracks from top

        def top_y(h):
            """Return the y origin for a view of height h at current cursor, then advance."""
            # In non-flipped coords, y=0 is bottom.
            # We'll lay out after we know the panel height.
            # For now, just track offsets from top.
            y = y_cursor[0]
            y_cursor[0] += h
            return y

        # --- Context block (Universal Action) ---
        ctx_height = 50
        top_y(ctx_height)
        ctx_container = self._make_box(
            container, NSMakeRect(0, 0, initial_width, ctx_height)
        )
        ctx_container.setHidden_(True)

        ctx_label = NSTextField.labelWithString_(t("chooser.ua.context_label"))
        ctx_label.setFrame_(NSMakeRect(14, ctx_height - 18, initial_width - 28, 14))
        ctx_label.setFont_(NSFont.systemFontOfSize_weight_(11, 0.0))
        ctx_label.setTextColor_(NSColor.secondaryLabelColor())
        ctx_container.addSubview_(ctx_label)

        ctx_text = NSTextField.labelWithString_("")
        ctx_text.setFrame_(NSMakeRect(14, 4, initial_width - 28, ctx_height - 22))
        ctx_text.setFont_(NSFont.systemFontOfSize_(13))
        ctx_text.setTextColor_(NSColor.labelColor())
        ctx_text.setLineBreakMode_(NSLineBreakByTruncatingTail)
        ctx_text.setMaximumNumberOfLines_(3)
        ctx_container.addSubview_(ctx_text)

        self._context_container = ctx_container
        self._context_label = ctx_label
        self._context_text_view = ctx_text

        # --- Search input ---
        search_height = self._SEARCH_HEIGHT
        top_y(search_height)

        # Search text field
        search_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(14, 0, initial_width - 80, 24)
        )
        search_field.setPlaceholderString_(t("chooser.placeholder"))
        search_field.setBordered_(False)
        search_field.setDrawsBackground_(False)
        search_field.setFocusRingType_(1)  # none
        search_field.setFont_(NSFont.systemFontOfSize_(16))
        search_field.setTextColor_(NSColor.labelColor())

        # Search field delegate
        sfd_cls = _get_search_field_delegate_class()
        sfd = sfd_cls.alloc().init()
        sfd._panel_ref = self
        search_field.setDelegate_(sfd)
        self._search_field_delegate = sfd

        container.addSubview_(search_field)
        self._search_field = search_field

        # Spinner
        spinner = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(initial_width - 76, (search_height - 16) / 2, 16, 16)
        )
        spinner.setStyle_(NSProgressIndicatorSpinningStyle)
        spinner.setControlSize_(1)  # small
        spinner.setDisplayedWhenStopped_(False)
        spinner.setHidden_(True)
        container.addSubview_(spinner)
        self._spinner = spinner

        # Create button
        create_btn = NSTextField.labelWithString_("+")
        create_btn.setFrame_(NSMakeRect(initial_width - 54, (search_height - 24) / 2, 24, 24))
        create_btn.setFont_(NSFont.systemFontOfSize_(18))
        create_btn.setAlignment_(1)  # center
        create_btn.setTextColor_(NSColor.secondaryLabelColor())
        create_btn.setHidden_(True)
        container.addSubview_(create_btn)
        self._create_btn = create_btn

        create_hint = NSTextField.labelWithString_("⌘N")
        create_hint.setFrame_(NSMakeRect(initial_width - 32, (search_height - 14) / 2, 28, 14))
        create_hint.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, 0.0))
        create_hint.setTextColor_(NSColor.tertiaryLabelColor())
        create_hint.setHidden_(True)
        container.addSubview_(create_hint)
        self._create_hint = create_hint

        # --- Result area (table + empty label) ---
        # This is sized dynamically. We'll set frames in _layout_views.

        # Empty label
        empty_label = NSTextField.labelWithString_(t("chooser.empty.type_to_search"))
        empty_label.setFont_(NSFont.systemFontOfSize_(13))
        empty_label.setTextColor_(NSColor.secondaryLabelColor())
        empty_label.setAlignment_(1)  # center
        empty_label.setHidden_(True)
        container.addSubview_(empty_label)
        self._empty_label = empty_label

        # Table view
        table = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, initial_width, 300)
        )
        column = NSTableColumn.alloc().initWithIdentifier_("main")
        column.setWidth_(initial_width)
        column.setResizingMask_(1)  # auto-resize with table
        table.addTableColumn_(column)
        table.setColumnAutoresizingStyle_(4)  # last column only (= our only column)
        table.setHeaderView_(None)
        table.setRowHeight_(self._ROW_HEIGHT)
        table.setSelectionHighlightStyle_(-1)  # none — we draw custom selection
        table.setBackgroundColor_(NSColor.clearColor())
        table.setGridStyleNone_(True) if hasattr(table, 'setGridStyleNone_') else None
        table.setIntercellSpacing_((0, 0))

        # Table delegate
        td_cls = _get_table_delegate_class()
        td = td_cls.alloc().init()
        td._panel_ref = self
        table.setDataSource_(td)
        table.setDelegate_(td)
        self._table_delegate = td
        self._table_view = table

        # Scroll view
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, initial_width, 300)
        )
        scroll.setDocumentView_(table)
        scroll.setHasVerticalScroller_(True)
        scroll.setDrawsBackground_(False)
        scroll.setAutohidesScrollers_(True)
        scroll.setHidden_(True)
        container.addSubview_(scroll)
        self._scroll_view = scroll

        # --- Preview panel (right side, for text preview) ---
        from AppKit import NSTextView

        preview_text = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 300, 300)
        )
        preview_text.setEditable_(False)
        preview_text.setSelectable_(True)
        preview_text.setDrawsBackground_(False)
        preview_text.setFont_(NSFont.monospacedSystemFontOfSize_weight_(12, 0.0))
        preview_text.setTextColor_(NSColor.labelColor())
        # Fixed insets: 12px horizontal, 8px vertical
        preview_text.setTextContainerInset_((12, 8))
        preview_text.textContainer().setLineFragmentPadding_(0)
        # Auto-resize width with scroll view's clip view
        preview_text.setAutoresizingMask_(1)  # width sizable
        preview_text.textContainer().setWidthTracksTextView_(True)
        preview_text.setMinSize_((0, 0))
        preview_text.setMaxSize_((1e7, 1e7))
        preview_text.setHorizontallyResizable_(False)
        preview_text.setVerticallyResizable_(True)

        preview_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, 300, 300)
        )
        preview_scroll.setDocumentView_(preview_text)
        preview_scroll.setHasVerticalScroller_(True)
        preview_scroll.setDrawsBackground_(False)
        preview_scroll.setAutohidesScrollers_(True)
        preview_scroll.setHidden_(True)
        # Separator line on left edge
        preview_scroll.setWantsLayer_(True)
        preview_scroll.layer().setBorderColor_(
            NSColor.separatorColor().CGColor()
        )
        preview_scroll.layer().setBorderWidth_(0)  # set via layout
        container.addSubview_(preview_scroll)
        self._preview_scroll = preview_scroll
        self._preview_text_view = preview_text

        # --- Footer ---
        footer_left = NSTextField.labelWithString_(" ")
        footer_left.setFrame_(NSMakeRect(14, 4, initial_width / 2 - 20, 16))
        footer_left.setFont_(NSFont.systemFontOfSize_(11))
        footer_left.setTextColor_(NSColor.secondaryLabelColor())
        footer_left.setLineBreakMode_(NSLineBreakByTruncatingTail)
        container.addSubview_(footer_left)
        self._footer_left = footer_left

        footer_right = NSTextField.labelWithString_(" ")
        footer_right.setFrame_(NSMakeRect(initial_width / 2, 4, initial_width / 2 - 14, 16))
        footer_right.setFont_(NSFont.systemFontOfSize_(11))
        footer_right.setTextColor_(NSColor.secondaryLabelColor())
        footer_right.setAlignment_(2)  # right
        footer_right.setLineBreakMode_(NSLineBreakByTruncatingTail)
        container.addSubview_(footer_right)
        self._footer_right = footer_right

        self._panel = panel

        # Populate footer hints before first layout
        self._push_action_hints()
        self._update_prefix_hints()

        # Layout, center, then apply initial state
        self._layout_views()
        self._center_on_main_screen()

        if self._pending_initial_query is not None:
            query = self._pending_initial_query
            self._pending_initial_query = None
            self._set_search_text(query)
            self._on_search_changed(query)

        if self._pending_placeholder is not None:
            search_field.setPlaceholderString_(self._pending_placeholder)
            self._pending_placeholder = None

        self._update_context_block()

    def _layout_views(self) -> None:
        """Position all subviews based on current panel height.

        Uses non-flipped coordinate system (y=0 at bottom).
        """
        if self._panel is None or self._scroll_view is None:
            return
        from Foundation import NSMakeRect

        frame = self._panel.frame()
        w = frame.size.width
        h = frame.size.height

        search_h = self._SEARCH_HEIGHT
        footer_h = self._FOOTER_HEIGHT
        ctx_h = 50 if (self._context_container and not self._context_container.isHidden()) else 0
        has_preview = self._show_preview and self._is_expanded
        list_w = self._LIST_WIDTH if has_preview else w

        # Search input at top (just one line, no extra padding)
        search_y = h - search_h - ctx_h
        field_h = 24  # text field intrinsic height
        if self._search_field is not None:
            self._search_field.setFrame_(NSMakeRect(14, search_y - 4, w - 80, field_h))
        if self._spinner is not None:
            self._spinner.setFrame_(NSMakeRect(w - 76, search_y + (search_h - 16) / 2, 16, 16))
        if self._create_btn is not None:
            self._create_btn.setFrame_(NSMakeRect(w - 54, search_y + (search_h - 24) / 2, 24, 24))
        if self._create_hint is not None:
            self._create_hint.setFrame_(NSMakeRect(w - 32, search_y + (search_h - 14) / 2, 28, 14))

        # Context block at very top
        if self._context_container is not None and ctx_h > 0:
            self._context_container.setFrame_(NSMakeRect(0, h - ctx_h, w, ctx_h))
            if self._context_label is not None:
                self._context_label.setFrame_(NSMakeRect(14, ctx_h - 18, w - 28, 14))
            if self._context_text_view is not None:
                self._context_text_view.setFrame_(NSMakeRect(14, 4, w - 28, ctx_h - 22))

        # Footer hints at bottom
        if self._footer_left is not None:
            self._footer_left.setFrame_(NSMakeRect(14, 4, w / 2 - 20, footer_h - 8))
        if self._footer_right is not None:
            self._footer_right.setFrame_(NSMakeRect(w / 2, 4, w / 2 - 14, footer_h - 8))

        # Result list between search and footer
        result_y = footer_h
        result_h = search_y - footer_h
        if result_h < 0:
            result_h = 0

        if self._scroll_view is not None:
            self._scroll_view.setFrame_(NSMakeRect(0, result_y, list_w, result_h))
        if self._empty_label is not None:
            self._empty_label.setFrame_(NSMakeRect(0, result_y, list_w, result_h))

        # Preview panel on the right
        if self._preview_scroll is not None:
            if has_preview:
                preview_x = list_w
                preview_w = w - list_w
                self._preview_scroll.setFrame_(
                    NSMakeRect(preview_x, result_y, preview_w, result_h)
                )
                self._sync_preview_text_width()
                # Left border via layer
                layer = self._preview_scroll.layer()
                if layer is not None:
                    from AppKit import NSColor

                    layer.setBorderColor_(NSColor.separatorColor().CGColor())
                    layer.setBorderWidth_(0.5)

    def _apply_frame(self, width: int, height: int) -> None:
        """Resize the panel, keeping the top edge fixed, then re-layout."""
        if self._panel is None:
            return
        from Foundation import NSMakeRect

        old = self._panel.frame()
        if round(old.size.width) == width and round(old.size.height) == height:
            return
        new_y = old.origin.y + old.size.height - height
        new_x = old.origin.x + (old.size.width - width) / 2
        new_frame = NSMakeRect(new_x, new_y, width, height)
        self._panel.setFrame_display_(new_frame, True)
        self._layout_views()

    @staticmethod
    def _make_box(parent, frame):
        """Create a plain NSView container."""
        from AppKit import NSView

        box = NSView.alloc().initWithFrame_(frame)
        parent.addSubview_(box)
        return box

    # ------------------------------------------------------------------
    # Legacy compatibility — _handle_js_message for tests
    # ------------------------------------------------------------------

    def _handle_js_message(self, body: dict) -> None:
        """Dispatch messages (kept for test compatibility)."""
        msg_type = body.get("type", "")

        if msg_type == "search":
            query = body.get("query", "")
            self._do_search(query)

        elif msg_type == "execute":
            index = body.get("index", 0)
            version = body.get("version", self._items_version)
            modifier = body.get("modifier")
            self._execute_item(index, version, modifier=modifier)

        elif msg_type == "reveal":
            index = body.get("index", 0)
            version = body.get("version", self._items_version)
            self._reveal_item(index, version)

        elif msg_type == "close":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.close)

        elif msg_type == "deleteItem":
            index = body.get("index", -1)
            version = body.get("version", self._items_version)
            self._delete_item(index, version)

        elif msg_type == "createItem":
            self._handle_create_item()

        elif msg_type == "historyUp":
            self._history_navigate(1)

        elif msg_type == "historyDown":
            self._history_navigate(-1)

        elif msg_type == "exitHistory":
            self._history_index = -1
            self._in_history_mode = False

        elif msg_type == "resize":
            w = body.get("width", self._PANEL_WIDTH)
            h = body.get("height", self._PANEL_COLLAPSED_HEIGHT)
            self._apply_frame(w, h)

        elif msg_type == "tab":
            index = body.get("index", -1)
            self._handle_tab_complete(index)

        elif msg_type == "openSettings":
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self.close)
            self._fire_event("openSettings")

        elif msg_type == "shiftPreview":
            is_open = body.get("open", False)
            index = body.get("index", -1)
            self._toggle_quicklook(is_open, index)

        elif msg_type == "qlNavigate":
            index = body.get("index", -1)
            self._update_quicklook(index)

