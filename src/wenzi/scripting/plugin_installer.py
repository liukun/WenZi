"""Plugin installer — download, install, update, uninstall plugins."""

from __future__ import annotations

import logging
import os
import shutil
import tomllib
from datetime import datetime, timezone

from wenzi.scripting.plugin_meta import (
    INSTALL_TOML,
    find_plugin_dir,
    load_plugin_meta,
    read_source,
)

logger = logging.getLogger(__name__)


class PluginInstaller:
    """Install, update, and uninstall plugins."""

    def __init__(self, plugins_dir: str):
        self._plugins_dir = plugins_dir

    def install(self, source_url: str) -> str:
        """Install a plugin from a plugin.toml URL (remote or local path).

        Returns the install directory path. Rolls back on failure.
        """
        raw = read_source(source_url)
        data = tomllib.loads(raw.decode("utf-8"))
        section = data.get("plugin", {})
        plugin_id = section.get("id", "")
        if not plugin_id:
            raise ValueError("plugin.toml missing required 'id' field")

        version = str(section.get("version", ""))
        files = section.get("files", [])
        if isinstance(files, str):
            files = [files]

        # Determine install directory from last segment of id
        dir_name = plugin_id.rsplit(".", 1)[-1] if "." in plugin_id else plugin_id
        install_dir = os.path.join(self._plugins_dir, dir_name)

        # Handle dir name collision with different id
        if os.path.isdir(install_dir):
            existing_meta = load_plugin_meta(install_dir)
            if existing_meta.id and existing_meta.id != plugin_id:
                for i in range(2, 100):
                    install_dir = os.path.join(self._plugins_dir, f"{dir_name}-{i}")
                    if not os.path.isdir(install_dir):
                        break
                else:
                    raise ValueError(f"Cannot find available directory for {plugin_id}")

        base_url = source_url.rsplit("/", 1)[0]

        os.makedirs(install_dir, exist_ok=True)
        try:
            for fname in files:
                file_url = f"{base_url}/{fname}"
                file_data = read_source(file_url)
                file_path = os.path.join(install_dir, fname)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(file_data)
            # Write plugin.toml
            with open(os.path.join(install_dir, "plugin.toml"), "wb") as f:
                f.write(raw)
            # Write install.toml
            self._write_install_toml(install_dir, source_url, version)
        except Exception:
            if os.path.isdir(install_dir):
                shutil.rmtree(install_dir)
            raise
        return install_dir

    def update(self, plugin_id: str) -> str:
        """Update an installed plugin by re-downloading from its source URL."""
        plugin_dir = find_plugin_dir(self._plugins_dir, plugin_id)
        if plugin_dir is None:
            raise ValueError(f"Plugin {plugin_id!r} not found")
        install_info = self._read_install_toml(plugin_dir)
        if install_info is None:
            raise ValueError(f"Plugin {plugin_id!r} has no install.toml (manually placed)")
        source_url = install_info.get("source_url", "")
        if not source_url:
            raise ValueError(f"Plugin {plugin_id!r} has no source_url in install.toml")

        raw = read_source(source_url)
        data = tomllib.loads(raw.decode("utf-8"))
        section = data.get("plugin", {})
        version = str(section.get("version", ""))
        files = section.get("files", [])
        if isinstance(files, str):
            files = [files]
        base_url = source_url.rsplit("/", 1)[0]

        for fname in files:
            file_data = read_source(f"{base_url}/{fname}")
            file_path = os.path.join(plugin_dir, fname)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(file_data)
        with open(os.path.join(plugin_dir, "plugin.toml"), "wb") as f:
            f.write(raw)
        self._write_install_toml(plugin_dir, source_url, version)
        return plugin_dir

    def uninstall(self, plugin_id: str) -> None:
        """Remove a plugin directory entirely."""
        plugin_dir = find_plugin_dir(self._plugins_dir, plugin_id)
        if plugin_dir is None:
            raise ValueError(f"Plugin {plugin_id!r} not found")
        shutil.rmtree(plugin_dir)

    def _read_install_toml(self, plugin_dir: str) -> dict | None:
        path = os.path.join(plugin_dir, INSTALL_TOML)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return data.get("install", {})

    @staticmethod
    def _write_install_toml(plugin_dir: str, source_url: str, version: str) -> None:
        content = (
            "[install]\n"
            f'source_url = "{source_url}"\n'
            f'installed_version = "{version}"\n'
            f'installed_at = "{datetime.now(timezone.utc).isoformat()}"\n'
        )
        with open(os.path.join(plugin_dir, INSTALL_TOML), "w") as f:
            f.write(content)
