"""Root test configuration — ensures safe defaults for all test sessions."""

import os

import pytest

# Enable debug mode so the secret-key production guard doesn't fire during tests.
os.environ.setdefault("MODELIONN_DEBUG", "1")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the in-memory rate-limiter and nonce replay state between tests
    so accumulated counts from earlier test files don't cause 429s / 401s."""
    from registry.api.middleware import rate_limit
    from registry.core import security

    rate_limit._request_counts.clear()
    rate_limit._redis_init_attempted = False
    rate_limit._redis_client = None
    security._used_nonces.clear()
    yield
    rate_limit._request_counts.clear()
    security._used_nonces.clear()
