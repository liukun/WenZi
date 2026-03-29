"""Tests for the wz.menu API."""

from __future__ import annotations

from wenzi.statusbar import StatusMenuItem

from wenzi.scripting.api.menu import MenuAPI


def _build_menu():
    """Build a small menu tree for testing."""
    root = StatusMenuItem("root")

    item_a = StatusMenuItem("Alpha", callback=lambda _: None)
    item_a.state = 1
    root.add(item_a)

    root.add(None)  # separator

    parent = StatusMenuItem("Parent")
    child1 = StatusMenuItem("Child1", callback=lambda _: None)
    child2 = StatusMenuItem("Child2")
    parent.add(child1)
    parent.add(child2)
    root.add(parent)

    item_b = StatusMenuItem("Beta", callback=lambda _: None)
    root.add(item_b)

    return root


class TestMenuList:
    def test_list_empty_when_no_root(self):
        api = MenuAPI()
        assert api.list() == []

    def test_list_returns_top_level_items(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list()

        titles = [i["title"] for i in items]
        assert titles == ["Alpha", "Parent", "Beta"]

    def test_list_skips_separators(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list()
        # 3 real items, separator excluded
        assert len(items) == 3

    def test_list_includes_children(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list()

        parent = [i for i in items if i["title"] == "Parent"][0]
        assert len(parent["children"]) == 2
        assert parent["children"][0]["title"] == "Child1"
        assert parent["children"][1]["title"] == "Child2"

    def test_list_item_fields(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list()

        alpha = items[0]
        assert alpha["title"] == "Alpha"
        assert alpha["state"] == 1
        assert alpha["has_action"] is True

        parent = items[1]
        assert parent["has_action"] is False
        assert "children" in parent

    def test_list_flat(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list(flat=True)

        titles = [i["title"] for i in items]
        assert titles == ["Alpha", "Parent", "Child1", "Child2", "Beta"]

    def test_list_flat_has_path(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        items = api.list(flat=True)

        paths = {i["title"]: i["path"] for i in items}
        assert paths["Alpha"] == "Alpha"
        assert paths["Child1"] == "Parent > Child1"
        assert paths["Child2"] == "Parent > Child2"


class TestMenuTrigger:
    def test_trigger_returns_false_when_no_root(self):
        api = MenuAPI()
        assert api.trigger("anything") is False

    def test_trigger_returns_false_for_missing_item(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        assert api.trigger("NonExistent") is False

    def test_trigger_returns_false_for_item_without_callback(self):
        api = MenuAPI()
        api._set_root(_build_menu())
        # Child2 has no callback
        assert api.trigger("Parent > Child2") is False

    def test_trigger_calls_callback(self):
        from unittest.mock import patch

        with patch("PyObjCTools.AppHelper.callAfter", side_effect=lambda fn, *a: fn(*a)):
            called = []
            api = MenuAPI()
            root = StatusMenuItem("root")
            item = StatusMenuItem("Foo", callback=lambda sender: called.append(sender))
            root.add(item)
            api._set_root(root)

            result = api.trigger("Foo")
            assert result is True
            assert len(called) == 1

    def test_trigger_nested_item(self):
        from unittest.mock import patch

        with patch("PyObjCTools.AppHelper.callAfter", side_effect=lambda fn, *a: fn(*a)):
            called = []
            api = MenuAPI()
            root = StatusMenuItem("root")
            parent = StatusMenuItem("Parent")
            child = StatusMenuItem("Child", callback=lambda s: called.append(s))
            parent.add(child)
            root.add(parent)
            api._set_root(root)

            result = api.trigger("Parent > Child")
            assert result is True
            assert len(called) == 1


class TestWZNamespaceIntegration:
    def test_wz_menu_property_returns_menu_api(self):
        from wenzi.scripting.registry import ScriptingRegistry
        from wenzi.scripting.api import _WZNamespace

        registry = ScriptingRegistry()
        wz = _WZNamespace(registry)
        assert wz.menu is not None
        from wenzi.scripting.api.menu import MenuAPI
        assert isinstance(wz.menu, MenuAPI)

    def test_wz_menu_is_same_instance(self):
        from wenzi.scripting.registry import ScriptingRegistry
        from wenzi.scripting.api import _WZNamespace

        registry = ScriptingRegistry()
        wz = _WZNamespace(registry)
        assert wz.menu is wz.menu
