"""Tests for universal_action parameter on chooser decorators and registration."""

from wenzi.scripting.api.chooser import ChooserAPI


class TestCommandUniversalAction:
    def setup_method(self):
        self.api = ChooserAPI()

    def test_register_command_default_no_ua(self):
        self.api.register_command("test", "Test", action=lambda a: None)
        entry = self.api._command_source._commands["test"]
        assert entry.universal_action is False

    def test_register_command_with_ua(self):
        self.api.register_command(
            "test", "Test", action=lambda a: None, universal_action=True,
        )
        entry = self.api._command_source._commands["test"]
        assert entry.universal_action is True

    def test_command_decorator_default_no_ua(self):
        @self.api.command("test", title="Test")
        def handler(args):
            pass

        entry = self.api._command_source._commands["test"]
        assert entry.universal_action is False

    def test_command_decorator_with_ua(self):
        @self.api.command("test", title="Test", universal_action=True)
        def handler(args):
            pass

        entry = self.api._command_source._commands["test"]
        assert entry.universal_action is True


class TestSourceUniversalAction:
    def setup_method(self):
        self.api = ChooserAPI()

    def test_source_decorator_default_no_ua(self):
        @self.api.source("test-src", prefix="ts")
        def search(query):
            return []

        src = self.api._panel._sources["test-src"]
        assert src.universal_action is False

    def test_source_decorator_with_ua(self):
        @self.api.source("test-src", prefix="ts", universal_action=True)
        def search(query):
            return []

        src = self.api._panel._sources["test-src"]
        assert src.universal_action is True
