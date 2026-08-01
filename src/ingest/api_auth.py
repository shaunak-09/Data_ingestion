"""API authentication.

`ApiAuth` is the vendor-neutral seam. Swapping a vendor's auth scheme means adding one class
here and changing `API_AUTH_TYPE` - no other module changes.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

import requests

from src.config import ApiSettings, ConfigError
from src.http import send
from src.logging_setup import log_event
from src.retry import Retryer

LOG = logging.getLogger(__name__)

_DEFAULT_TOKEN_LIFETIME_SECONDS = 3600.0


class AuthError(RuntimeError):
    """Credentials are missing, rejected, or the token response was unusable."""


class ApiAuth(Protocol):
    def headers(self) -> dict[str, str]:
        """Headers to attach to the next request."""
        ...

    def invalidate(self) -> None:
        """Drop any cached credential so the next call fetches a fresh one."""
        ...


class StaticTokenAuth:
    """For vendors that issue one long-lived token."""

    def __init__(self, token: str) -> None:
        self._token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def invalidate(self) -> None:
        # There is nothing to refresh, so a 401 here means the configured token is wrong.
        log_event(LOG, logging.WARNING, "api.auth.static_token_rejected")


class OAuth2ClientCredentialsAuth:
    """Fetches and caches a bearer token from the vendor's token endpoint.

    The token is treated as an opaque string - we never parse it. Expiry comes from the
    `expires_in` field in the token response, reduced by a safety skew.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        session: requests.Session,
        retryer: Retryer,
        timeout_seconds: float,
        expiry_skew_seconds: float = 30.0,
        scope: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._retryer = retryer
        self._timeout = timeout_seconds
        self._skew = max(0.0, expiry_skew_seconds)
        self._scope = scope
        self._monotonic = monotonic
        self._token: str | None = None
        self._expires_at = 0.0

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._current_token()}"}

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    def _current_token(self) -> str:
        if self._token is not None and self._monotonic() < self._expires_at:
            return self._token
        return self._fetch_token()

    def _fetch_token(self) -> str:
        response = self._retryer.call("api.auth.token", self._post_token)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthError("token endpoint did not return JSON") from exc
        token = payload.get("access_token")
        if not token:
            raise AuthError("token response contained no access_token")
        try:
            lifetime = float(payload.get("expires_in", _DEFAULT_TOKEN_LIFETIME_SECONDS))
        except (TypeError, ValueError):
            lifetime = _DEFAULT_TOKEN_LIFETIME_SECONDS
        self._token = str(token)
        self._expires_at = self._monotonic() + max(0.0, lifetime - self._skew)
        log_event(
            LOG,
            logging.INFO,
            "api.auth.token_issued",
            lifetime_seconds=lifetime,
            skew_seconds=self._skew,
        )
        return self._token

    def _post_token(self) -> requests.Response:
        return send(
            self._session,
            "POST",
            self._token_url,
            timeout=self._timeout,
            headers={"Accept": "application/json"},
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                **({"scope": self._scope} if self._scope else {}),
            },
        )


def build_auth(settings: ApiSettings, session: requests.Session, retryer: Retryer) -> ApiAuth:
    if settings.auth_type == "oauth2_client_credentials":
        if not (settings.token_url and settings.client_id and settings.client_secret):
            raise ConfigError(
                "oauth2_client_credentials needs API_TOKEN_URL, API_CLIENT_ID and API_CLIENT_SECRET"
            )
        return OAuth2ClientCredentialsAuth(
            token_url=settings.token_url,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            session=session,
            retryer=retryer,
            timeout_seconds=settings.timeout_seconds,
            expiry_skew_seconds=settings.token_expiry_skew_seconds,
        )
    if settings.auth_type == "static_token":
        if not settings.static_token:
            raise ConfigError("static_token auth needs API_STATIC_TOKEN")
        return StaticTokenAuth(settings.static_token)
    raise ConfigError(f"unsupported API_AUTH_TYPE: {settings.auth_type!r}")
