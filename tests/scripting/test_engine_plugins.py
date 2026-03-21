"""Tests for ScriptEngine plugin loading."""

import sys
import types
from unittest.mock import patch


class TestLoadPlugins:
    """Test _load_plugins method."""

    def test_loads_plugin_with_setup(self, tmp_path):
        """Plugin with setup(wz) is loaded and setup called."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create a minimal plugin
        plugin = plugins_dir / "test_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            "SETUP_CALLED = False\n"
            "def setup(wz):\n"
            "    global SETUP_CALLED\n"
            "    SETUP_CALLED = True\n"
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()

        # Verify setup was called
        import test_plug
        assert test_plug.SETUP_CALLED is True

        # Cleanup sys.modules and sys.path
        for name in list(sys.modules):
            if name.startswith("test_plug"):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_skips_disabled_plugin(self, tmp_path):
        """Plugins in disabled_plugins config are skipped."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "disabled_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            "def setup(wz): raise RuntimeError('should not be called')\n"
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
            config={"disabled_plugins": ["disabled_plug"]},
        )
        # Should not raise
        engine._load_plugins()

        # Cleanup
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_skips_hidden_directories(self, tmp_path):
        """Directories starting with . or _ are skipped."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        for name in [".hidden", "_private", "__pycache__"]:
            d = plugins_dir / name
            d.mkdir()
            (d / "__init__.py").write_text(
                "def setup(wz): raise RuntimeError('should not load')\n"
            )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()  # Should not raise

        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_skips_directory_without_init(self, tmp_path):
        """Directories without __init__.py are skipped."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        (plugins_dir / "not_a_plugin").mkdir()

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()  # Should not raise

        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_plugin_error_does_not_block_others(self, tmp_path):
        """A failing plugin does not prevent other plugins from loading."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Bad plugin (alphabetically first)
        bad = plugins_dir / "aaa_bad"
        bad.mkdir()
        (bad / "__init__.py").write_text(
            "def setup(wz): raise RuntimeError('plugin error')\n"
        )

        # Good plugin
        good = plugins_dir / "zzz_good"
        good.mkdir()
        (good / "__init__.py").write_text(
            "LOADED = False\n"
            "def setup(wz):\n"
            "    global LOADED\n"
            "    LOADED = True\n"
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()

        import zzz_good
        assert zzz_good.LOADED is True

        # Cleanup
        for name in list(sys.modules):
            if name.startswith(("aaa_bad", "zzz_good")):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_nonexistent_plugins_dir(self, tmp_path):
        """Non-existent plugins directory is handled gracefully."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(tmp_path / "nonexistent"),
        )
        engine._load_plugins()  # Should not raise

    def test_no_setup_function_warns(self, tmp_path):
        """Plugin without setup() logs a warning."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "no_setup_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text("# No setup function\n")

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        with patch("wenzi.scripting.engine.logger") as mock_logger:
            engine._load_plugins()
            mock_logger.warning.assert_called_once()

        # Cleanup
        for name in list(sys.modules):
            if name.startswith("no_setup_plug"):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))


class TestPurgePluginModules:
    """Test that _purge_user_modules also cleans plugin modules."""

    def test_purges_plugins_dir_modules(self, tmp_path):
        """Modules from plugins_dir are purged during reload."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Create a plugin and manually register its module
        plugin = plugins_dir / "purge_test"
        plugin.mkdir()
        init_file = plugin / "__init__.py"
        init_file.write_text("X = 1\n")

        # Simulate a loaded module
        mod = types.ModuleType("purge_test")
        mod.__file__ = str(init_file)
        sys.modules["purge_test"] = mod

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._purge_user_modules()

        assert "purge_test" not in sys.modules


class TestPluginMetadata:
    """Test that engine reads and stores plugin metadata."""

    def test_stores_metadata_from_toml(self, tmp_path):
        """Plugin with plugin.toml has its metadata stored."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "meta_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text("def setup(wz): pass\n")
        (plugin / "plugin.toml").write_text(
            '[plugin]\n'
            'name = "Meta Plugin"\n'
            'description = "A test"\n'
            'version = "1.0.0"\n'
            'author = "Tester"\n'
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()

        metas = engine.get_plugin_metas()
        assert "meta_plug" in metas
        assert metas["meta_plug"].name == "Meta Plugin"
        assert metas["meta_plug"].version == "1.0.0"

        # Cleanup
        for name in list(sys.modules):
            if name.startswith("meta_plug"):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_fallback_when_no_toml(self, tmp_path):
        """Plugin without plugin.toml uses directory name."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "simple_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text("def setup(wz): pass\n")

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        engine._load_plugins()

        metas = engine.get_plugin_metas()
        assert "simple_plug" in metas
        assert metas["simple_plug"].name == "simple_plug"

        # Cleanup
        for name in list(sys.modules):
            if name.startswith("simple_plug"):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_skips_incompatible_plugin(self, tmp_path):
        """Plugin with min_wenzi_version higher than current is skipped."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "future_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            "def setup(wz): raise RuntimeError('should not be called')\n"
        )
        (plugin / "plugin.toml").write_text(
            '[plugin]\nname = "Future"\nmin_wenzi_version = "99.0.0"\n'
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        # Patch __version__ to a real version (default is "dev" which skips check)
        with patch("wenzi.__version__", "0.1.7"):
            engine._load_plugins()

        # Plugin was not imported (setup() would raise RuntimeError)
        assert "future_plug" not in sys.modules

        # Metadata is still stored (for Settings panel to show reason)
        metas = engine.get_plugin_metas()
        assert "future_plug" in metas

        # Cleanup
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))

    def test_dev_version_always_compatible(self, tmp_path):
        """In dev mode, all plugins are compatible regardless of min_wenzi_version."""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        plugin = plugins_dir / "dev_plug"
        plugin.mkdir()
        (plugin / "__init__.py").write_text(
            "LOADED = False\n"
            "def setup(wz):\n"
            "    global LOADED\n"
            "    LOADED = True\n"
        )
        (plugin / "plugin.toml").write_text(
            '[plugin]\nname = "Dev"\nmin_wenzi_version = "99.0.0"\n'
        )

        from wenzi.scripting.engine import ScriptEngine

        engine = ScriptEngine(
            script_dir=str(scripts_dir),
            plugins_dir=str(plugins_dir),
        )
        # wenzi.__version__ is "dev" in test env — plugin should load
        engine._load_plugins()

        import dev_plug
        assert dev_plug.LOADED is True

        # Cleanup
        for name in list(sys.modules):
            if name.startswith("dev_plug"):
                del sys.modules[name]
        if str(plugins_dir) in sys.path:
            sys.path.remove(str(plugins_dir))
