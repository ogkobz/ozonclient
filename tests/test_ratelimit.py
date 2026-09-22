"""Лимиты. Часы и sleep подменены, тесты не ждут реального времени.

Ozon не сообщает состояние лимита в заголовках, поэтому окно считается
на нашей стороне: не больше 50 запросов в секунду на один Client-Id.
"""

from __future__ import annotations

import pytest

from ozonclient.ratelimit import RateLimiter


def limiter(clock, limit=3, period=1.0) -> RateLimiter:
    return RateLimiter(limit, period, clock=clock, sleep=clock.sleep)


def test_default_limit_is_fifty_per_second():
    rl = RateLimiter()
    assert rl.limit == 50
    assert rl.period == 1.0


def test_requests_under_limit_do_not_wait(clock):
    rl = limiter(clock)
    assert rl.acquire() == 0.0
    assert rl.acquire() == 0.0
    assert rl.acquire() == 0.0
    assert clock.slept == []


def test_request_over_limit_waits_for_window(clock):
    rl = limiter(clock)
    for _ in range(3):
        rl.acquire()
    waited = rl.acquire()
    assert waited == pytest.approx(1.0)


def test_window_slides(clock):
    """Прошла секунда — старые отметки больше не мешают."""
    rl = limiter(clock)
    for _ in range(3):
        rl.acquire()
    clock.now += 1.1
    assert rl.acquire() == 0.0


def test_partial_slide_waits_only_the_remainder(clock):
    rl = limiter(clock)
    rl.acquire()
    clock.now += 0.6
    rl.acquire()
    rl.acquire()
    assert rl.acquire() == pytest.approx(0.4)


def test_in_window_counts_current_requests(clock):
    rl = limiter(clock)
    rl.acquire()
    rl.acquire()
    assert rl.in_window == 2
    clock.now += 1.1
    assert rl.in_window == 0


# --- отдельные лимиты методов --------------------------------------------


def test_method_limit_is_stricter_than_common(clock):
    """У отдельных методов свои ограничения, более узкие чем общее."""
    rl = limiter(clock, limit=10)
    rl.set_method_limit("product_import", 2)
    rl.acquire("product_import")
    rl.acquire("product_import")
    assert rl.acquire("product_import") == pytest.approx(1.0)


def test_method_limit_does_not_affect_other_methods(clock):
    rl = limiter(clock, limit=10)
    rl.set_method_limit("product_import", 1)
    rl.acquire("product_import")
    assert rl.acquire("product_list") == 0.0


def test_common_limit_still_applies_to_named_method(clock):
    rl = limiter(clock, limit=2)
    rl.set_method_limit("product_list", 100)
    rl.acquire("product_list")
    rl.acquire("product_list")
    assert rl.acquire("product_list") == pytest.approx(1.0)


# --- штраф ----------------------------------------------------------------


def test_penalize_pushes_next_request(clock):
    rl = limiter(clock)
    rl.penalize(5.0)
    assert rl.acquire() == pytest.approx(5.0)


def test_limiter_rejects_zero_limit():
    with pytest.raises(ValueError):
        RateLimiter(0)
