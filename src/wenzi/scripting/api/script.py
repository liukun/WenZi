"""wz.script — register snippet placeholder scripts from plugins."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from typing import Any

from wenzi.scripting import script_registry

logger = logging.getLogger(__name__)


class ScriptAPI:
    """Plugin-facing wrapper around the global script registry.

    The engine wraps each ``setup(wz)`` call in ``_plugin_context(id)``;
    ``register()`` then auto-prefixes the name as ``<plugin>.<short_name>``.
    Calls outside any plugin context (e.g. from the user's ``init.py``)
    register the bare name. On reload, the engine calls ``_clear_owned()``
    to unregister all scripts registered through this API — plugin and
    user — before re-running setups.
    """

    def __init__(self) -> None:
        self._current_plugin_id: str | None = None
        self._owned: set[str] = set()

    @contextlib.contextmanager
    def _plugin_context(self, plugin_id: str) -> Iterator[None]:
        self._current_plugin_id = plugin_id
        try:
            yield
        finally:
            self._current_plugin_id = None

    def _clear_owned(self) -> None:
        if self._owned:
            logger.info("Clearing %d registered script(s)", len(self._owned))
        for full_name in self._owned:
            script_registry.unregister(full_name)
        self._owned.clear()

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """Register *fn* as a snippet script.

        When called inside a plugin's ``setup(wz)``, *name* is namespaced
        with the plugin id (``<plugin>.<name>``) — so plugins cannot
        collide with built-ins or each other.  Calling from outside a
        plugin context registers the bare name (intended only for user
        scripts in ``~/.wenzi/scripts``).

        The function must be sync and return a string (or stringifiable
        value).  When invoked as ``{name}`` it receives no input; when
        invoked downstream of a pipe ``{a|name}`` it receives the upstream
        result as its first positional argument.
        """
        plugin_id = self._current_plugin_id
        full_name = f"{plugin_id}.{name}" if plugin_id else name
        script_registry.register(full_name, fn)
        self._owned.add(full_name)
        logger.info("Script registered: %s", full_name)
