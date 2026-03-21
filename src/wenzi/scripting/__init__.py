"""Scripting subpackage — plugin system for user automation scripts."""

from .engine import ScriptEngine
from .plugin_meta import PluginMeta, load_plugin_meta

__all__ = ["PluginMeta", "ScriptEngine", "load_plugin_meta"]
