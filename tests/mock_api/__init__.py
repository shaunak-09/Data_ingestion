"""Mock vendor student API used by tests and by local end-to-end runs."""

from tests.mock_api.server import (
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIENT_SECRET,
    MockApiState,
    mock_api,
)

__all__ = ["DEFAULT_CLIENT_ID", "DEFAULT_CLIENT_SECRET", "MockApiState", "mock_api"]
