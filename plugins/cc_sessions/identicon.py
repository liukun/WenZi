"""Generate two-letter avatar icons for project names."""

from __future__ import annotations

import base64
import re
from functools import lru_cache

COLORS = [
    "#E05252", "#E07B39", "#D4A843", "#5AAE5A", "#43A5A5", "#4A90D9",
    "#6B7FD9", "#8B6FC0", "#C06BAA", "#7C8A6E", "#9E7B5B", "#5B8A9E",
]


def _djb2(s: str) -> int:
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return h


def _get_initials(name: str) -> str:
    """Extract two-letter initials from a project name.

    Tries separator-based splitting, then camelCase detection,
    then falls back to the first two letters. Non-letter characters
    are stripped before the fallback so avatars always show letters.
    """
    if not name:
        return "?"

    # Try separator-based splitting
    parts = re.split(r"[-_.\s]+", name)
    if len(parts) >= 2 and parts[0] and parts[1]:
        return parts[0][0].upper() + parts[1][0].lower()

    # Try camelCase detection
    match = re.search(r"([a-zA-Z]).*?([A-Z])", name)
    if match:
        return match.group(1).upper() + match.group(2).lower()

    # Fallback: first two letters (strip non-alpha characters)
    letters = re.sub(r"[^a-zA-Z]", "", name)
    if len(letters) >= 2:
        return letters[0].upper() + letters[1].lower()
    if letters:
        return letters[0].upper()

    return name[0].upper()


@lru_cache(maxsize=128)
def generate(name: str, size: int = 32) -> str:
    """Generate a data URI for a two-letter avatar SVG from a project name."""
    h = _djb2(name)
    color = COLORS[h % len(COLORS)]
    initials = _get_initials(name)

    rx = size * 0.1875
    font_size = size * 0.42
    y_pos = size * 0.62

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<rect width="{size}" height="{size}" rx="{rx}" fill="{color}"/>'
        f'<text x="{size / 2}" y="{y_pos}" text-anchor="middle" fill="white" '
        f'font-family="-apple-system,BlinkMacSystemFont,sans-serif" '
        f'font-weight="600" font-size="{font_size}">{initials}</text>'
        f"</svg>"
    )
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"
