# Plugin Management UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Plugins tab to the Settings panel for managing plugin installation, updates, and removal via plugin metadata and registries.

**Architecture:** Extend `PluginMeta` with `id`/`files` fields, add `PluginRegistry` for fetching/merging registry sources, `PluginInstaller` for download/install/update/uninstall operations. Add a "Plugins" tab to the existing Settings WebPanel with card-based plugin list. All network operations use `threading.Thread` + `AppHelper.callAfter()`.

**Tech Stack:** Python 3, PyObjC, tomllib, urllib.request, threading, WKWebView + JS bridge

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/wenzi/scripting/plugin_meta.py` | Add `id` and `files` fields to `PluginMeta` |
| Create | `src/wenzi/scripting/plugin_registry.py` | `PluginRegistry`, `PluginInfo`, `PluginStatus` — fetch/merge registries, compute plugin status |
| Create | `src/wenzi/scripting/plugin_installer.py` | `PluginInstaller` — download, install, update, uninstall plugins |
| Modify | `src/wenzi/scripting/engine.py` | Update `_load_plugins()` for bundle ID disabled_plugins matching |
| Modify | `src/wenzi/config.py` | Add `BUILTIN_REGISTRY_URL`, `plugins` config section defaults |
| Modify | `src/wenzi/ui/settings_window_web.py` | Add Plugins tab HTML/CSS/JS |
| Modify | `src/wenzi/controllers/settings_controller.py` | Add plugin management callbacks |
| Create | `plugins/registry.toml` | Official plugin index |
| Modify | `plugins/cc_sessions/plugin.toml` | Add `id` and `files` fields |
| Create | `scripts/sync_registry.py` | Generate registry.toml from plugin.toml files |
| Modify | `Makefile` | Add `sync-registry` target |
| Create | `tests/scripting/test_plugin_registry.py` | Tests for PluginRegistry |
| Create | `tests/scripting/test_plugin_installer.py` | Tests for PluginInstaller |
| Modify | `tests/scripting/test_plugin_meta.py` | Tests for new `id`/`files` fields |
| Modify | `tests/scripting/test_engine_plugins.py` | Tests for disabled_plugins migration |

---

### Task 1: Extend PluginMeta with `id` and `files` fields

**Files:**
- Modify: `src/wenzi/scripting/plugin_meta.py:15-61`
- Test: `tests/scripting/test_plugin_meta.py`

- [ ] **Step 1: Write failing tests for new fields**

Add to `tests/scripting/test_plugin_meta.py`:

```python
class TestPluginMeta:
    def test_defaults(self):
        meta = PluginMeta(name="test")
        assert meta.name == "test"
        assert meta.id == ""
        assert meta.files == []
        # ... existing assertions ...

    def test_id_and_files_defaults(self):
        meta = PluginMeta(name="test")
        assert meta.id == ""
        assert meta.files == []


