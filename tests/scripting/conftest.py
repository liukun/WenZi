"""Shared fixtures for scripting tests."""

from __future__ import annotations

import pytest

from wenzi.scripting.api.chooser import ChooserAPI


@pytest.fixture
def chooser_panel():
    """Return a ChooserPanel without AppKit views for testing."""
    api = ChooserAPI()
    return api.panel
