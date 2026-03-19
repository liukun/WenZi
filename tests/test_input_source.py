"""Tests for wenzi.input_source module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wenzi import input_source


@pytest.fixture(autouse=True)
def _reset_tis_state():
    """Reset module-level TIS loading state between tests."""
    input_source._tis_loaded = None
    input_source._TISCopyCurrentKeyboardInputSource = None
    input_source._TISCreateInputSourceList = None
    input_source._TISSelectInputSource = None
    input_source._TISGetInputSourceProperty = None
    input_source._kTISPropertyInputSourceID = None
    input_source._cached_english_sid = None
    yield
    input_source._tis_loaded = None
    input_source._TISCopyCurrentKeyboardInputSource = None
    input_source._TISCreateInputSourceList = None
    input_source._TISSelectInputSource = None
    input_source._TISGetInputSourceProperty = None
    input_source._kTISPropertyInputSourceID = None
    input_source._cached_english_sid = None


@pytest.fixture()
def _patch_foundation():
    """Patch sys.modules with a mock Foundation.NSDictionary."""
    mock_ns_dict = MagicMock()
    mock_ns_dict.dictionaryWithObject_forKey_ = MagicMock(
        return_value={"key": "val"}
    )
    mock_foundation = MagicMock()
    mock_foundation.NSDictionary = mock_ns_dict
    with patch.dict("sys.modules", {"Foundation": mock_foundation}):
        yield


class TestLoadTis:
    def test_load_failure_returns_false(self):
        """When HIToolbox bundle is unavailable, _load_tis returns False."""
        mock_objc = MagicMock()
        mock_foundation = MagicMock()
        # Simulate bundle not found
        mock_foundation.NSBundle.bundleWithPath_.return_value = None

        with patch.dict("sys.modules", {
            "objc": mock_objc,
            "Foundation": mock_foundation,
        }):
            result = input_source._load_tis()

        assert result is False
        assert input_source._tis_loaded is False

    def test_load_failure_on_import_error(self):
        """When objc is not available, _load_tis returns False."""
        input_source._tis_loaded = None
        with patch.dict("sys.modules", {"objc": None}):
            result = input_source._load_tis()
        assert result is False

    def test_cached_result(self):
        """Second call returns cached result without reloading."""
        input_source._tis_loaded = True
        assert input_source._load_tis() is True

        input_source._tis_loaded = False
        assert input_source._load_tis() is False


class TestGetCurrentInputSource:
    def test_returns_none_when_tis_unavailable(self):
        input_source._tis_loaded = False
        assert input_source.get_current_input_source() is None

    def test_returns_source_id(self):
        input_source._tis_loaded = True
        mock_source = MagicMock()
        input_source._TISCopyCurrentKeyboardInputSource = MagicMock(
            return_value=mock_source
        )
        input_source._TISGetInputSourceProperty = MagicMock(
            return_value="com.apple.keylayout.ABC"
        )
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"

        result = input_source.get_current_input_source()
        assert result == "com.apple.keylayout.ABC"

    def test_returns_none_when_source_is_none(self):
        input_source._tis_loaded = True
        input_source._TISCopyCurrentKeyboardInputSource = MagicMock(
            return_value=None
        )
        assert input_source.get_current_input_source() is None

    def test_returns_none_on_exception(self):
        input_source._tis_loaded = True
        input_source._TISCopyCurrentKeyboardInputSource = MagicMock(
            side_effect=RuntimeError("boom")
        )
        assert input_source.get_current_input_source() is None


class TestSelectInputSource:
    def test_returns_false_when_tis_unavailable(self):
        input_source._tis_loaded = False
        assert input_source.select_input_source("com.apple.keylayout.ABC") is False

    @pytest.mark.usefixtures("_patch_foundation")
    def test_success(self):
        input_source._tis_loaded = True
        mock_source = MagicMock()
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"
        input_source._TISCreateInputSourceList = MagicMock(
            return_value=[mock_source]
        )
        input_source._TISSelectInputSource = MagicMock(return_value=0)

        result = input_source.select_input_source("com.apple.keylayout.ABC")

        assert result is True
        input_source._TISSelectInputSource.assert_called_once_with(mock_source)

    @pytest.mark.usefixtures("_patch_foundation")
    def test_returns_false_when_source_not_found(self):
        input_source._tis_loaded = True
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"
        input_source._TISCreateInputSourceList = MagicMock(return_value=[])

        result = input_source.select_input_source("com.apple.keylayout.Foo")

        assert result is False

    @pytest.mark.usefixtures("_patch_foundation")
    def test_returns_false_on_select_error(self):
        input_source._tis_loaded = True
        mock_source = MagicMock()
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"
        input_source._TISCreateInputSourceList = MagicMock(
            return_value=[mock_source]
        )
        input_source._TISSelectInputSource = MagicMock(return_value=-1)

        result = input_source.select_input_source("com.apple.keylayout.ABC")

        assert result is False

    @pytest.mark.usefixtures("_patch_foundation")
    def test_returns_false_on_exception(self):
        input_source._tis_loaded = True
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"
        input_source._TISCreateInputSourceList = MagicMock(
            side_effect=RuntimeError("boom")
        )

        result = input_source.select_input_source("com.apple.keylayout.ABC")

        assert result is False


class TestIsEnglishInputSource:
    @pytest.mark.parametrize("source_id,expected", [
        ("com.apple.keylayout.ABC", True),
        ("com.apple.keylayout.US", True),
        ("com.apple.keylayout.USInternational-PC", True),
        ("com.apple.inputmethod.SCIM.ITABC", False),
        ("com.apple.inputmethod.SCIM.WBX", False),
        ("com.sogou.inputmethod.sogou", False),
    ])
    def test_detection(self, source_id, expected):
        assert input_source.is_english_input_source(source_id) is expected

    def test_none_with_tis_unavailable(self):
        """When source_id is None and TIS unavailable, returns False."""
        input_source._tis_loaded = False
        assert input_source.is_english_input_source(None) is False

    def test_uses_current_when_none(self):
        input_source._tis_loaded = True
        mock_source = MagicMock()
        input_source._TISCopyCurrentKeyboardInputSource = MagicMock(
            return_value=mock_source
        )
        input_source._TISGetInputSourceProperty = MagicMock(
            return_value="com.apple.keylayout.ABC"
        )
        input_source._kTISPropertyInputSourceID = "kTISPropertyInputSourceID"

        assert input_source.is_english_input_source() is True


class TestSelectEnglishInputSource:
    def test_returns_false_when_tis_unavailable(self):
        input_source._tis_loaded = False
        assert input_source.select_english_input_source() is False

    def test_tries_sources_in_order(self):
        """Tries ABC first, falls back to US, then USInternational-PC."""
        call_log = []

        def mock_select(sid):
            call_log.append(sid)
            # Only succeed on US
            return sid == "com.apple.keylayout.US"

        with patch("wenzi.input_source.select_input_source", side_effect=mock_select):
            result = input_source.select_english_input_source()

        assert result is True
        assert call_log == [
            "com.apple.keylayout.ABC",
            "com.apple.keylayout.US",
        ]

    def test_returns_false_when_none_found(self):
        with patch(
            "wenzi.input_source.select_input_source", return_value=False
        ):
            result = input_source.select_english_input_source()

        assert result is False

    def test_cached_sid_used_on_second_call(self):
        """After first success, cached source ID is tried first."""
        call_log = []

        def mock_select(sid):
            call_log.append(sid)
            return sid == "com.apple.keylayout.US"

        with patch("wenzi.input_source.select_input_source", side_effect=mock_select):
            input_source.select_english_input_source()  # first: tries ABC, then US
            call_log.clear()
            input_source.select_english_input_source()  # second: cached US directly

        assert call_log == ["com.apple.keylayout.US"]

    def test_cached_sid_invalidated_on_failure(self):
        """If cached source fails, falls back to full scan."""
        input_source._cached_english_sid = "com.apple.keylayout.Gone"
        call_log = []

        def mock_select(sid):
            call_log.append(sid)
            return sid == "com.apple.keylayout.ABC"

        with patch("wenzi.input_source.select_input_source", side_effect=mock_select):
            result = input_source.select_english_input_source()

        assert result is True
        assert call_log == [
            "com.apple.keylayout.Gone",  # cached, fails
            "com.apple.keylayout.ABC",   # fallback, succeeds
        ]