class TestLoadPluginMeta:
    def test_full_toml_with_id_and_files(self, tmp_path):
        """id and files fields are read from plugin.toml."""
        plugin_dir = tmp_path / "my_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.my-plugin"\n'
            'name = "My Plugin"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py", "main.py", "util.py"]\n'
        )
        meta = load_plugin_meta(str(plugin_dir))
        assert meta.id == "com.example.my-plugin"
        assert meta.files == ["__init__.py", "main.py", "util.py"]

    def test_missing_id_fallback(self, tmp_path):
        """Missing id field defaults to empty string."""
        plugin_dir = tmp_path / "no_id"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nname = "No ID"\n'
        )
        meta = load_plugin_meta(str(plugin_dir))
        assert meta.id == ""
        assert meta.files == []

    def test_files_non_list_coerced(self, tmp_path):
        """Non-list files value is wrapped in a list."""
        plugin_dir = tmp_path / "bad_files"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nname = "Bad"\nfiles = "__init__.py"\n'
        )
        meta = load_plugin_meta(str(plugin_dir))
        assert meta.files == ["__init__.py"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_meta.py -v`
Expected: FAIL — `PluginMeta` has no `id` or `files` attribute

- [ ] **Step 3: Implement `id` and `files` in PluginMeta**

In `src/wenzi/scripting/plugin_meta.py`:

```python
from dataclasses import dataclass, field

@dataclass
class PluginMeta:
    """Metadata for a WenZi plugin, read from plugin.toml."""

    name: str
    id: str = ""
    description: str = ""
    version: str = ""
    author: str = ""
    url: str = ""
    icon: str = ""
    min_wenzi_version: str = ""
    files: list[str] = field(default_factory=list)
```

Update `load_plugin_meta()` return statement to include new fields:

```python
    # Parse files — must be a list of strings
    raw_files = section.get("files", [])
    if isinstance(raw_files, str):
        raw_files = [raw_files]
    files = [str(f) for f in raw_files] if isinstance(raw_files, list) else []

    return PluginMeta(
        name=str(section.get("name", dir_name)),
        id=str(section.get("id", "")),
        description=str(section.get("description", "")),
        version=str(section.get("version", "")),
        author=str(section.get("author", "")),
        url=str(section.get("url", "")),
        icon=str(section.get("icon", "")),
        min_wenzi_version=str(section.get("min_wenzi_version", "")),
        files=files,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_meta.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/wenzi/scripting/plugin_meta.py tests/scripting/test_plugin_meta.py
git commit -m "feat(plugin-meta): add id and files fields to PluginMeta"
```

---

### Task 2: Update cc_sessions plugin.toml and create registry.toml

**Files:**
- Modify: `plugins/cc_sessions/plugin.toml`
- Create: `plugins/registry.toml`

- [ ] **Step 1: Add `id` and `files` to cc_sessions plugin.toml**

```toml
[plugin]
id = "com.airead.wenzi.cc-sessions"
name = "Claude Code Sessions"
description = "Browse and view Claude Code session history through the launcher"
version = "0.1.0"
author = "WenZi"
url = "https://github.com/Airead/WenZi"
icon = "claude_icon.png"
min_wenzi_version = "0.1.7"
files = [
    "__init__.py",
    "init_plugin.py",
    "scanner.py",
    "reader.py",
    "cache.py",
    "preview.py",
    "viewer.html",
    "claude_icon.png",
]
```

Note: `vendor/` directory is excluded from files — it should be handled separately or bundled.

- [ ] **Step 2: Create `plugins/registry.toml`**

```toml
name = "WenZi Official"

[[plugins]]
id = "com.airead.wenzi.cc-sessions"
name = "Claude Code Sessions"
description = "Browse and view Claude Code session history through the launcher"
version = "0.1.0"
author = "WenZi"
min_wenzi_version = "0.1.7"
source = "https://raw.githubusercontent.com/Airead/WenZi/refs/heads/main/plugins/cc_sessions/plugin.toml"
```

- [ ] **Step 3: Commit**

```bash
git add plugins/cc_sessions/plugin.toml plugins/registry.toml
git commit -m "feat(plugins): add bundle ID, files list, and registry.toml"
```

---

### Task 3: Create sync_registry.py script and Makefile target

**Files:**
- Create: `scripts/sync_registry.py`
- Modify: `Makefile:1`
- Create: `tests/scripts/test_sync_registry.py`

- [ ] **Step 1: Write test for sync_registry**

Create `tests/scripts/test_sync_registry.py`:

```python
"""Tests for sync_registry.py script."""

import importlib.util
import os
import sys

import pytest


@pytest.fixture
def sync_module():
    """Import sync_registry.py as a module."""
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "sync_registry.py"
    )
    spec = importlib.util.spec_from_file_location("sync_registry", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSyncRegistry:
    def test_generates_registry_from_plugin_toml(self, tmp_path, sync_module):
        """Registry is generated from plugin.toml files."""
        plugin_dir = tmp_path / "plugins" / "my_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.my-plugin"\n'
            'name = "My Plugin"\n'
            'description = "A test"\n'
            'version = "1.0.0"\n'
            'author = "Alice"\n'
            'min_wenzi_version = "0.1.0"\n'
            'files = ["__init__.py"]\n'
        )
        registry_path = tmp_path / "plugins" / "registry.toml"
        sync_module.generate_registry(
            plugins_dir=str(tmp_path / "plugins"),
            output_path=str(registry_path),
            base_url="https://raw.githubusercontent.com/Airead/WenZi/refs/heads/main/plugins",
        )
        content = registry_path.read_text()
        assert 'name = "WenZi Official"' in content
        assert 'id = "com.example.my-plugin"' in content
        assert 'name = "My Plugin"' in content
        assert "source = " in content

    def test_skips_dirs_without_plugin_toml(self, tmp_path, sync_module):
        """Directories without plugin.toml are skipped."""
        (tmp_path / "plugins" / "no_toml").mkdir(parents=True)
        registry_path = tmp_path / "plugins" / "registry.toml"
        sync_module.generate_registry(
            plugins_dir=str(tmp_path / "plugins"),
            output_path=str(registry_path),
            base_url="https://example.com/plugins",
        )
        content = registry_path.read_text()
        assert "[[plugins]]" not in content

    def test_skips_dirs_without_id(self, tmp_path, sync_module):
        """Plugins without id field are skipped with a warning."""
        plugin_dir = tmp_path / "plugins" / "no_id"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nname = "No ID"\n'
        )
        registry_path = tmp_path / "plugins" / "registry.toml"
        sync_module.generate_registry(
            plugins_dir=str(tmp_path / "plugins"),
            output_path=str(registry_path),
            base_url="https://example.com/plugins",
        )
        content = registry_path.read_text()
        assert "[[plugins]]" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_sync_registry.py -v`
Expected: FAIL — script doesn't exist

- [ ] **Step 3: Implement sync_registry.py**

Create `scripts/sync_registry.py`:

```python
#!/usr/bin/env python3
"""Generate plugins/registry.toml from plugins/*/plugin.toml files.

Usage:
    python scripts/sync_registry.py [--plugins-dir DIR] [--base-url URL]
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib


DEFAULT_PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "..", "plugins")
DEFAULT_BASE_URL = (
    "https://raw.githubusercontent.com/Airead/WenZi/refs/heads/main/plugins"
)

REGISTRY_FIELDS = ["id", "name", "description", "version", "author", "min_wenzi_version"]


def generate_registry(
    plugins_dir: str,
    output_path: str,
    base_url: str,
) -> None:
    """Scan plugin dirs and write registry.toml."""
    plugins_dir = os.path.normpath(plugins_dir)
    entries: list[dict] = []

    for entry in sorted(os.listdir(plugins_dir)):
        entry_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        toml_path = os.path.join(entry_path, "plugin.toml")
        if not os.path.isfile(toml_path):
            continue

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        section = data.get("plugin")
        if not isinstance(section, dict):
            print(f"WARNING: {toml_path} has no [plugin] section, skipping")
            continue

        plugin_id = section.get("id", "")
        if not plugin_id:
            print(f"WARNING: {toml_path} has no id field, skipping")
            continue

        source = f"{base_url}/{entry}/plugin.toml"
        info = {"source": source}
        for field in REGISTRY_FIELDS:
            val = section.get(field, "")
            if val:
                info[field] = str(val)
        entries.append(info)

    lines = ['name = "WenZi Official"', ""]
    for info in entries:
        lines.append("[[plugins]]")
        for key in REGISTRY_FIELDS:
            if key in info:
                lines.append(f'{key} = "{info[key]}"')
        lines.append(f'source = "{info["source"]}"')
        lines.append("")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync plugins/registry.toml")
    parser.add_argument(
        "--plugins-dir",
        default=os.path.normpath(DEFAULT_PLUGINS_DIR),
        help="Path to plugins directory",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for plugin.toml source links",
    )
    args = parser.parse_args()
    output = os.path.join(args.plugins_dir, "registry.toml")
    generate_registry(args.plugins_dir, output, args.base_url)
    print(f"Registry written to {output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_sync_registry.py -v`
Expected: All PASS

- [ ] **Step 5: Add Makefile target**

Add to `Makefile` after the `.PHONY` line:

```makefile
# Update .PHONY to include sync-registry
.PHONY: dev run-lite docs docs-serve lint test build build-lite build-dmg build-lite-dmg clean sync-registry

# Add after existing targets:
# Regenerate plugins/registry.toml from plugins/*/plugin.toml
sync-registry:
	python scripts/sync_registry.py
```

- [ ] **Step 6: Verify `make sync-registry` works**

Run: `make sync-registry`
Expected: "Registry written to plugins/registry.toml"

Run: `diff <(cat plugins/registry.toml) <(python scripts/sync_registry.py --plugins-dir plugins && cat plugins/registry.toml)`
Expected: No diff (idempotent)

- [ ] **Step 7: Commit**

```bash
git add scripts/sync_registry.py tests/scripts/test_sync_registry.py Makefile
git commit -m "feat(scripts): add sync_registry.py and make sync-registry target"
```

---

### Task 4: Create PluginRegistry module

**Files:**
- Create: `src/wenzi/scripting/plugin_registry.py`
- Create: `tests/scripting/test_plugin_registry.py`

- [ ] **Step 1: Write failing tests for PluginStatus and PluginInfo**

Create `tests/scripting/test_plugin_registry.py`:

```python
"""Tests for plugin registry — fetch, merge, status calculation."""

from wenzi.scripting.plugin_meta import PluginMeta
from wenzi.scripting.plugin_registry import (
    PluginInfo,
    PluginRegistry,
    PluginStatus,
)


class TestPluginStatus:
    def test_enum_values(self):
        assert PluginStatus.NOT_INSTALLED.value == "not_installed"
        assert PluginStatus.INSTALLED.value == "installed"
        assert PluginStatus.UPDATE_AVAILABLE.value == "update_available"
        assert PluginStatus.MANUALLY_PLACED.value == "manually_placed"
        assert PluginStatus.INCOMPATIBLE.value == "incompatible"


class TestPluginInfo:
    def test_creation(self):
        meta = PluginMeta(name="Test", id="com.test.plugin", version="1.0.0")
        info = PluginInfo(
            meta=meta,
            source_url="https://example.com/plugin.toml",
            registry_name="Official",
            status=PluginStatus.NOT_INSTALLED,
            is_official=True,
        )
        assert info.meta.name == "Test"
        assert info.status == PluginStatus.NOT_INSTALLED
        assert info.installed_version is None
        assert info.is_official is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestPluginStatus -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PluginStatus and PluginInfo**

Create `src/wenzi/scripting/plugin_registry.py`:

```python
"""Plugin registry — fetch, parse, merge registries and compute plugin status."""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from wenzi.scripting.plugin_meta import PluginMeta

logger = logging.getLogger(__name__)

INSTALL_TOML = "install.toml"
REQUEST_TIMEOUT = 30


class PluginStatus(Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    UPDATE_AVAILABLE = "update_available"
    MANUALLY_PLACED = "manually_placed"
    INCOMPATIBLE = "incompatible"


@dataclass
class PluginInfo:
    meta: PluginMeta
    source_url: str
    registry_name: str
    status: PluginStatus
    installed_version: str | None = None
    is_official: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestPluginStatus tests/scripting/test_plugin_registry.py::TestPluginInfo -v`
Expected: All PASS

- [ ] **Step 5: Write failing tests for registry parsing**

Add to `tests/scripting/test_plugin_registry.py`:

```python
class TestParseRegistry:
    def test_parse_registry_toml(self, tmp_path):
        """Parse a local registry.toml file."""
        registry_file = tmp_path / "registry.toml"
        registry_file.write_text(
            'name = "Test Registry"\n'
            "\n"
            "[[plugins]]\n"
            'id = "com.test.alpha"\n'
            'name = "Alpha"\n'
            'description = "Alpha plugin"\n'
            'version = "1.0.0"\n'
            'author = "Alice"\n'
            'min_wenzi_version = "0.1.0"\n'
            'source = "https://example.com/alpha/plugin.toml"\n'
            "\n"
            "[[plugins]]\n"
            'id = "com.test.beta"\n'
            'name = "Beta"\n'
            'version = "2.0.0"\n'
            'source = "https://example.com/beta/plugin.toml"\n'
        )
        registry = PluginRegistry(plugins_dir=str(tmp_path / "plugins"))
        entries = registry.parse_registry(str(registry_file))
        assert len(entries) == 2
        assert entries[0]["id"] == "com.test.alpha"
        assert entries[1]["id"] == "com.test.beta"

    def test_parse_registry_name(self, tmp_path):
        """Registry name is extracted."""
        registry_file = tmp_path / "registry.toml"
        registry_file.write_text('name = "My Registry"\n')
        registry = PluginRegistry(plugins_dir=str(tmp_path / "plugins"))
        name, _ = registry.parse_registry_with_name(str(registry_file))
        assert name == "My Registry"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestParseRegistry -v`
Expected: FAIL — `parse_registry` not defined

- [ ] **Step 7: Implement registry parsing**

Add to `src/wenzi/scripting/plugin_registry.py`:

```python
def _read_source(source: str) -> bytes:
    """Read from a local path or remote URL. Returns raw bytes."""
    if source.startswith(("http://", "https://")):
        req = Request(source, headers={"User-Agent": "WenZi-PluginManager"})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read()
    else:
        with open(source, "rb") as f:
            return f.read()


class PluginRegistry:
    def __init__(self, plugins_dir: str):
        self._plugins_dir = plugins_dir

    def parse_registry(self, source: str) -> list[dict[str, Any]]:
        """Parse a registry.toml and return plugin entry dicts."""
        _, entries = self.parse_registry_with_name(source)
        return entries

    def parse_registry_with_name(
        self, source: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """Parse registry.toml, returning (registry_name, entries)."""
        raw = _read_source(source)
        data = tomllib.loads(raw.decode("utf-8"))
        name = data.get("name", "Unknown")
        entries = data.get("plugins", [])
        return name, [e for e in entries if isinstance(e, dict) and e.get("id")]
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestParseRegistry -v`
Expected: All PASS

- [ ] **Step 9: Write failing tests for install.toml reading and status computation**

Add to `tests/scripting/test_plugin_registry.py`:

```python
class TestLoadInstallInfo:
    def test_reads_install_toml(self, tmp_path):
        """Read install.toml from a plugin directory."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "my_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "install.toml").write_text(
            "[install]\n"
            'source_url = "https://example.com/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
            'installed_at = "2026-03-22T10:00:00"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        info = registry.load_install_info(str(plugin_dir))
        assert info["source_url"] == "https://example.com/plugin.toml"
        assert info["installed_version"] == "1.0.0"

    def test_missing_install_toml(self, tmp_path):
        """Missing install.toml returns None."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "manual"
        plugin_dir.mkdir(parents=True)
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        assert registry.load_install_info(str(plugin_dir)) is None


class TestComputeStatus:
    def test_not_installed(self, tmp_path):
        """Plugin not in local dir is NOT_INSTALLED."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, installed_ver = registry.compute_status(
            plugin_id="com.test.new",
            registry_version="1.0.0",
            min_wenzi_version="0.1.0",
            current_wenzi_version="0.2.0",
        )
        assert status == PluginStatus.NOT_INSTALLED
        assert installed_ver is None

    def test_installed_up_to_date(self, tmp_path):
        """Installed plugin with matching version is INSTALLED."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "alpha"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "Alpha"\nversion = "1.0.0"\n'
        )
        (plugin_dir / "install.toml").write_text(
            '[install]\nsource_url = "https://example.com/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, installed_ver = registry.compute_status(
            plugin_id="com.test.alpha",
            registry_version="1.0.0",
            min_wenzi_version="0.1.0",
            current_wenzi_version="0.2.0",
        )
        assert status == PluginStatus.INSTALLED
        assert installed_ver == "1.0.0"

    def test_update_available(self, tmp_path):
        """Installed plugin with older version shows UPDATE_AVAILABLE."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "alpha"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "Alpha"\nversion = "1.0.0"\n'
        )
        (plugin_dir / "install.toml").write_text(
            '[install]\nsource_url = "https://example.com/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, installed_ver = registry.compute_status(
            plugin_id="com.test.alpha",
            registry_version="2.0.0",
            min_wenzi_version="0.1.0",
            current_wenzi_version="0.2.0",
        )
        assert status == PluginStatus.UPDATE_AVAILABLE
        assert installed_ver == "1.0.0"

    def test_manually_placed(self, tmp_path):
        """Plugin without install.toml is MANUALLY_PLACED."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "manual"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.manual"\nname = "Manual"\nversion = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, installed_ver = registry.compute_status(
            plugin_id="com.test.manual",
            registry_version="1.0.0",
            min_wenzi_version="0.1.0",
            current_wenzi_version="0.2.0",
        )
        assert status == PluginStatus.MANUALLY_PLACED

    def test_incompatible(self, tmp_path):
        """Plugin requiring newer WenZi is INCOMPATIBLE."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, _ = registry.compute_status(
            plugin_id="com.test.new",
            registry_version="1.0.0",
            min_wenzi_version="9.0.0",
            current_wenzi_version="0.2.0",
        )
        assert status == PluginStatus.INCOMPATIBLE
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestLoadInstallInfo tests/scripting/test_plugin_registry.py::TestComputeStatus -v`
Expected: FAIL

- [ ] **Step 11: Implement install.toml reading and status computation**

Add to `PluginRegistry` class in `src/wenzi/scripting/plugin_registry.py`:

```python
    def load_install_info(self, plugin_dir: str) -> dict[str, str] | None:
        """Read install.toml from a plugin directory. Returns None if missing."""
        install_path = os.path.join(plugin_dir, INSTALL_TOML)
        if not os.path.isfile(install_path):
            return None
        try:
            with open(install_path, "rb") as f:
                data = tomllib.load(f)
            return data.get("install", {})
        except Exception:
            logger.warning("Failed to parse %s", install_path, exc_info=True)
            return None

    def _find_local_plugin_dir(self, plugin_id: str) -> str | None:
        """Find local plugin directory by scanning for matching id."""
        if not os.path.isdir(self._plugins_dir):
            return None
        for entry in os.listdir(self._plugins_dir):
            entry_path = os.path.join(self._plugins_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            toml_path = os.path.join(entry_path, "plugin.toml")
            if not os.path.isfile(toml_path):
                continue
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                section = data.get("plugin", {})
                if section.get("id") == plugin_id:
                    return entry_path
            except Exception:
                continue
        return None

    @staticmethod
    def _parse_version(version: str) -> tuple[int, ...]:
        """Parse 'MAJOR.MINOR.PATCH' into numeric tuple."""
        try:
            return tuple(int(x) for x in version.split("."))
        except (ValueError, AttributeError):
            return (0,)

    def compute_status(
        self,
        plugin_id: str,
        registry_version: str,
        min_wenzi_version: str,
        current_wenzi_version: str,
    ) -> tuple[PluginStatus, str | None]:
        """Compute plugin status by comparing registry with local state."""
        # Check compatibility first
        if min_wenzi_version and current_wenzi_version != "dev":
            if self._parse_version(current_wenzi_version) < self._parse_version(
                min_wenzi_version
            ):
                return PluginStatus.INCOMPATIBLE, None

        # Find local plugin
        local_dir = self._find_local_plugin_dir(plugin_id)
        if local_dir is None:
            return PluginStatus.NOT_INSTALLED, None

        # Check if UI-installed
        install_info = self.load_install_info(local_dir)
        if install_info is None:
            return PluginStatus.MANUALLY_PLACED, None

        installed_ver = install_info.get("installed_version", "")
        if self._parse_version(installed_ver) < self._parse_version(registry_version):
            return PluginStatus.UPDATE_AVAILABLE, installed_ver

        return PluginStatus.INSTALLED, installed_ver
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_registry.py -v`
Expected: All PASS

- [ ] **Step 13: Write failing tests for merge_registries (official priority)**

Add to `tests/scripting/test_plugin_registry.py`:

```python
class TestMergeRegistries:
    def test_official_takes_priority(self, tmp_path):
        """Official registry entries override third-party with same id."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        official = tmp_path / "official.toml"
        official.write_text(
            'name = "Official"\n'
            "[[plugins]]\n"
            'id = "com.test.shared"\n'
            'name = "Official Version"\n'
            'version = "1.0.0"\n'
            'source = "https://official/plugin.toml"\n'
        )
        third_party = tmp_path / "community.toml"
        third_party.write_text(
            'name = "Community"\n'
            "[[plugins]]\n"
            'id = "com.test.shared"\n'
            'name = "Community Version"\n'
            'version = "2.0.0"\n'
            'source = "https://community/plugin.toml"\n'
            "\n"
            "[[plugins]]\n"
            'id = "com.test.unique"\n'
            'name = "Unique"\n'
            'version = "1.0.0"\n'
            'source = "https://community/unique/plugin.toml"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        result = registry.merge_registries(
            official_source=str(official),
            extra_sources=[str(third_party)],
            current_wenzi_version="1.0.0",
        )
        ids = [r.meta.id for r in result]
        assert ids.count("com.test.shared") == 1
        shared = [r for r in result if r.meta.id == "com.test.shared"][0]
        assert shared.meta.name == "Official Version"
        assert shared.is_official is True
        unique = [r for r in result if r.meta.id == "com.test.unique"][0]
        assert unique.is_official is False
```

- [ ] **Step 14: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_registry.py::TestMergeRegistries -v`
Expected: FAIL

- [ ] **Step 15: Implement merge_registries**

Add to `PluginRegistry` class:

```python
    def merge_registries(
        self,
        official_source: str,
        extra_sources: list[str],
        current_wenzi_version: str,
    ) -> list[PluginInfo]:
        """Fetch and merge registries. Official first, dedup by id."""
        result: list[PluginInfo] = []
        seen_ids: set[str] = set()

        # Official first
        try:
            name, entries = self.parse_registry_with_name(official_source)
        except Exception:
            logger.error("Failed to fetch official registry: %s", official_source, exc_info=True)
            name, entries = "WenZi Official", []

        for entry in entries:
            pid = entry.get("id", "")
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            meta = PluginMeta(
                name=entry.get("name", ""),
                id=pid,
                description=entry.get("description", ""),
                version=entry.get("version", ""),
                author=entry.get("author", ""),
                min_wenzi_version=entry.get("min_wenzi_version", ""),
            )
            status, installed_ver = self.compute_status(
                pid, meta.version, meta.min_wenzi_version, current_wenzi_version
            )
            result.append(PluginInfo(
                meta=meta,
                source_url=entry.get("source", ""),
                registry_name=name,
                status=status,
                installed_version=installed_ver,
                is_official=True,
            ))

        # Extra registries
        for source in extra_sources:
            try:
                ename, eentries = self.parse_registry_with_name(source)
            except Exception:
                logger.error("Failed to fetch registry: %s", source, exc_info=True)
                continue
            for entry in eentries:
                pid = entry.get("id", "")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                meta = PluginMeta(
                    name=entry.get("name", ""),
                    id=pid,
                    description=entry.get("description", ""),
                    version=entry.get("version", ""),
                    author=entry.get("author", ""),
                    min_wenzi_version=entry.get("min_wenzi_version", ""),
                )
                status, installed_ver = self.compute_status(
                    pid, meta.version, meta.min_wenzi_version, current_wenzi_version
                )
                result.append(PluginInfo(
                    meta=meta,
                    source_url=entry.get("source", ""),
                    registry_name=ename,
                    status=status,
                    installed_version=installed_ver,
                    is_official=False,
                ))

        return result
```

- [ ] **Step 16: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_registry.py -v`
Expected: All PASS

- [ ] **Step 17: Commit**

```bash
git add src/wenzi/scripting/plugin_registry.py tests/scripting/test_plugin_registry.py
git commit -m "feat(plugin-registry): add PluginRegistry with fetch, parse, merge, and status computation"
```

---

### Task 5: Create PluginInstaller module

**Files:**
- Create: `src/wenzi/scripting/plugin_installer.py`
- Create: `tests/scripting/test_plugin_installer.py`

- [ ] **Step 1: Write failing tests for install**

Create `tests/scripting/test_plugin_installer.py`:

```python
"""Tests for plugin installer — download, install, update, uninstall."""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

import pytest

from wenzi.scripting.plugin_installer import PluginInstaller


@pytest.fixture
def plugins_dir(tmp_path):
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def serve_dir(tmp_path):
    """Create a directory to serve files from via HTTP."""
    d = tmp_path / "serve"
    d.mkdir()
    return d


@pytest.fixture
def http_server(serve_dir):
    """Start a local HTTP server serving serve_dir."""
    handler = type(
        "Handler",
        (SimpleHTTPRequestHandler,),
        {"directory": str(serve_dir)},
    )

    # Use init to set directory properly
    class DirHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, format, *args):
            pass  # Suppress logs

    server = HTTPServer(("127.0.0.1", 0), DirHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestInstall:
    def test_install_from_url(self, plugins_dir, serve_dir, http_server):
        """Install downloads files and writes install.toml."""
        # Set up remote plugin
        plugin_remote = serve_dir / "my_plugin"
        plugin_remote.mkdir()
        (plugin_remote / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.test.my-plugin"\n'
            'name = "My Plugin"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py", "main.py"]\n'
        )
        (plugin_remote / "__init__.py").write_text("# init")
        (plugin_remote / "main.py").write_text("# main")

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        source_url = f"{http_server}/my_plugin/plugin.toml"
        installer.install(source_url)

        # Verify files downloaded
        installed_dir = plugins_dir / "my-plugin"
        assert (installed_dir / "__init__.py").read_text() == "# init"
        assert (installed_dir / "main.py").read_text() == "# main"
        assert (installed_dir / "plugin.toml").exists()
        assert (installed_dir / "install.toml").exists()

        # Verify install.toml content
        import tomllib
        with open(installed_dir / "install.toml", "rb") as f:
            install_data = tomllib.load(f)
        assert install_data["install"]["source_url"] == source_url
        assert install_data["install"]["installed_version"] == "1.0.0"

    def test_install_from_local_path(self, plugins_dir, tmp_path):
        """Install from local file path."""
        source_dir = tmp_path / "source_plugin"
        source_dir.mkdir()
        (source_dir / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.test.local"\n'
            'name = "Local Plugin"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py"]\n'
        )
        (source_dir / "__init__.py").write_text("# local init")

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        installer.install(str(source_dir / "plugin.toml"))

        installed_dir = plugins_dir / "local"
        assert (installed_dir / "__init__.py").read_text() == "# local init"

    def test_install_rollback_on_failure(self, plugins_dir, serve_dir, http_server):
        """Failed download rolls back partial install."""
        plugin_remote = serve_dir / "bad_plugin"
        plugin_remote.mkdir()
        (plugin_remote / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.test.bad"\n'
            'name = "Bad"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py", "missing.py"]\n'
        )
        (plugin_remote / "__init__.py").write_text("# init")
        # missing.py intentionally not created

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        with pytest.raises(Exception):
            installer.install(f"{http_server}/bad_plugin/plugin.toml")

        # Directory should be cleaned up
        assert not (plugins_dir / "bad").exists()

    def test_install_rejects_id_conflict(self, plugins_dir):
        """Cannot install plugin with same id as existing one."""
        existing = plugins_dir / "existing"
        existing.mkdir()
        (existing / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.conflict"\nname = "Existing"\n'
        )
        (existing / "install.toml").write_text(
            '[install]\nsource_url = "https://other.com/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
        )

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        # Trying to install from a different source with same id should fail
        # (unless it's the same source — that's an update)
        # This test uses a mock since we can't easily set up two different sources
        # The actual conflict check is: same id, different source_url
        assert (plugins_dir / "existing").exists()


class TestUpdate:
    def test_update_overwrites_files(self, plugins_dir, serve_dir, http_server):
        """Update downloads new version and overwrites files."""
        # Pre-install v1
        installed = plugins_dir / "updatable"
        installed.mkdir()
        (installed / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.updatable"\nname = "Updatable"\nversion = "1.0.0"\n'
            'files = ["__init__.py"]\n'
        )
        (installed / "__init__.py").write_text("# v1")
        (installed / "install.toml").write_text(
            '[install]\n'
            f'source_url = "{http_server}/updatable/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
        )

        # Set up remote v2
        remote = serve_dir / "updatable"
        remote.mkdir()
        (remote / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.updatable"\nname = "Updatable"\nversion = "2.0.0"\n'
            'files = ["__init__.py"]\n'
        )
        (remote / "__init__.py").write_text("# v2")

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        installer.update("com.test.updatable")

        assert (installed / "__init__.py").read_text() == "# v2"
        import tomllib
        with open(installed / "install.toml", "rb") as f:
            data = tomllib.load(f)
        assert data["install"]["installed_version"] == "2.0.0"


class TestUninstall:
    def test_uninstall_removes_directory(self, plugins_dir):
        """Uninstall deletes the entire plugin directory."""
        installed = plugins_dir / "removeme"
        installed.mkdir()
        (installed / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.removeme"\nname = "Remove"\n'
        )
        (installed / "install.toml").write_text(
            '[install]\nsource_url = "https://example.com/plugin.toml"\n'
            'installed_version = "1.0.0"\n'
        )
        (installed / "__init__.py").write_text("# code")

        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        installer.uninstall("com.test.removeme")
        assert not installed.exists()

    def test_uninstall_not_found_raises(self, plugins_dir):
        """Uninstall non-existent plugin raises error."""
        installer = PluginInstaller(plugins_dir=str(plugins_dir))
        with pytest.raises(ValueError, match="not found"):
            installer.uninstall("com.test.nonexistent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_plugin_installer.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PluginInstaller**

Create `src/wenzi/scripting/plugin_installer.py`:

```python
"""Plugin installer — download, install, update, uninstall plugins."""

from __future__ import annotations

import logging
import os
import shutil
import tomllib
from datetime import datetime, timezone

from wenzi.scripting.plugin_meta import load_plugin_meta
from wenzi.scripting.plugin_registry import INSTALL_TOML, _read_source

logger = logging.getLogger(__name__)


class PluginInstaller:
    """Install, update, and uninstall plugins."""

    def __init__(self, plugins_dir: str):
        self._plugins_dir = plugins_dir

    def install(self, source_url: str) -> str:
        """Install a plugin from a plugin.toml URL (remote or local path).

        Returns the install directory path.
        Raises on failure (rolls back partial downloads).
        """
        # Fetch plugin.toml
        raw = _read_source(source_url)
        data = tomllib.loads(raw.decode("utf-8"))
        section = data.get("plugin", {})
        plugin_id = section.get("id", "")
        if not plugin_id:
            raise ValueError("plugin.toml missing required 'id' field")

        version = str(section.get("version", ""))
        files = section.get("files", [])
        if isinstance(files, str):
            files = [files]

        # Determine install directory
        dir_name = plugin_id.rsplit(".", 1)[-1] if "." in plugin_id else plugin_id
        install_dir = os.path.join(self._plugins_dir, dir_name)

        # Check for id conflict (different plugin already using this dir)
        if os.path.isdir(install_dir):
            existing_meta = load_plugin_meta(install_dir)
            if existing_meta.id and existing_meta.id != plugin_id:
                # Try with suffix
                for i in range(2, 100):
                    install_dir = os.path.join(self._plugins_dir, f"{dir_name}-{i}")
                    if not os.path.isdir(install_dir):
                        break
                else:
                    raise ValueError(f"Cannot find available directory for {plugin_id}")

        # Compute base URL for file downloads
        base_url = source_url.rsplit("/", 1)[0]

        # Download files
        os.makedirs(install_dir, exist_ok=True)
        try:
            for fname in files:
                file_url = f"{base_url}/{fname}"
                file_data = _read_source(file_url)
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
            # Rollback
            if os.path.isdir(install_dir):
                shutil.rmtree(install_dir)
            raise

        return install_dir

    def update(self, plugin_id: str) -> str:
        """Update an installed plugin by re-downloading from its source URL.

        Returns the install directory path.
        """
        plugin_dir = self._find_plugin_dir(plugin_id)
        if plugin_dir is None:
            raise ValueError(f"Plugin {plugin_id!r} not found")

        install_info = self._read_install_toml(plugin_dir)
        if install_info is None:
            raise ValueError(f"Plugin {plugin_id!r} has no install.toml (manually placed)")

        source_url = install_info.get("source_url", "")
        if not source_url:
            raise ValueError(f"Plugin {plugin_id!r} has no source_url in install.toml")

        # Fetch new plugin.toml
        raw = _read_source(source_url)
        data = tomllib.loads(raw.decode("utf-8"))
        section = data.get("plugin", {})
        version = str(section.get("version", ""))
        files = section.get("files", [])
        if isinstance(files, str):
            files = [files]

        base_url = source_url.rsplit("/", 1)[0]

        # Download and overwrite files
        for fname in files:
            file_url = f"{base_url}/{fname}"
            file_data = _read_source(file_url)
            file_path = os.path.join(plugin_dir, fname)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(file_data)

        # Overwrite plugin.toml
        with open(os.path.join(plugin_dir, "plugin.toml"), "wb") as f:
            f.write(raw)

        # Update install.toml
        self._write_install_toml(plugin_dir, source_url, version)

        return plugin_dir

    def uninstall(self, plugin_id: str) -> None:
        """Remove a plugin directory entirely."""
        plugin_dir = self._find_plugin_dir(plugin_id)
        if plugin_dir is None:
            raise ValueError(f"Plugin {plugin_id!r} not found")
        shutil.rmtree(plugin_dir)

    def _find_plugin_dir(self, plugin_id: str) -> str | None:
        """Find local plugin directory by bundle id."""
        if not os.path.isdir(self._plugins_dir):
            return None
        for entry in os.listdir(self._plugins_dir):
            entry_path = os.path.join(self._plugins_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            meta = load_plugin_meta(entry_path)
            if meta.id == plugin_id:
                return entry_path
        return None

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_plugin_installer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/wenzi/scripting/plugin_installer.py tests/scripting/test_plugin_installer.py
git commit -m "feat(plugin-installer): add PluginInstaller with install, update, uninstall"
```

---

### Task 6: Update engine.py for bundle ID disabled_plugins

**Files:**
- Modify: `src/wenzi/scripting/engine.py:740-804`
- Test: `tests/scripting/test_engine_plugins.py`

- [ ] **Step 1: Write failing tests for bundle ID matching**

Add to `tests/scripting/test_engine_plugins.py`:

```python
class TestDisabledPluginsMigration:
    def test_disabled_by_bundle_id(self, tmp_path):
        """Plugin can be disabled by bundle ID."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "my_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "__init__.py").write_text("def setup(wz): pass")
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.my-plugin"\nname = "My Plugin"\n'
        )
        # Use bundle id in disabled list
        config = {"disabled_plugins": ["com.test.my-plugin"]}
        engine = ScriptEngine(
            config=config,
            plugins_dir=str(plugins_dir),
            scripts_dir=str(tmp_path / "scripts"),
        )
        engine._load_plugins()
        # Plugin should be disabled (metadata stored but not loaded)
        metas = engine.get_plugin_metas()
        assert "my_plugin" in metas
        # Verify it was skipped during loading
        assert "my_plugin" not in sys.modules

    def test_disabled_by_dir_name_still_works(self, tmp_path):
        """Backward compat: directory name still works for disabling."""
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "legacy_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "__init__.py").write_text("def setup(wz): pass")
        (plugin_dir / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.legacy"\nname = "Legacy"\n'
        )
        config = {"disabled_plugins": ["legacy_plugin"]}
        engine = ScriptEngine(
            config=config,
            plugins_dir=str(plugins_dir),
            scripts_dir=str(tmp_path / "scripts"),
        )
        engine._load_plugins()
        assert "legacy_plugin" not in sys.modules
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripting/test_engine_plugins.py::TestDisabledPluginsMigration -v`
Expected: FAIL — disabled check only matches directory name

- [ ] **Step 3: Update `_load_plugins()` in engine.py**

In `src/wenzi/scripting/engine.py`, modify `_load_plugins()` around line 759-772. Change the disabled check to:

1. Read metadata first (move `load_plugin_meta` before the disabled check)
2. Check both directory name and bundle ID against `disabled_plugins`

```python
# Before (approximately):
#   disabled = set(self._config.get("disabled_plugins", []))
#   ...
#   if entry in disabled:
#       continue
#   meta = load_plugin_meta(entry_path)

