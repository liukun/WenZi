"""wz.menu — read-only access to the app's statusbar menu items."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MenuAPI:
    """Enumerate and trigger the app's statusbar menu items — ``wz.menu``."""

    def __init__(self) -> None:
        self._root = None  # StatusMenuItem (app's root menu)

    def _set_root(self, root: Any) -> None:
        """Inject the app's root StatusMenuItem. Called by ScriptEngine."""
        self._root = root

    def list(self, flat: bool = False) -> List[Dict[str, Any]]:
        """Return the menu item tree as a list of dicts.

        Each dict contains: ``title``, ``key``, ``state``, ``has_action``,
        and optionally ``children`` (nested list).

        When *flat* is True, the tree is flattened and each item gets a
        ``path`` field (e.g. ``"Parent > Child"``).
        """
        if self._root is None:
            return []
        items = self._walk(self._root)
        if flat:
            return self._flatten(items)
        return items

    def trigger(self, title: str) -> bool:
        """Trigger a menu item by its title.

        Supports nested items using ``" > "`` as separator
        (e.g. ``"Parent > Child"``).  The callback is dispatched on the
        main thread.

        Returns True if the item was found and triggered.
        """
        if self._root is None:
            return False
        item = self._find(title)
        if item is None:
            return False

        from wenzi.statusbar import _ns_to_callback

        entry = _ns_to_callback.get(id(item._menuitem))
        if entry is None:
            return False

        smitem, callback = entry
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(callback, smitem)
        except Exception:
            logger.exception("Failed to trigger menu item: %s", title)
            return False
        return True

    def _find(self, title: str) -> Any:
        """Find a StatusMenuItem by title or path (``"A > B"``)."""
        parts = [p.strip() for p in title.split(" > ")]
        node = self._root
        for part in parts:
            found = None
            for _key, child in node._items.items():
                from wenzi.statusbar import SeparatorMenuItem

                if isinstance(child, SeparatorMenuItem):
                    continue
                if child.title == part:
                    found = child
                    break
            if found is None:
                return None
            node = found
        return node

    def _walk(self, parent: Any) -> List[Dict[str, Any]]:
        """Recursively walk the menu tree."""
        from wenzi.statusbar import SeparatorMenuItem, _ns_to_callback

        results: List[Dict[str, Any]] = []
        for key, item in parent._items.items():
            if isinstance(item, SeparatorMenuItem):
                continue
            entry: Dict[str, Any] = {
                "title": item.title,
                "key": key,
                "state": item.state,
                "has_action": id(item._menuitem) in _ns_to_callback,
            }
            if item._items:
                entry["children"] = self._walk(item)
            results.append(entry)
        return results

    def _flatten(
        self, items: List[Dict[str, Any]], prefix: str = "",
    ) -> List[Dict[str, Any]]:
        """Flatten a nested item list, adding ``path`` to each item."""
        flat: List[Dict[str, Any]] = []
        for item in items:
            path = f"{prefix} > {item['title']}" if prefix else item["title"]
            children = item.pop("children", None)
            item["path"] = path
            flat.append(item)
            if children:
                flat.extend(self._flatten(children, path))
        return flat
