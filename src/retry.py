"""Retry with exponential backoff and jitter. Used by the API client and the database writer."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from src.config import RetrySettings
from src.logging_setup import log_event

LOG = logging.getLogger(__name__)

T = TypeVar("T")


class RetryableError(Exception):
    """Raised by callers for a failure worth retrying (429, 5xx, connection reset)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0

    @classmethod
    def from_settings(cls, settings: RetrySettings) -> RetryPolicy:
        return cls(
            max_attempts=settings.max_attempts,
            base_delay_seconds=settings.base_delay_seconds,
            max_delay_seconds=settings.max_delay_seconds,
        )


class Retryer:
    """Retries an operation. `sleep` and `rng` are injectable so tests stay fast and exact."""

    def __init__(
        self,
        policy: RetryPolicy,
        *,
        retry_on: tuple[type[BaseException], ...] = (RetryableError,),
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        if policy.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._policy = policy
        self._retry_on = retry_on
        self._sleep = sleep
        self._rng = rng or random.Random()

    def delay_for(self, attempt: int, retry_after: float | None = None) -> float:
        """Equal jitter: half the backoff is fixed, half is random. `Retry-After` wins outright."""
        if retry_after is not None:
            return max(0.0, retry_after)
        exponential = self._policy.base_delay_seconds * (2 ** (attempt - 1))
        capped = min(exponential, self._policy.max_delay_seconds)
        return capped / 2 + self._rng.uniform(0, capped / 2)

    def call(self, operation: str, fn: Callable[..., T], *args: object, **kwargs: object) -> T:
        """Run `fn`, retrying listed exceptions. Re-raises the last error once attempts run out."""
        last_error: BaseException | None = None
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                return fn(*args, **kwargs)
            except self._retry_on as exc:
                last_error = exc
                if attempt == self._policy.max_attempts:
                    break
                retry_after = getattr(exc, "retry_after", None)
                delay = self.delay_for(attempt, retry_after)
                log_event(
                    LOG,
                    logging.WARNING,
                    "retry.attempt_failed",
                    operation=operation,
                    attempt=attempt,
                    max_attempts=self._policy.max_attempts,
                    delay_seconds=round(delay, 3),
                    honoured_retry_after=retry_after is not None,
                    error=str(exc),
                )
                self._sleep(delay)
        log_event(
            LOG,
            logging.ERROR,
            "retry.exhausted",
            operation=operation,
            attempts=self._policy.max_attempts,
            error=str(last_error),
        )
        assert last_error is not None
        raise last_error
