"""Tests for build type detection (wenzi.app.get_build_type)."""

from __future__ import annotations

import sys
from unittest.mock import patch

import wenzi.app as app_module


class TestGetBuildTypeEnvVar:
    """WENZI_VERSION environment variable detection."""

    def test_env_lite(self):
        with patch.dict("os.environ", {"WENZI_VERSION": "lite"}):
            assert app_module.get_build_type() == "lite"

    def test_env_standard(self):
        with patch.dict("os.environ", {"WENZI_VERSION": "standard"}):
            assert app_module.get_build_type() == "standard"

    def test_env_invalid_falls_through(self):
        with patch.dict("os.environ", {"WENZI_VERSION": "invalid"}), \
             patch("importlib.util.find_spec", return_value=None):
            assert app_module.get_build_type() == "lite"


class TestGetBuildTypePackageProbe:
    """Package probing fallback when no env var or frozen mode."""

    def test_funasr_available_means_standard(self):
        with patch.dict("os.environ", {}, clear=False), \
             patch("importlib.util.find_spec", return_value=object()):
            import os
            env = os.environ.copy()
            env.pop("WENZI_VERSION", None)
            with patch.dict("os.environ", env, clear=True):
                assert app_module.get_build_type() == "standard"

    def test_funasr_not_available_means_lite(self):
        with patch.dict("os.environ", {}, clear=False), \
             patch("importlib.util.find_spec", return_value=None):
            import os
            env = os.environ.copy()
            env.pop("WENZI_VERSION", None)
            with patch.dict("os.environ", env, clear=True):
                assert app_module.get_build_type() == "lite"


class TestGetBuildTypeFrozen:
    """PyInstaller frozen mode detection."""

    def test_frozen_lite(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/Applications/WenZi-Lite.app/Contents/MacOS/WenZi-Lite"):
            assert app_module.get_build_type() == "lite"

    def test_frozen_standard(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/Applications/WenZi.app/Contents/MacOS/WenZi"):
            assert app_module.get_build_type() == "standard"


class TestGetBuildTypeCache:
    """Caching behavior."""

    def test_result_is_cached(self):
        with patch.dict("os.environ", {"WENZI_VERSION": "lite"}):
            assert app_module.get_build_type() == "lite"

        # Now change env — should still return cached value
        with patch.dict("os.environ", {"WENZI_VERSION": "standard"}):
            assert app_module.get_build_type() == "lite"

    def test_cache_can_be_reset(self):
        with patch.dict("os.environ", {"WENZI_VERSION": "lite"}):
            assert app_module.get_build_type() == "lite"

        app_module._build_type_cache = None

        with patch.dict("os.environ", {"WENZI_VERSION": "standard"}):
            assert app_module.get_build_type() == "standard"


class TestGetBuildTypePriority:
    """Frozen mode takes priority over env var."""

    def test_frozen_overrides_env(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/Applications/WenZi-Lite.app/Contents/MacOS/WenZi-Lite"), \
             patch.dict("os.environ", {"WENZI_VERSION": "standard"}):
            assert app_module.get_build_type() == "lite"
