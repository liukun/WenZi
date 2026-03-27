"""Shared fixtures for wenzi.enhance tests."""

import pytest


@pytest.fixture
def rate_limit_error():
    """Create a mock 429 RateLimitError for testing."""
    from httpx import Request, Response
    from openai import RateLimitError

    response = Response(
        status_code=429,
        request=Request("POST", "https://example.com/v1/chat/completions"),
        json={"error": {"message": "rate limited", "code": "429"}},
    )
    return RateLimitError(
        message="rate limited",
        response=response,
        body={"error": {"message": "rate limited"}},
    )
