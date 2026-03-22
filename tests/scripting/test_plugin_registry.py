"""Tests for plugin registry — fetch, merge, status calculation."""

from wenzi.scripting.plugin_meta import PluginMeta, load_install_info
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
        assert PluginStatus.PINNED.value == "pinned"


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


class TestParseRegistry:
    def test_parse_registry_toml(self, tmp_path):
        registry_file = tmp_path / "registry.toml"
        registry_file.write_text(
            'name = "Test Registry"\n\n'
            '[[plugins]]\nid = "com.test.alpha"\nname = "Alpha"\n'
            'description = "Alpha plugin"\nversion = "1.0.0"\nauthor = "Alice"\n'
            'min_wenzi_version = "0.1.0"\nsource = "https://example.com/alpha/plugin.toml"\n\n'
            '[[plugins]]\nid = "com.test.beta"\nname = "Beta"\n'
            'version = "2.0.0"\nsource = "https://example.com/beta/plugin.toml"\n'
        )
        registry = PluginRegistry(plugins_dir=str(tmp_path / "plugins"))
        entries = registry.parse_registry(str(registry_file))
        assert len(entries) == 2
        assert entries[0]["id"] == "com.test.alpha"
        assert entries[1]["id"] == "com.test.beta"

    def test_parse_registry_name(self, tmp_path):
        registry_file = tmp_path / "registry.toml"
        registry_file.write_text('name = "My Registry"\n')
        registry = PluginRegistry(plugins_dir=str(tmp_path / "plugins"))
        name, _ = registry.parse_registry_with_name(str(registry_file))
        assert name == "My Registry"


class TestLoadInstallInfo:
    def test_reads_install_toml(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "my_plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "install.toml").write_text(
            '[install]\nsource_url = "https://example.com/plugin.toml"\n'
            'installed_version = "1.0.0"\ninstalled_at = "2026-03-22T10:00:00"\n'
        )
        info = load_install_info(str(plugin_dir))
        assert info["source_url"] == "https://example.com/plugin.toml"
        assert info["installed_version"] == "1.0.0"

    def test_missing_install_toml(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugin_dir = plugins_dir / "manual"
        plugin_dir.mkdir(parents=True)
        assert load_install_info(str(plugin_dir)) is None


class TestComputeStatus:
    def test_not_installed(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.new", "1.0.0", "0.1.0", "0.2.0")
        assert status == PluginStatus.NOT_INSTALLED
        assert ver is None

    def test_installed_up_to_date(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "1.0.0"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "1.0.0", "0.1.0", "0.2.0")
        assert status == PluginStatus.INSTALLED
        assert ver == "1.0.0"

    def test_update_available(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "1.0.0"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "2.0.0", "0.1.0", "0.2.0")
        assert status == PluginStatus.UPDATE_AVAILABLE
        assert ver == "1.0.0"

    def test_manually_placed(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "manual"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.manual"\nname = "M"\nversion = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, _ = registry.compute_status("com.test.manual", "1.0.0", "0.1.0", "0.2.0")
        assert status == PluginStatus.MANUALLY_PLACED

    def test_incompatible(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, _ = registry.compute_status("com.test.new", "1.0.0", "9.0.0", "0.2.0")
        assert status == PluginStatus.INCOMPATIBLE


class TestMergeRegistries:
    def test_official_takes_priority(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        official = tmp_path / "official.toml"
        official.write_text(
            'name = "Official"\n[[plugins]]\nid = "com.test.shared"\n'
            'name = "Official Version"\nversion = "1.0.0"\nsource = "https://official/plugin.toml"\n'
        )
        third_party = tmp_path / "community.toml"
        third_party.write_text(
            'name = "Community"\n[[plugins]]\nid = "com.test.shared"\n'
            'name = "Community Version"\nversion = "2.0.0"\nsource = "https://community/plugin.toml"\n\n'
            '[[plugins]]\nid = "com.test.unique"\nname = "Unique"\n'
            'version = "1.0.0"\nsource = "https://community/unique/plugin.toml"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        result = registry.merge_registries(str(official), [str(third_party)], "1.0.0")
        ids = [r.meta.id for r in result]
        assert ids.count("com.test.shared") == 1
        shared = [r for r in result if r.meta.id == "com.test.shared"][0]
        assert shared.meta.name == "Official Version"
        assert shared.is_official is True
        unique = [r for r in result if r.meta.id == "com.test.unique"][0]
        assert unique.is_official is False


class TestPinnedStatus:
    def test_pinned_with_update_available(self, tmp_path):
        """Pinned plugin with newer registry version -> PINNED, not UPDATE_AVAILABLE."""
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "1.0.0"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "1.0.0"\n'
            'pinned_ref = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "2.0.0", "", "1.0.0")
        assert status == PluginStatus.PINNED
        assert ver == "1.0.0"

    def test_pinned_at_latest_version(self, tmp_path):
        """Pinned plugin at same version as registry -> INSTALLED."""
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "2.0.0"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "2.0.0"\n'
            'pinned_ref = "2.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "2.0.0", "", "1.0.0")
        assert status == PluginStatus.INSTALLED
        assert ver == "2.0.0"

    def test_non_pinned_still_shows_update(self, tmp_path):
        """Non-pinned plugin with update -> UPDATE_AVAILABLE (unchanged behavior)."""
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "1.0.0"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "1.0.0"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "2.0.0", "", "1.0.0")
        assert status == PluginStatus.UPDATE_AVAILABLE
        assert ver == "1.0.0"

    def test_pinned_with_nonsemver_version(self, tmp_path):
        """Pinned from branch/commit with non-semver version -> PINNED."""
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "alpha"
        d.mkdir(parents=True)
        (d / "plugin.toml").write_text(
            '[plugin]\nid = "com.test.alpha"\nname = "A"\nversion = "dev"\n'
        )
        (d / "install.toml").write_text(
            '[install]\nsource_url = "x"\ninstalled_version = "dev"\n'
            'pinned_ref = "feat/experiment"\n'
        )
        registry = PluginRegistry(plugins_dir=str(plugins_dir))
        status, ver = registry.compute_status("com.test.alpha", "1.0.0", "", "1.0.0")
        assert status == PluginStatus.PINNED
        assert ver == "dev"