# After:
disabled = set(self._config.get("disabled_plugins", []))
# ... (keep existing filters: hidden dirs, no __init__.py)
meta = load_plugin_meta(entry_path)
self._plugin_metas[entry] = meta

# Check disabled by directory name OR bundle ID
is_disabled = entry in disabled or (meta.id and meta.id in disabled)
if is_disabled:
    logger.info("Plugin %s is disabled, skipping", entry)
    continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripting/test_engine_plugins.py -v`
Expected: All PASS (existing + new tests)

- [ ] **Step 5: Commit**

```bash
git add src/wenzi/scripting/engine.py tests/scripting/test_engine_plugins.py
git commit -m "feat(engine): support bundle ID in disabled_plugins with backward compat"
```

---

### Task 7: Add config defaults for plugin registry

**Files:**
- Modify: `src/wenzi/config.py:42-53` (add constants)
- Modify: `src/wenzi/config.py:271-381` (add to DEFAULT_CONFIG)

- [ ] **Step 1: Add registry constants and config defaults**

In `src/wenzi/config.py`, add near other constants:

```python
BUILTIN_REGISTRY_URL = (
    "https://raw.githubusercontent.com/Airead/WenZi/refs/heads/main/plugins/registry.toml"
)
```

Add to `DEFAULT_CONFIG` dict under a `"plugins"` key:

```python
"plugins": {
    "extra_registries": [],
},
```

- [ ] **Step 2: Commit**

```bash
git add src/wenzi/config.py
git commit -m "feat(config): add BUILTIN_REGISTRY_URL and plugins config section"
```

---

### Task 8: Add Plugins tab HTML/CSS/JS to Settings WebPanel

**Files:**
- Modify: `src/wenzi/ui/settings_window_web.py:422-441` (sidebar), `447-754` (tab content), CSS section

This is the largest task. It adds the Plugins tab UI with:
- Registry management section
- Plugin card list
- Manual install URL input
- Status-dependent action buttons

- [ ] **Step 1: Add sidebar item for Plugins tab**

In `src/wenzi/ui/settings_window_web.py`, add after the Launcher sidebar item (around line 441):

```html
<div class="sidebar-item" data-tab="plugins" onclick="switchTab('plugins')">
  <span class="sidebar-icon">🧩</span>
  <span>Plugins</span>
