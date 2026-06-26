import pytest
from platform_core.reliability import (
    BreakerState,
    CircuitBreakerError,
    TransientError,
    get_breaker,
    with_breaker,
    with_retry,
)

pytestmark = pytest.mark.unit


async def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    @with_retry(attempts=4, initial=0.001, maximum=0.002)
    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("boom")
        return "ok"

    assert await flaky() == "ok"
    assert calls["n"] == 3


async def test_retry_gives_up_and_reraises():
    @with_retry(attempts=2, initial=0.001, maximum=0.002)
    async def always_fails():
        raise TransientError("nope")

    with pytest.raises(TransientError):
        await always_fails()


async def test_circuit_breaker_opens_after_threshold():
    breaker = get_breaker("test_breaker_unit", fail_max=2, reset_timeout=60)
    breaker.reset()

    @with_breaker("test_breaker_unit", fail_max=2, reset_timeout=60)
    async def boom():
        raise ValueError("fail")

    for _ in range(2):
        with pytest.raises(ValueError):
            await boom()

    assert breaker.state is BreakerState.OPEN
    # Breaker should now short-circuit subsequent calls (fail fast).
    with pytest.raises(CircuitBreakerError):
        await boom()


async def test_circuit_breaker_half_opens_and_recovers():
    breaker = get_breaker("test_breaker_recover", fail_max=1, reset_timeout=0.05)
    breaker.reset()

    calls = {"n": 0}

    @with_breaker("test_breaker_recover", fail_max=1, reset_timeout=0.05)
    async def sometimes():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("first fails")
        return "ok"

    with pytest.raises(ValueError):
        await sometimes()
    assert breaker.state is BreakerState.OPEN

    import asyncio

    await asyncio.sleep(0.06)  # let reset_timeout elapse -> half-open probe allowed
    assert await sometimes() == "ok"
    assert breaker.state is BreakerState.CLOSED
