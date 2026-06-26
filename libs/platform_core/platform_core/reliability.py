"""Reliability primitives: retry with exponential backoff + an async circuit breaker.

These wrap any flaky downstream (connector targets, embedding model, external APIs).
The circuit breaker prevents cascading failures by failing fast once an error threshold is
crossed, then probing for recovery; retries with jittered backoff absorb transient faults.

We ship a small, dependency-free async breaker rather than depending on a sync/Tornado-based
library, so it composes cleanly with our asyncio code and is trivially testable.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from functools import wraps
from typing import ParamSpec, TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .logging import get_logger
from .telemetry import CIRCUIT_BREAKER_STATE

log = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class TransientError(Exception):
    """Raise for errors that are safe to retry (timeouts, 429, 5xx, conn reset)."""


class CircuitBreakerError(Exception):
    """Raised when a call is rejected because the breaker is open."""


class BreakerState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


_STATE_VALUE = {BreakerState.CLOSED: 0, BreakerState.HALF_OPEN: 1, BreakerState.OPEN: 2}


class AsyncCircuitBreaker:
    """Three-state breaker: CLOSED -> (failures) -> OPEN -> (timeout) -> HALF_OPEN -> CLOSED.

    - CLOSED: calls pass through; consecutive failures are counted.
    - OPEN: calls fail fast for ``reset_timeout`` seconds.
    - HALF_OPEN: a single probe call is allowed; success closes, failure re-opens.
    """

    def __init__(self, name: str, *, fail_max: int = 5, reset_timeout: float = 30.0) -> None:
        self.name = name
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0
        self._publish()

    @property
    def state(self) -> BreakerState:
        return self._state

    def _publish(self) -> None:
        CIRCUIT_BREAKER_STATE.labels(name=self.name).set(_STATE_VALUE[self._state])

    def _transition(self, new: BreakerState) -> None:
        if new != self._state:
            log.warning(
                "circuit_breaker_state_change", breaker=self.name, old=self._state, new=new
            )
            self._state = new
            self._publish()

    def _on_success(self) -> None:
        self._failures = 0
        self._transition(BreakerState.CLOSED)

    def _on_failure(self) -> None:
        self._failures += 1
        if self._state == BreakerState.HALF_OPEN or self._failures >= self.fail_max:
            self._opened_at = time.monotonic()
            self._transition(BreakerState.OPEN)

    def _allow(self) -> bool:
        if self._state == BreakerState.OPEN:
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._transition(BreakerState.HALF_OPEN)
                return True
            return False
        return True

    async def call(self, func: Callable[..., Awaitable[T]], *args: object, **kwargs: object) -> T:
        if not self._allow():
            raise CircuitBreakerError(f"circuit '{self.name}' is open")
        try:
            result = await func(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = 0.0
        self._transition(BreakerState.CLOSED)


_breakers: dict[str, AsyncCircuitBreaker] = {}


def get_breaker(
    name: str, *, fail_max: int = 5, reset_timeout: float = 30.0
) -> AsyncCircuitBreaker:
    if name not in _breakers:
        _breakers[name] = AsyncCircuitBreaker(
            name, fail_max=fail_max, reset_timeout=reset_timeout
        )
    return _breakers[name]


def with_retry(
    *,
    attempts: int = 5,
    initial: float = 0.5,
    maximum: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (TransientError,),
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator: retry an async callable with exponential backoff + jitter."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential_jitter(initial=initial, max=maximum),
                retry=retry_if_exception_type(retry_on),
                reraise=True,
            ):
                with attempt:
                    return await func(*args, **kwargs)
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator


def with_breaker(
    name: str, *, fail_max: int = 5, reset_timeout: float = 30.0
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator: guard an async callable with a named circuit breaker."""

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        breaker = get_breaker(name, fail_max=fail_max, reset_timeout=reset_timeout)

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator
