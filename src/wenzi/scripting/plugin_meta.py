"""Plugin metadata — parse plugin.toml from a plugin directory."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PLUGIN_TOML = "plugin.toml"


@dataclass
class PluginMeta:
    """Metadata for a WenZi plugin, read from plugin.toml."""

    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    url: str = ""
    icon: str = ""
    min_wenzi_version: str = ""


def load_plugin_meta(plugin_dir: str) -> PluginMeta:
    """Load plugin metadata from *plugin_dir*/plugin.toml.

    Returns a :class:`PluginMeta` with all available fields populated.
    If the file is missing, malformed, or lacks a ``[plugin]`` section,
    falls back to using the directory name as the plugin name.
    """
    dir_name = os.path.basename(os.path.normpath(plugin_dir))
    toml_path = os.path.join(plugin_dir, PLUGIN_TOML)

    if not os.path.isfile(toml_path):
        return PluginMeta(name=dir_name)

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        logger.warning("Failed to parse %s, using defaults", toml_path, exc_info=True)
        return PluginMeta(name=dir_name)

    section = data.get("plugin")
    if not isinstance(section, dict):
        logger.warning("No [plugin] section in %s, using defaults", toml_path)
        return PluginMeta(name=dir_name)

    return PluginMeta(
        name=str(section.get("name", dir_name)),
        description=str(section.get("description", "")),
        version=str(section.get("version", "")),
        author=str(section.get("author", "")),
        url=str(section.get("url", "")),
        icon=str(section.get("icon", "")),
        min_wenzi_version=str(section.get("min_wenzi_version", "")),
    )
