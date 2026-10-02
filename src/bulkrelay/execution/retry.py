from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from bulkrelay.config.models import RetryConfig

RandomValue = Callable[[], float]
WallClock = Callable[[], datetime]


class RetryPolicy:
    def __init__(
        self,
        config: RetryConfig,
        *,
        random_value: RandomValue = random.random,
        wall_clock: WallClock | None = None,
    ) -> None:
        self.config = config
        self._random_value = random_value
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))

    def can_retry(self, attempt: int) -> bool:
        return attempt < self.config.max_attempts

    def response_is_retryable(self, response: httpx.Response) -> bool:
        return response.status_code in self.config.statuses

    def exception_is_retryable(self, exc: httpx.HTTPError) -> bool:
        return isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.ProxyError,
            ),
        )

    def delay_for_response(self, response: httpx.Response, failed_attempt: int) -> float:
        backoff = self._backoff_delay(failed_attempt)
        if not self.config.respect_retry_after:
            return backoff

        retry_after = parse_retry_after(response.headers.get("Retry-After"), now=self._wall_clock())
        if retry_after is None:
            return backoff
        return max(backoff, retry_after)

    def delay_for_exception(self, failed_attempt: int) -> float:
        return self._backoff_delay(failed_attempt)

    def _backoff_delay(self, failed_attempt: int) -> float:
        base = min(
            self.config.initial_backoff_seconds * (2 ** (failed_attempt - 1)),
            self.config.max_backoff_seconds,
        )
        if base == 0 or self.config.jitter_ratio == 0:
            return base

        spread = self.config.jitter_ratio
        multiplier = (1 - spread) + (2 * spread * self._random_value())
        return max(0.0, base * multiplier)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Parse Retry-After delta-seconds or an HTTP-date into a non-negative delay."""

    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    try:
        seconds = int(stripped)
    except ValueError:
        seconds = -1
    else:
        return float(max(0, seconds))

    try:
        retry_at = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return max(0.0, (retry_at - current).total_seconds())
