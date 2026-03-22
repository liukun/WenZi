"""Tests for PluginInstaller — install, update, uninstall plugins."""

from __future__ import annotations

import http.server
import os
import threading

import pytest

from wenzi.scripting.plugin_installer import PluginInstaller
from wenzi.scripting.plugin_meta import INSTALL_TOML, load_plugin_meta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def plugins_dir(tmp_path):
    """Return a temporary plugins directory."""
    d = tmp_path / "plugins"
    d.mkdir()
    return str(d)


@pytest.fixture()
def serve_dir(tmp_path):
    """Return a temporary directory to serve files from over HTTP."""
    d = tmp_path / "serve"
    d.mkdir()
    return d


@pytest.fixture()
def http_server(serve_dir):
    """Spin up a local HTTP server serving files from *serve_dir*."""

    class SilentHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, format, *args):  # noqa: A002
            # Suppress server logs during tests
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), SilentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# TestInstall
# ---------------------------------------------------------------------------


class TestInstall:
    def test_install_from_url(self, plugins_dir, serve_dir, http_server):
        """Download plugin.toml + files from URL and verify install.toml is written."""
        # Set up files in serve_dir
        (serve_dir / "myplugin").mkdir()
        (serve_dir / "myplugin" / "__init__.py").write_bytes(b"# myplugin")
        (serve_dir / "myplugin" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.myplugin"\n'
            'name = "My Plugin"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py"]\n'
        )

        installer = PluginInstaller(plugins_dir)
        install_dir = installer.install(f"{http_server}/myplugin/plugin.toml")

        # plugin.toml written
        assert os.path.isfile(os.path.join(install_dir, "plugin.toml"))
        # downloaded file written
        assert os.path.isfile(os.path.join(install_dir, "__init__.py"))
        # install.toml written
        install_toml_path = os.path.join(install_dir, INSTALL_TOML)
        assert os.path.isfile(install_toml_path)
        content = open(install_toml_path).read()
        assert "source_url" in content
        assert "1.0.0" in content

    def test_install_from_local_path(self, plugins_dir, tmp_path):
        """Install from a local file path (not HTTP)."""
        local = tmp_path / "local_plugin"
        local.mkdir()
        (local / "__init__.py").write_bytes(b"# local")
        (local / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.localplugin"\n'
            'name = "Local Plugin"\n'
            'version = "0.1.0"\n'
            'files = ["__init__.py"]\n'
        )

        installer = PluginInstaller(plugins_dir)
        install_dir = installer.install(str(local / "plugin.toml"))

        assert os.path.isfile(os.path.join(install_dir, "__init__.py"))
        assert os.path.isfile(os.path.join(install_dir, INSTALL_TOML))
        meta = load_plugin_meta(install_dir)
        assert meta.id == "com.example.localplugin"

    def test_install_rollback_on_failure(self, plugins_dir, serve_dir, http_server):
        """If a file listed in plugin.toml is missing, the install dir is cleaned up."""
        (serve_dir / "broken").mkdir()
        (serve_dir / "broken" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.broken"\n'
            'name = "Broken"\n'
            'version = "1.0.0"\n'
            'files = ["missing_file.py"]\n'  # this file does not exist
        )
        # Do NOT create missing_file.py — download should fail

        installer = PluginInstaller(plugins_dir)
        with pytest.raises(Exception):
            installer.install(f"{http_server}/broken/plugin.toml")

        # The install dir should have been rolled back (removed)
        assert not any(
            os.path.isdir(os.path.join(plugins_dir, d))
            for d in os.listdir(plugins_dir)
        )

    def test_install_dir_collision_different_id_gets_suffix(self, plugins_dir, serve_dir, http_server):
        """If the target dir already exists for a different plugin id, append -2."""
        # Pre-create a dir named 'myplugin' with a different id
        existing = os.path.join(plugins_dir, "myplugin")
        os.makedirs(existing)
        with open(os.path.join(existing, "plugin.toml"), "w") as f:
            f.write(
                '[plugin]\n'
                'id = "com.other.myplugin"\n'
                'name = "Other"\n'
                'version = "1.0.0"\n'
            )

        (serve_dir / "myplugin").mkdir()
        (serve_dir / "myplugin" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.myplugin"\n'
            'name = "New Plugin"\n'
            'version = "1.0.0"\n'
            'files = []\n'
        )

        installer = PluginInstaller(plugins_dir)
        install_dir = installer.install(f"{http_server}/myplugin/plugin.toml")

        # Should have installed into myplugin-2
        assert os.path.basename(install_dir) == "myplugin-2"
        assert os.path.isdir(install_dir)


# ---------------------------------------------------------------------------
# TestUpdate
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_update_overwrites_files(self, plugins_dir, serve_dir, http_server):
        """Update downloads a newer version and overwrites existing files."""
        # Initial install
        (serve_dir / "alpha").mkdir()
        (serve_dir / "alpha" / "__init__.py").write_bytes(b"# v1")
        (serve_dir / "alpha" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.alpha"\n'
            'name = "Alpha"\n'
            'version = "1.0.0"\n'
            'files = ["__init__.py"]\n'
        )

        installer = PluginInstaller(plugins_dir)
        install_dir = installer.install(f"{http_server}/alpha/plugin.toml")
        assert open(os.path.join(install_dir, "__init__.py"), "rb").read() == b"# v1"

        # Update serve_dir to v2
        (serve_dir / "alpha" / "__init__.py").write_bytes(b"# v2")
        (serve_dir / "alpha" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.alpha"\n'
            'name = "Alpha"\n'
            'version = "2.0.0"\n'
            'files = ["__init__.py"]\n'
        )

        installer.update("com.example.alpha")
        assert open(os.path.join(install_dir, "__init__.py"), "rb").read() == b"# v2"
        meta = load_plugin_meta(install_dir)
        assert meta.version == "2.0.0"


# ---------------------------------------------------------------------------
# TestUninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_uninstall_removes_directory(self, plugins_dir, serve_dir, http_server):
        """Uninstall deletes the plugin directory."""
        (serve_dir / "gamma").mkdir()
        (serve_dir / "gamma" / "plugin.toml").write_text(
            '[plugin]\n'
            'id = "com.example.gamma"\n'
            'name = "Gamma"\n'
            'version = "1.0.0"\n'
            'files = []\n'
        )

        installer = PluginInstaller(plugins_dir)
        install_dir = installer.install(f"{http_server}/gamma/plugin.toml")
        assert os.path.isdir(install_dir)

        installer.uninstall("com.example.gamma")
        assert not os.path.isdir(install_dir)

    def test_uninstall_not_found_raises(self, plugins_dir):
        """Uninstalling a non-existent plugin raises ValueError."""
        installer = PluginInstaller(plugins_dir)
        with pytest.raises(ValueError, match="not found"):
            installer.uninstall("com.example.nonexistent")
