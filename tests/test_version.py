"""Tests for version and build info consistency."""

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_pyproject_version() -> str:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


class TestVersion:
    def test_version_importable(self):
        from voicetext import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
        assert len(__version__) > 0

    def test_version_matches_pyproject(self):
        """__version__ should match pyproject.toml when package is installed."""
        from voicetext import __version__

        # In dev (editable install), these should match
        # If PackageNotFoundError was raised, __version__ is "0.0.0-dev"
        if __version__ != "0.0.0-dev":
            expected = _read_pyproject_version()
            assert __version__ == expected


class TestBuildInfo:
    def test_build_info_importable(self):
        from voicetext._build_info import BUILD_DATE, GIT_HASH

        assert isinstance(GIT_HASH, str)
        assert isinstance(BUILD_DATE, str)
        assert len(GIT_HASH) > 0
        assert len(BUILD_DATE) > 0

    def test_build_info_has_defaults(self):
        """Default values should be present for local development."""
        from voicetext._build_info import BUILD_DATE, GIT_HASH

        # In non-CI environment, defaults are "dev" and "unknown"
        assert GIT_HASH in ("dev", ) or len(GIT_HASH) >= 7  # short hash
        assert BUILD_DATE in ("unknown", ) or len(BUILD_DATE) == 10  # YYYY-MM-DD