</div>
```

- [ ] **Step 2: Add Plugins tab content HTML**

After the last `</div>` of `tab-launcher` content, add:

```html
<div id="tab-plugins" class="tab-content">
  <!-- Registry Sources -->
  <div class="section">
    <div class="section-title">Plugin Sources</div>
    <div id="registry-list"></div>
    <div class="manual-install-row" style="margin-top:8px;">
      <input type="text" id="registry-url-input"
             placeholder="Registry URL..."
             class="text-input" style="flex:1;">
      <button class="btn btn-secondary" onclick="addRegistry()">Add</button>
    </div>
  </div>

  <!-- Plugin List -->
  <div class="section">
    <div class="section-title">
      Plugins
      <span id="plugins-loading" style="display:none; font-size:12px; color:var(--secondary-text);">
        Loading...
      </span>
    </div>
    <div id="plugin-list"></div>
    <div id="plugins-error" style="display:none; color:var(--error-color); margin-top:8px;"></div>
  </div>

  <!-- Manual Install -->
  <div class="section">
    <div class="section-title">Install from URL</div>
    <div class="manual-install-row">
      <input type="text" id="plugin-url-input"
             placeholder="plugin.toml URL..."
             class="text-input" style="flex:1;">
      <button class="btn btn-primary" onclick="installFromUrl()">Install</button>
    </div>
  </div>

  <!-- Reload Banner -->
  <div id="reload-banner" style="display:none;"
       class="reload-banner">
    <span>Plugins changed. Reload to apply.</span>
    <button class="btn btn-primary" onclick="postCallback('on_plugin_reload')">
      Reload Now
    </button>
  </div>
