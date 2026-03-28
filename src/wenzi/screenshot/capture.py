"""Screen capture using Quartz and CGWindowList.

Provides :func:`capture_screen`, which captures a screenshot of every connected
display and collects window metadata for the annotation overlay.

Uses ``CGDisplayCreateImage`` for pixel capture and
``CGWindowListCopyWindowInfo`` for window metadata.

Temp images are written to ``~/.cache/WenZi/screenshot_tmp/`` and should be
cleaned up by the caller after the annotation session ends.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Minimum window dimensions to be considered visible.
_MIN_WIN_SIZE = 10

# Directory for temporary screenshot files (relative to DEFAULT_CACHE_DIR).
_SCREENSHOT_TMP_SUBDIR = "screenshot_tmp"


def _get_screenshot_tmp_dir() -> str:
    """Return the path to the temp screenshot directory (not yet created)."""
    from wenzi.config import DEFAULT_CACHE_DIR
    return os.path.join(os.path.expanduser(DEFAULT_CACHE_DIR), _SCREENSHOT_TMP_SUBDIR)


# ---------------------------------------------------------------------------
# Window metadata
# ---------------------------------------------------------------------------

def _collect_window_metadata() -> List[Dict[str, Any]]:
    """Return filtered, sorted window metadata via CGWindowList.

    Each dict contains:
    - ``bounds``: ``{"x": float, "y": float, "width": float, "height": float}``
    - ``title``: window title (may be empty string)
    - ``app``: owning application name (may be empty string)
    - ``layer``: window layer (z-order); higher = more on top
    - ``window_id``: CoreGraphics window ID

    Filtering rules (invisible windows are excluded):
    - ``layer < 0``  — background/desktop layers
    - width < 10 or height < 10  — too small to interact with
    - both ``title`` and ``app`` are empty — unidentifiable system elements
    """
    import Quartz

    options = Quartz.kCGWindowListOptionAll
    window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    if not window_list:
        return []

    windows: List[Dict[str, Any]] = []
    for info in window_list:
        layer = info.get("kCGWindowLayer", 0)
        if layer < 0:
            continue

        bounds_raw = info.get("kCGWindowBounds", {})
        width = float(bounds_raw.get("Width", 0))
        height = float(bounds_raw.get("Height", 0))
        if width < _MIN_WIN_SIZE or height < _MIN_WIN_SIZE:
            continue

        title = info.get("kCGWindowName", "") or ""
        app = info.get("kCGWindowOwnerName", "") or ""
        if not title and not app:
            continue

        bounds = {
            "x": float(bounds_raw.get("X", 0)),
            "y": float(bounds_raw.get("Y", 0)),
            "width": width,
            "height": height,
        }
        windows.append(
            {
                "bounds": bounds,
                "title": title,
                "app": app,
                "layer": layer,
                "window_id": info.get("kCGWindowNumber", 0),
            }
        )

    # Sort: higher layer first; within same layer, smaller area first
    # (so the "smallest containing window" is found first during hit-testing).
    windows.sort(key=lambda w: (-w["layer"], w["bounds"]["width"] * w["bounds"]["height"]))
    return windows


# ---------------------------------------------------------------------------
# Screen capture via Quartz (CGDisplayCreateImage)
# ---------------------------------------------------------------------------

def _capture_displays_sync() -> Dict[int, Any]:
    """Capture every online display using Quartz CGDisplayCreateImage.

    Returns ``{display_id: CGImage}`` for each online display.
    """
    import Quartz

    result: Dict[int, Any] = {}

    max_displays = 16
    (err, display_ids, count) = Quartz.CGGetOnlineDisplayList(max_displays, None, None)
    if err != 0:
        raise RuntimeError(f"CGGetOnlineDisplayList failed with error {err}")

    if not display_ids:
        return result

    for did in display_ids[:count]:
        image = Quartz.CGDisplayCreateImage(did)
        if image is not None:
            result[int(did)] = image
        else:
            logger.warning("CGDisplayCreateImage returned None for display %d", did)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_screen() -> Dict[str, Any]:
    """Capture screenshots of all displays and collect window metadata.

    Returns a dict::

        {
            "displays": {
                <display_id: int>: <CGImage>,
                ...
            },
            "windows": [
                {
                    "bounds": {"x": float, "y": float, "width": float, "height": float},
                    "title": str,
                    "app": str,
                    "layer": int,
                    "window_id": int,
                },
                ...
            ],
        }

    ``displays`` contains one entry per connected display.
    ``windows`` is sorted: higher layer first, smaller area first within a layer.

    The caller is responsible for cleaning up any temp files written to
    ``~/.cache/WenZi/screenshot_tmp/``.

    Raises ``RuntimeError`` on capture failure.
    """
    tmp_dir = _get_screenshot_tmp_dir()
    os.makedirs(tmp_dir, exist_ok=True)

    logger.debug("Collecting window metadata via CGWindowList")
    windows = _collect_window_metadata()
    logger.debug("Found %d visible windows", len(windows))

    logger.debug("Capturing display screenshots via ScreenCaptureKit")
    displays = _capture_displays_sync()
    logger.debug("Captured %d display(s)", len(displays))

    return {
        "displays": displays,
        "windows": windows,
    }
