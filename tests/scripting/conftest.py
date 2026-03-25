"""Shared fixtures for scripting tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wenzi.scripting.api.chooser import ChooserAPI


@pytest.fixture
def chooser_panel():
    """Return a ChooserPanel with mocked JS evaluation."""
    api = ChooserAPI()
    panel = api.panel
    panel._eval_js = MagicMock()
    return panel
