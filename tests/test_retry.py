"""Backoff, jitter and `Retry-After` handling."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from src.http import parse_retry_after
from src.retry import RetryableError, Retryer, RetryPolicy


def build_retryer(policy: RetryPolicy, sleeps: list[float]) -> Retryer:
    return Retryer(policy, sleep=sleeps.append, rng=random.Random(0))


def test_succeeds_after_transient_failures():
    sleeps: list[float] = []
    retryer = build_retryer(RetryPolicy(max_attempts=3, base_delay_seconds=1), sleeps)
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("boom")
        return "ok"

    assert retryer.call("test", flaky) == "ok"
    assert attempts["count"] == 3
    assert len(sleeps) == 2


def test_raises_the_original_error_once_attempts_run_out():
    sleeps: list[float] = []
    retryer = build_retryer(RetryPolicy(max_attempts=2, base_delay_seconds=1), sleeps)

    def always_fails() -> None:
        raise RetryableError("still down")

    with pytest.raises(RetryableError, match="still down"):
        retryer.call("test", always_fails)
    assert len(sleeps) == 1


def test_unexpected_errors_are_not_retried():
    sleeps: list[float] = []
    retryer = build_retryer(RetryPolicy(max_attempts=5), sleeps)

    def broken() -> None:
        raise ValueError("bug, not a blip")

    with pytest.raises(ValueError):
        retryer.call("test", broken)
    assert sleeps == []


def test_retry_after_is_honoured_exactly():
    sleeps: list[float] = []
    retryer = build_retryer(RetryPolicy(max_attempts=2, base_delay_seconds=30), sleeps)

    def rate_limited() -> None:
        raise RetryableError("429", retry_after=2.5)

    with pytest.raises(RetryableError):
        retryer.call("test", rate_limited)
    assert sleeps == [2.5]


def test_backoff_grows_and_stays_inside_the_cap():
    retryer = build_retryer(RetryPolicy(base_delay_seconds=1, max_delay_seconds=10), [])

    delays = [retryer.delay_for(attempt) for attempt in range(1, 7)]

    for attempt, delay in enumerate(delays, start=1):
        cap = min(1 * 2 ** (attempt - 1), 10)
        assert cap / 2 <= delay <= cap
    assert max(delays) <= 10


def test_jitter_spreads_retries_apart():
    retryer = build_retryer(RetryPolicy(base_delay_seconds=8, max_delay_seconds=60), [])

    assert len({retryer.delay_for(3) for _ in range(20)}) > 1


@pytest.mark.parametrize(("header", "expected"), [("120", 120.0), ("0", 0.0), (None, None)])
def test_parse_retry_after_seconds(header, expected):
    assert parse_retry_after(header) == expected


def test_parse_retry_after_http_date():
    later = datetime.now(UTC) + timedelta(seconds=60)

    seconds = parse_retry_after(format_datetime(later))

    assert seconds is not None
    assert 55 <= seconds <= 61


def test_parse_retry_after_ignores_nonsense():
    assert parse_retry_after("soon") is None
