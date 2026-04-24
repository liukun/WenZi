"""Tests for wz.script — plugin-facing snippet script registration."""

from __future__ import annotations

import pytest

from wenzi.scripting import script_registry as sr
from wenzi.scripting.api.script import ScriptAPI

pytestmark = pytest.mark.usefixtures("isolate_script_registry")


class TestPluginNamespace:
    def test_register_inside_plugin_context_prefixes_name(self):
        api = ScriptAPI()
        with api._plugin_context("my-plugin"):
            api.register("ts", lambda: "2026")
        assert sr.lookup("my-plugin.ts")() == "2026"
        assert sr.lookup("ts") is None

    def test_register_outside_plugin_uses_bare_name(self):
        api = ScriptAPI()
        api.register("user_script", lambda: "hi")
        assert sr.lookup("user_script")() == "hi"

    def test_plugin_context_resets_after_block(self):
        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "A")
        # outside the block the bare name should be used
        api.register("bar", lambda: "B")
        assert sr.lookup("plugin-a.foo") is not None
        assert sr.lookup("bar") is not None

    def test_two_plugins_can_use_same_short_name(self):
        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "A")
        with api._plugin_context("plugin-b"):
            api.register("foo", lambda: "B")
        assert sr.lookup("plugin-a.foo")() == "A"
        assert sr.lookup("plugin-b.foo")() == "B"

    def test_same_plugin_duplicate_short_name_raises(self):
        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "1")
            with pytest.raises(ValueError, match="already registered"):
                api.register("foo", lambda: "2")

    def test_plugin_context_resets_on_exception(self):
        api = ScriptAPI()
        with pytest.raises(RuntimeError):
            with api._plugin_context("plugin-a"):
                raise RuntimeError("setup failed")
        assert api._current_plugin_id is None


class TestClearOwned:
    def test_unregisters_plugin_scripts(self):
        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "x")
        with api._plugin_context("plugin-b"):
            api.register("bar", lambda: "y")

        api._clear_owned()

        assert sr.lookup("plugin-a.foo") is None
        assert sr.lookup("plugin-b.bar") is None

    def test_does_not_touch_built_ins(self):
        # snippet_source registers built-ins like `date` at import time.
        from wenzi.scripting.sources import snippet_source  # noqa: F401

        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "x")
        api._clear_owned()

        assert sr.lookup("date") is not None

    def test_lets_plugin_re_register_after_reload(self):
        api = ScriptAPI()
        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "v1")

        api._clear_owned()

        with api._plugin_context("plugin-a"):
            api.register("foo", lambda: "v2")
        assert sr.lookup("plugin-a.foo")() == "v2"

    def test_unregisters_user_scripts(self):
        # User init.py registers without a plugin context — bare names
        # must still be tracked so reload can clean them up.
        api = ScriptAPI()
        api.register("user_foo", lambda: "x")
        api._clear_owned()
        assert sr.lookup("user_foo") is None

    def test_lets_user_re_register_after_reload(self):
        api = ScriptAPI()
        api.register("user_foo", lambda: "v1")
        api._clear_owned()
        api.register("user_foo", lambda: "v2")
        assert sr.lookup("user_foo")() == "v2"