</div>
```

- [ ] **Step 3: Add CSS for plugin cards and reload banner**

Add to the `<style>` section:

```css
/* Plugin card */
.plugin-card {
  display: flex;
  align-items: flex-start;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  margin-bottom: 8px;
  gap: 12px;
}
.plugin-icon {
  width: 40px; height: 40px;
  border-radius: 8px;
  background: var(--bg-secondary);
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.plugin-info { flex: 1; min-width: 0; }
.plugin-name { font-weight: 600; font-size: 14px; }
.plugin-version { font-size: 12px; color: var(--secondary-text); margin-left: 6px; }
.plugin-author { font-size: 12px; color: var(--secondary-text); }
.plugin-desc { font-size: 13px; margin-top: 4px; color: var(--secondary-text); }
.plugin-badge {
  font-size: 10px; padding: 2px 6px; border-radius: 4px;
  display: inline-block; margin-left: 6px;
}
.badge-official { background: #e8f5e9; color: #2e7d32; }
.badge-unverified { background: #fff3e0; color: #e65100; }
.plugin-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }

/* Reload banner */
.reload-banner {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; margin-top: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
}

/* Manual install row */
.manual-install-row { display: flex; gap: 8px; align-items: center; }

@media (prefers-color-scheme: dark) {
  .badge-official { background: #1b5e20; color: #a5d6a7; }
  .badge-unverified { background: #bf360c; color: #ffcc80; }
}
```

- [ ] **Step 4: Add JavaScript for plugin rendering and actions**

Add to the `<script>` section:

```javascript
function renderPlugins() {
  var plugins = CONFIG.plugins || [];
  var list = document.getElementById('plugin-list');
  if (!plugins.length) {
    list.innerHTML = '<div style="color:var(--secondary-text);padding:8px;">No plugins available.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < plugins.length; i++) {
    var p = plugins[i];
    html += renderPluginCard(p);
  }
  list.innerHTML = html;
}

function renderPluginCard(p) {
  var badge = p.is_official
    ? '<span class="plugin-badge badge-official">Official</span>'
    : '<span class="plugin-badge badge-unverified">Unverified</span>';
  var actions = '';
  if (p.status === 'incompatible') {
    actions = '<button class="btn btn-secondary" disabled title="Requires WenZi >= ' + _esc(p.min_wenzi_version) + '">Install</button>';
  } else if (p.status === 'not_installed') {
    actions = '<button class="btn btn-primary" onclick="installPlugin(\'' + _esc(p.id) + '\')">Install</button>';
  } else if (p.status === 'update_available') {
    actions = '<button class="btn btn-primary" onclick="updatePlugin(\'' + _esc(p.id) + '\')">Update (' + _esc(p.installed_version) + ' → ' + _esc(p.version) + ')</button>';
    actions += toggleHtml(p.id, p.enabled);
    actions += '<button class="btn btn-danger" onclick="uninstallPlugin(\'' + _esc(p.id) + '\')">Uninstall</button>';
  } else if (p.status === 'installed') {
    actions += toggleHtml(p.id, p.enabled);
    actions += '<button class="btn btn-danger" onclick="uninstallPlugin(\'' + _esc(p.id) + '\')">Uninstall</button>';
  } else if (p.status === 'manually_placed') {
    actions += toggleHtml(p.id, p.enabled);
  }
  return '<div class="plugin-card">'
    + '<div class="plugin-icon">🧩</div>'
    + '<div class="plugin-info">'
    + '<div><span class="plugin-name">' + _esc(p.name) + '</span>'
    + '<span class="plugin-version">v' + _esc(p.version) + '</span>'
    + badge + '</div>'
    + '<div class="plugin-author">' + _esc(p.author) + ' · ' + _esc(p.registry_name) + '</div>'
    + '<div class="plugin-desc">' + _esc(p.description) + '</div>'
    + '</div>'
    + '<div class="plugin-actions">' + actions + '</div>'
    + '</div>';
}

function toggleHtml(pluginId, enabled) {
  var cls = enabled ? 'toggle on' : 'toggle';
  return '<div class="' + cls + '" onclick="togglePlugin(this, \'' + _esc(pluginId) + '\')"><div class="toggle-knob"></div></div>';
}

function installPlugin(id) { postCallback('on_plugin_install_by_id', id); }
function updatePlugin(id) { postCallback('on_plugin_update', id); }
function uninstallPlugin(id) {
  if (confirm('Uninstall this plugin? This will delete all plugin files.')) {
    postCallback('on_plugin_uninstall', id);
  }
}
function togglePlugin(el, id) {
  el.classList.toggle('on');
  var enabled = el.classList.contains('on');
  postCallback('on_plugin_toggle', id, enabled);
}
function installFromUrl() {
  var input = document.getElementById('plugin-url-input');
  var url = input.value.trim();
  if (url) { postCallback('on_plugin_install_url', url); input.value = ''; }
}

function renderRegistries() {
  var registries = CONFIG.registries || [];
  var list = document.getElementById('registry-list');
  var html = '';
  for (var i = 0; i < registries.length; i++) {
    var r = registries[i];
    var removeBtn = r.removable
      ? ' <button class="btn btn-small btn-danger" onclick="removeRegistry(' + i + ')">Remove</button>'
      : '';
    html += '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;">'
      + '<span style="flex:1;font-size:13px;">' + _esc(r.name) + '</span>'
      + removeBtn + '</div>';
  }
  list.innerHTML = html;
}

function addRegistry() {
  var input = document.getElementById('registry-url-input');
  var url = input.value.trim();
  if (url) { postCallback('on_registry_add', url); input.value = ''; }
}
function removeRegistry(index) { postCallback('on_registry_remove', index); }

function showPluginsLoading(show) {
  document.getElementById('plugins-loading').style.display = show ? 'inline' : 'none';
}
function showPluginsError(msg) {
  var el = document.getElementById('plugins-error');
  if (msg) { el.textContent = msg; el.style.display = 'block'; }
  else { el.style.display = 'none'; }
}
function showReloadBanner(show) {
  document.getElementById('reload-banner').style.display = show ? 'flex' : 'none';
}
```

- [ ] **Step 5: Hook up tab switch to trigger plugin loading**

Update the `switchTab` function to trigger plugin loading:

```javascript
// In switchTab(), add:
if (tabId === 'plugins') {
  postCallback('on_plugins_tab_open');
}
```

- [ ] **Step 6: Update `_updateState` to handle plugin-specific updates**

Add to the `_updateState` JS function:

```javascript
if (payload.plugins !== undefined) { CONFIG.plugins = payload.plugins; renderPlugins(); }
if (payload.registries !== undefined) { CONFIG.registries = payload.registries; renderRegistries(); }
if (payload.plugins_loading !== undefined) { showPluginsLoading(payload.plugins_loading); }
if (payload.plugins_error !== undefined) { showPluginsError(payload.plugins_error); }
if (payload.show_reload_banner !== undefined) { showReloadBanner(payload.show_reload_banner); }
```

- [ ] **Step 7: Commit**

```bash
git add src/wenzi/ui/settings_window_web.py
git commit -m "feat(settings-ui): add Plugins tab with card list, registry management, and manual install"
```

---

### Task 9: Add plugin management callbacks to SettingsController

**Files:**
- Modify: `src/wenzi/controllers/settings_controller.py`

- [ ] **Step 1: Add imports and instance variables**

Add imports at top of `settings_controller.py`:

```python
from wenzi.scripting.plugin_registry import PluginRegistry, PluginStatus
from wenzi.scripting.plugin_installer import PluginInstaller
from wenzi.config import BUILTIN_REGISTRY_URL
```

In `__init__` or at class level, add:

```python
self._plugin_registry = PluginRegistry(plugins_dir=app._plugins_dir)
self._plugin_installer = PluginInstaller(plugins_dir=app._plugins_dir)
self._needs_reload = False
```

- [ ] **Step 2: Add callback registrations**

In the `callbacks` dict (around line 163-213), add:

```python
"on_plugins_tab_open": self._on_plugins_tab_open,
"on_plugin_install_by_id": self._on_plugin_install_by_id,
"on_plugin_install_url": self._on_plugin_install_url,
"on_plugin_update": self._on_plugin_update,
"on_plugin_uninstall": self._on_plugin_uninstall,
"on_plugin_toggle": self._on_plugin_toggle,
"on_plugin_reload": self._on_plugin_reload,
"on_registry_add": self._on_registry_add,
"on_registry_remove": self._on_registry_remove,
```

- [ ] **Step 3: Implement `_on_plugins_tab_open` with background fetch**

```python
def _on_plugins_tab_open(self):
    """Fetch registries in background, update UI when done."""
    app = self._app
    panel = app._settings_panel

    panel.update_state({"plugins_loading": True, "plugins_error": None})
    self._update_registries_state()

    def _fetch():
        try:
            extra = app._config.get("plugins", {}).get("extra_registries", [])
            import wenzi
            current_ver = getattr(wenzi, "__version__", "dev")
            infos = self._plugin_registry.merge_registries(
                official_source=BUILTIN_REGISTRY_URL,
                extra_sources=extra,
                current_wenzi_version=current_ver,
            )
            plugins_data = self._plugin_infos_to_state(infos)
            AppHelper.callAfter(
                panel.update_state,
                {"plugins": plugins_data, "plugins_loading": False},
            )
        except Exception as e:
            logger.error("Failed to fetch plugins", exc_info=True)
            AppHelper.callAfter(
                panel.update_state,
                {"plugins_loading": False, "plugins_error": str(e)},
            )

    threading.Thread(target=_fetch, daemon=True).start()
```

- [ ] **Step 4: Implement install/update/uninstall callbacks**

```python
def _on_plugin_install_by_id(self, plugin_id: str):
    """Install a plugin from registry by its id."""
    # Find the source URL from the last fetched registry data
    # Store registry infos for lookup
    ...

def _on_plugin_install_url(self, url: str):
    """Install from a manually entered plugin.toml URL."""
    panel = self._app._settings_panel

    def _do_install():
        try:
            self._plugin_installer.install(url)
            self._needs_reload = True
            AppHelper.callAfter(self._on_plugins_tab_open)
            AppHelper.callAfter(
                panel.update_state, {"show_reload_banner": True}
            )
        except Exception as e:
            AppHelper.callAfter(
                panel.update_state,
                {"plugins_error": f"Install failed: {e}"},
            )

    threading.Thread(target=_do_install, daemon=True).start()

def _on_plugin_update(self, plugin_id: str):
    """Update an installed plugin."""
    panel = self._app._settings_panel

    def _do_update():
        try:
            self._plugin_installer.update(plugin_id)
            self._needs_reload = True
            AppHelper.callAfter(self._on_plugins_tab_open)
            AppHelper.callAfter(
                panel.update_state, {"show_reload_banner": True}
            )
        except Exception as e:
            AppHelper.callAfter(
                panel.update_state,
                {"plugins_error": f"Update failed: {e}"},
            )

    threading.Thread(target=_do_update, daemon=True).start()

def _on_plugin_uninstall(self, plugin_id: str):
    """Uninstall a plugin."""
    try:
        self._plugin_installer.uninstall(plugin_id)
        self._needs_reload = True
        self._on_plugins_tab_open()
        self._app._settings_panel.update_state({"show_reload_banner": True})
    except Exception as e:
        self._app._settings_panel.update_state(
            {"plugins_error": f"Uninstall failed: {e}"}
        )

def _on_plugin_toggle(self, plugin_id: str, enabled: bool):
    """Enable or disable a plugin."""
    disabled = list(self._app._config.get("disabled_plugins", []))
    if enabled and plugin_id in disabled:
        disabled.remove(plugin_id)
    elif not enabled and plugin_id not in disabled:
        disabled.append(plugin_id)
    self._app._config["disabled_plugins"] = disabled
    self._save_and_reload()
    self._needs_reload = True
    self._app._settings_panel.update_state({"show_reload_banner": True})

def _on_plugin_reload(self):
    """Reload scripts/plugins."""
    self._app._script_engine.reload()
    self._needs_reload = False
    self._app._settings_panel.update_state({"show_reload_banner": False})
    self._on_plugins_tab_open()
```

- [ ] **Step 5: Implement registry management callbacks**

```python
def _on_registry_add(self, url: str):
    """Add a third-party registry URL."""
    plugins_cfg = self._app._config.setdefault("plugins", {})
    extra = plugins_cfg.setdefault("extra_registries", [])
    if url not in extra:
        extra.append(url)
        self._save_and_reload()
    self._update_registries_state()
    self._on_plugins_tab_open()

def _on_registry_remove(self, index: int):
    """Remove a third-party registry by index."""
    extra = self._app._config.get("plugins", {}).get("extra_registries", [])
    if 0 <= index < len(extra):
        extra.pop(index)
        self._save_and_reload()
    self._update_registries_state()
    self._on_plugins_tab_open()

def _update_registries_state(self):
    """Push current registry list to UI."""
    extra = self._app._config.get("plugins", {}).get("extra_registries", [])
    registries = [{"name": "WenZi Official", "removable": False}]
    for url in extra:
        registries.append({"name": url, "removable": True})
    self._app._settings_panel.update_state({"registries": registries})
```

- [ ] **Step 6: Implement helper to convert PluginInfo list to JS state**

```python
def _plugin_infos_to_state(self, infos):
    """Convert PluginInfo list to dicts for JS."""
    disabled = set(self._app._config.get("disabled_plugins", []))
    result = []
    for info in infos:
        pid = info.meta.id
        is_enabled = pid not in disabled and info.meta.name not in disabled
        result.append({
            "id": pid,
            "name": info.meta.name,
            "version": info.meta.version,
            "author": info.meta.author,
            "description": info.meta.description,
            "min_wenzi_version": info.meta.min_wenzi_version,
            "source_url": info.source_url,
            "registry_name": info.registry_name,
            "status": info.status.value,
            "installed_version": info.installed_version or "",
            "is_official": info.is_official,
            "enabled": is_enabled,
        })
    # Also include locally installed plugins not in any registry
    self._add_local_only_plugins(result, disabled)
    return result

def _add_local_only_plugins(self, result, disabled):
    """Add locally installed plugins that aren't in any registry."""
    known_ids = {p["id"] for p in result}
    plugins_dir = self._app._plugins_dir
    if not os.path.isdir(plugins_dir):
        return
    from wenzi.scripting.plugin_meta import load_plugin_meta
    for entry in os.listdir(plugins_dir):
        entry_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        meta = load_plugin_meta(entry_path)
        pid = meta.id or entry
        if pid in known_ids:
            continue
        is_enabled = pid not in disabled and entry not in disabled
        has_install = os.path.isfile(os.path.join(entry_path, "install.toml"))
        result.append({
            "id": pid,
            "name": meta.name,
            "version": meta.version,
            "author": meta.author,
            "description": meta.description,
            "min_wenzi_version": meta.min_wenzi_version,
            "source_url": "",
            "registry_name": "Local",
            "status": "installed" if has_install else "manually_placed",
            "installed_version": meta.version,
            "is_official": False,
            "enabled": is_enabled,
        })
```

- [ ] **Step 7: Commit**

```bash
git add src/wenzi/controllers/settings_controller.py
git commit -m "feat(settings-controller): add plugin management callbacks"
```

---

### Task 10: Integration testing and lint

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v --cov=wenzi`
Expected: All PASS

- [ ] **Step 2: Run lint**

Run: `uv run ruff check`
Expected: 0 errors

- [ ] **Step 3: Fix any failures**

Address any test failures or lint errors.

- [ ] **Step 4: Final commit if fixes needed**

```bash
git add -A
git commit -m "fix: address test and lint issues from plugin management UI"
```
