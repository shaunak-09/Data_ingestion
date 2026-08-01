"""API adapter over real HTTP against the mock vendor API.

Covers pagination (both vendor styles), token caching, refresh on expiry, one-time refresh
after a 401, rate limiting with `Retry-After`, and giving up on a permanent failure.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
import requests

from src.config import ApiSettings
from src.http import UnauthorizedError
from src.ingest.api_auth import OAuth2ClientCredentialsAuth, build_auth
from src.ingest.api_source import StudentApiClient
from src.retry import RetryableError, Retryer, RetryPolicy
from tests.mock_api import DEFAULT_CLIENT_ID, DEFAULT_CLIENT_SECRET, MockApiState, mock_api


def students(count: int) -> list[dict]:
    return [
        {
            "student_id": f"S{index:03d}",
            "first_name": "Ava",
            "last_name": "Nguyen",
            "grade_level": 9,
            "school_id": "SCH-01",
            "email": f"student{index}@example.edu",
            "enrollment_status": "active",
            "updated_at": f"2026-07-{index + 1:02d}T00:00:00Z",
        }
        for index in range(count)
    ]


def settings_for(base_url: str, *, page_size: int = 2, secret: str = DEFAULT_CLIENT_SECRET):
    return ApiSettings(
        base_url=base_url,
        students_path="/students",
        auth_type="oauth2_client_credentials",
        token_url=f"{base_url}/oauth2/token",
        client_id=DEFAULT_CLIENT_ID,
        client_secret=secret,
        static_token=None,
        token_expiry_skew_seconds=0,
        page_size=page_size,
        timeout_seconds=5.0,
    )


def build_client(
    base_url: str,
    sleeps: list[float],
    *,
    page_size: int = 2,
    secret: str = DEFAULT_CLIENT_SECRET,
) -> StudentApiClient:
    settings = settings_for(base_url, page_size=page_size, secret=secret)
    retryer = Retryer(
        RetryPolicy(max_attempts=3, base_delay_seconds=0.01, max_delay_seconds=0.02),
        sleep=sleeps.append,
        rng=random.Random(0),
    )
    session = requests.Session()
    return StudentApiClient(settings, build_auth(settings, session, retryer), retryer, session)


def test_pages_are_yielded_one_at_a_time():
    with mock_api(MockApiState(students=students(5))) as (base_url, state):
        chunks = list(build_client(base_url, []).fetch_chunks())

    assert [len(chunk) for chunk in chunks] == [2, 2, 1]
    assert [record["student_id"] for chunk in chunks for record in chunk] == [
        "S000",
        "S001",
        "S002",
        "S003",
        "S004",
    ]
    assert state.page_requests == [1, 2, 3]


def test_vendor_next_url_style_also_pages():
    with mock_api(MockApiState(students=students(5), use_next_url=True)) as (base_url, state):
        chunks = list(build_client(base_url, []).fetch_chunks())

    assert sum(len(chunk) for chunk in chunks) == 5
    assert state.page_requests == [1, 2, 3]


def test_one_token_is_reused_across_pages():
    with mock_api(MockApiState(students=students(5))) as (base_url, state):
        list(build_client(base_url, []).fetch_chunks())

    assert len(state.issued_tokens) == 1


def test_a_401_mid_run_refreshes_the_token_once_and_continues():
    with mock_api(MockApiState(students=students(5))) as (base_url, state):
        pages = build_client(base_url, []).fetch_chunks()
        first = next(pages)
        state.reject_current_token()
        rest = list(pages)

    assert len(state.issued_tokens) == 2
    assert sum(len(chunk) for chunk in [first, *rest]) == 5


def test_rate_limit_waits_for_retry_after_then_succeeds():
    sleeps: list[float] = []
    state = MockApiState(students=students(5), rate_limit_pages_once={2}, retry_after_seconds=2)

    with mock_api(state) as (base_url, _):
        chunks = list(build_client(base_url, sleeps).fetch_chunks())

    assert sleeps == [2.0]
    assert sum(len(chunk) for chunk in chunks) == 5


def test_a_permanently_failing_page_gives_up_after_the_configured_attempts():
    sleeps: list[float] = []
    state = MockApiState(students=students(5), server_error_pages={2})

    with mock_api(state) as (base_url, _), pytest.raises(RetryableError):
        list(build_client(base_url, sleeps).fetch_chunks())

    assert state.page_requests.count(2) == 3
    assert len(sleeps) == 2


def test_bad_credentials_are_not_retried_forever():
    with (
        mock_api(MockApiState(students=students(2))) as (base_url, state),
        pytest.raises(UnauthorizedError),
    ):
        list(build_client(base_url, [], secret="wrong-secret").fetch_chunks())

    assert state.issued_tokens == []


def test_watermark_is_sent_and_narrows_the_result():
    since = datetime(2026, 7, 3, tzinfo=UTC)

    with mock_api(MockApiState(students=students(5))) as (base_url, state):
        chunks = list(build_client(base_url, []).fetch_chunks(since=since))

    returned = [record["student_id"] for chunk in chunks for record in chunk]
    assert returned == ["S003", "S004"]
    assert state.updated_since_seen[0] == "2026-07-03T00:00:00+00:00"


def test_expired_token_is_refreshed_before_the_next_call():
    clock = {"now": 1000.0}
    session = requests.Session()
    retryer = Retryer(RetryPolicy(max_attempts=2, base_delay_seconds=0.01), sleep=lambda _: None)

    with mock_api(MockApiState(students=students(1), token_lifetime_seconds=60)) as (base_url, s):
        auth = OAuth2ClientCredentialsAuth(
            token_url=f"{base_url}/oauth2/token",
            client_id=DEFAULT_CLIENT_ID,
            client_secret=DEFAULT_CLIENT_SECRET,
            session=session,
            retryer=retryer,
            timeout_seconds=5.0,
            expiry_skew_seconds=10,
            monotonic=lambda: clock["now"],
        )
        first = auth.headers()["Authorization"]
        clock["now"] += 30  # still inside the 60s lifetime
        cached = auth.headers()["Authorization"]
        clock["now"] += 30  # past lifetime minus skew
        refreshed = auth.headers()["Authorization"]

    assert first == cached
    assert refreshed != first
    assert len(s.issued_tokens) == 2
