"""Tests for the file search data source."""

from unittest.mock import patch

from wenzi.scripting.sources.file_source import (
    FileSource,
    _file_type_label,
    _mdfind,
)


class TestFileTypeLabel:
    def test_folder(self):
        with patch("os.path.isdir", return_value=True):
            assert _file_type_label("/some/folder") == "Folder"

    def test_known_extensions(self):
        with patch("os.path.isdir", return_value=False):
            assert _file_type_label("doc.pdf") == "PDF"
            assert _file_type_label("code.py") == "Python"
            assert _file_type_label("pic.png") == "Image"
            assert _file_type_label("app.app") == "Application"
            assert _file_type_label("data.json") == "JSON"

    def test_unknown_extension(self):
        with patch("os.path.isdir", return_value=False):
            assert _file_type_label("file.xyz") == "File"


class TestMdfind:
    def test_returns_paths(self):
        paths = ["/Users/test/readme.md", "/Users/test/README.txt"]
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=paths,
        ):
            result = _mdfind("readme")
            assert len(result) == 2
            assert result[0] == "/Users/test/readme.md"

    def test_empty_result(self):
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=[],
        ):
            result = _mdfind("nonexistent")
            assert result == []

    def test_max_results_passed_through(self):
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=[],
        ) as mock_search:
            _mdfind("file", max_results=5)
            mock_search.assert_called_once_with("file", 5)


class TestFileSource:
    def test_empty_query_returns_empty(self):
        source = FileSource()
        assert source.search("") == []
        assert source.search("   ") == []

    def test_search_returns_items(self):
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=["/Users/test/readme.md"],
        ), patch("os.path.exists", return_value=True):
            source = FileSource()
            items = source.search("readme")
            assert len(items) == 1
            assert items[0].title == "readme.md"
            assert items[0].reveal_path == "/Users/test/readme.md"
            assert items[0].action is not None

    def test_nonexistent_paths_filtered(self):
        def exists_side_effect(path):
            return path == "/exists/file.txt"

        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=["/gone/file.txt", "/exists/file.txt"],
        ), patch("os.path.exists", side_effect=exists_side_effect):
            source = FileSource()
            items = source.search("file")
            assert len(items) == 1
            assert items[0].title == "file.txt"

    def test_home_dir_shortened(self):
        import os

        home = os.path.expanduser("~")
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=[f"{home}/Documents/test.txt"],
        ), patch("os.path.exists", return_value=True):
            source = FileSource()
            items = source.search("test")
            assert "~/Documents" in items[0].subtitle

    def test_as_chooser_source(self):
        source = FileSource()
        cs = source.as_chooser_source()
        assert cs.name == "files"
        assert cs.prefix == "f"
        assert cs.priority == 3
        assert cs.search is not None

    def test_preview_is_path_type(self):
        with patch(
            "wenzi.scripting.sources.file_source.mdquery_search",
            return_value=["/Users/test/file.txt"],
        ), patch("os.path.exists", return_value=True):
            source = FileSource()
            items = source.search("file")
            assert items[0].preview["type"] == "path"
            assert items[0].preview["content"] == "/Users/test/file.txt"
