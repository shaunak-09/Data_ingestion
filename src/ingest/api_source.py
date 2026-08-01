"""REST API adapter. Yields one page of student records at a time.

Assumed vendor contract (documented in the README):
- `GET {base_url}{students_path}?updated_since=<iso8601>&page=<n>&page_size=<n>`
- body is JSON with the records under `data` (or `students` / `items` / `results`)
- next page is either an absolute/relative URL in `next`, or a page number in `next_page`
- absent/null `next` and `next_page` means the last page
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import requests

from src.config import ApiSettings
from src.http import UnauthorizedError, send
from src.ingest.api_auth import ApiAuth
from src.logging_setup import log_event
from src.retry import Retryer

LOG = logging.getLogger(__name__)

_RECORD_KEYS = ("data", "students", "items", "results")


class ApiSourceError(RuntimeError):
    """The API answered in a shape we cannot page through safely."""


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in _RECORD_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return [record for record in value if isinstance(record, dict)]
    raise ApiSourceError("could not find a record list in the API response")


class StudentApiClient:
    """Paginated, authenticated, retrying reader for the vendor student API."""

    def __init__(
        self,
        settings: ApiSettings,
        auth: ApiAuth,
        retryer: Retryer,
        session: requests.Session | None = None,
    ) -> None:
        if not settings.base_url:
            raise ApiSourceError("API_BASE_URL is not set")
        self._settings = settings
        self._auth = auth
        self._retryer = retryer
        self._session = session or requests.Session()

    def fetch_chunks(self, since: datetime | None = None) -> Iterator[list[dict[str, Any]]]:
        """Yield each page of records. Memory holds one page, never the whole result set."""
        url = f"{self._settings.base_url}{self._settings.students_path}"
        params: dict[str, Any] | None = {"page_size": self._settings.page_size, "page": 1}
        if since is not None:
            params["updated_since"] = since.astimezone(UTC).isoformat()

        seen_pages: set[str] = set()
        page_count = 0
        while True:
            page_key = f"{url}|{params}"
            if page_key in seen_pages:
                raise ApiSourceError(f"API pagination repeated a page: {url}")
            seen_pages.add(page_key)

            payload = self._get_page(url, params)
            records = _extract_records(payload)
            page_count += 1
            log_event(
                LOG,
                logging.INFO,
                "api.page_fetched",
                page=page_count,
                records=len(records),
                total_pages=payload.get("total_pages") if isinstance(payload, dict) else None,
            )
            if records:
                yield records

            url, params = self._next_target(url, params, payload)
            if url is None:
                log_event(LOG, logging.INFO, "api.pagination_complete", pages=page_count)
                return

    def _next_target(
        self, url: str, params: dict[str, Any] | None, payload: Any
    ) -> tuple[str | None, dict[str, Any] | None]:
        if not isinstance(payload, dict):
            return None, None

        next_url = payload.get("next") or payload.get("next_url")
        if isinstance(next_url, str) and next_url:
            # The vendor's link already carries the query string.
            return urljoin(url, next_url), None

        next_page = payload.get("next_page")
        if next_page is None:
            return None, None
        try:
            next_page_number = int(next_page)
        except (TypeError, ValueError) as exc:
            raise ApiSourceError(f"next_page is not a number: {next_page!r}") from exc
        current_page = int((params or {}).get("page", 0) or 0)
        if next_page_number <= current_page:
            raise ApiSourceError(
                f"next_page {next_page_number} does not advance past page {current_page}"
            )
        return url, {**(params or {}), "page": next_page_number}

    def _get_page(self, url: str, params: dict[str, Any] | None) -> Any:
        """Retryable statuses are handled by the retryer; a 401 buys exactly one token refresh."""
        for attempt in (1, 2):
            try:
                response = self._retryer.call(
                    "api.fetch_page",
                    send,
                    self._session,
                    "GET",
                    url,
                    timeout=self._settings.timeout_seconds,
                    headers={"Accept": "application/json", **self._auth.headers()},
                    params=params,
                )
                break
            except UnauthorizedError:
                if attempt == 2:
                    raise
                log_event(LOG, logging.WARNING, "api.unauthorized_refreshing_token", url=url)
                self._auth.invalidate()
        try:
            return response.json()
        except ValueError as exc:
            raise ApiSourceError(f"{url} did not return JSON") from exc
