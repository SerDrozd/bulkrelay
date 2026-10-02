from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from bulkrelay.config.models import RetryConfig
from bulkrelay.execution.retry import RetryPolicy, parse_retry_after


def test_parse_retry_after_delta_seconds() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    assert parse_retry_after("14", now=now) == 14.0


def test_parse_retry_after_http_date() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    value = format_datetime(now + timedelta(seconds=45), usegmt=True)

    assert parse_retry_after(value, now=now) == 45.0


def test_parse_retry_after_invalid_value_is_ignored() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)

    assert parse_retry_after("not-a-date", now=now) is None


def test_retry_after_never_shortens_exponential_backoff() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    policy = RetryPolicy(
        RetryConfig(
            max_attempts=4,
            initial_backoff_seconds=4,
            max_backoff_seconds=30,
            jitter_ratio=0,
        ),
        wall_clock=lambda: now,
    )
    request = httpx.Request("POST", "https://example.test/users")
    response = httpx.Response(429, headers={"Retry-After": "1"}, request=request)

    assert policy.delay_for_response(response, failed_attempt=1) == 4.0


def test_retry_after_can_extend_backoff() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    policy = RetryPolicy(
        RetryConfig(
            max_attempts=4,
            initial_backoff_seconds=1,
            max_backoff_seconds=30,
            jitter_ratio=0,
        ),
        wall_clock=lambda: now,
    )
    request = httpx.Request("POST", "https://example.test/users")
    response = httpx.Response(503, headers={"Retry-After": "8"}, request=request)

    assert policy.delay_for_response(response, failed_attempt=1) == 8.0


def test_backoff_is_exponential_and_capped() -> None:
    policy = RetryPolicy(
        RetryConfig(
            max_attempts=6,
            initial_backoff_seconds=2,
            max_backoff_seconds=5,
            jitter_ratio=0,
        )
    )

    assert policy.delay_for_exception(1) == 2.0
    assert policy.delay_for_exception(2) == 4.0
    assert policy.delay_for_exception(3) == 5.0
    assert policy.delay_for_exception(4) == 5.0


def test_jitter_stays_within_configured_band() -> None:
    config = RetryConfig(
        initial_backoff_seconds=10,
        max_backoff_seconds=30,
        jitter_ratio=0.2,
    )

    low = RetryPolicy(config, random_value=lambda: 0.0).delay_for_exception(1)
    high = RetryPolicy(config, random_value=lambda: 1.0).delay_for_exception(1)

    assert low == pytest.approx(8.0)
    assert high == pytest.approx(12.0)
