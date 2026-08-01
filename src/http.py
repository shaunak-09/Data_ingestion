"""HTTP send helper shared by the API client and the API auth provider.

It exists so the "which status codes are retryable" rule is written once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from src.retry import RetryableError

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_BODY_SNIPPET_CHARS = 200


class HttpError(RuntimeError):
    """A non-retryable HTTP failure."""

    def __init__(self, message: str, *, status_code: int, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class UnauthorizedError(HttpError):
    """401. The caller should refresh credentials once and retry."""


def parse_retry_after(value: str | None) -> float | None:
    """Accepts both `Retry-After: 120` and the HTTP-date form. Returns seconds."""
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def send(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> requests.Response:
    """One HTTP call. Turns transport errors and retryable statuses into `RetryableError`."""
    try:
        response = session.request(
            method, url, headers=headers, params=params, data=data, timeout=timeout
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise RetryableError(f"{method} {url} transport failure: {exc}") from exc

    if response.status_code in RETRYABLE_STATUS:
        raise RetryableError(
            f"{method} {url} returned {response.status_code}",
            retry_after=parse_retry_after(response.headers.get("Retry-After")),
        )
    if response.status_code == 401:
        raise UnauthorizedError(f"{method} {url} returned 401", status_code=401)
    if response.status_code >= 400:
        raise HttpError(
            f"{method} {url} returned {response.status_code}",
            status_code=response.status_code,
            body=response.text[:_BODY_SNIPPET_CHARS],
        )
    return response
