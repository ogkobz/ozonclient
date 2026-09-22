"""Клиент целиком: защита от записи, маршрутизация, лимиты, повторы. Сети нет."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeTransport, err, fail, ok
from ozonclient.client import OzonClient
from ozonclient.errors import (
    OzonAuthError,
    OzonError,
    OzonKeyExpiredError,
    OzonNotFoundError,
    OzonTemporaryError,
    OzonValidationError,
    OzonWriteBlockedError,
)
from ozonclient.methods import UnknownMethodError
from ozonclient.ratelimit import RateLimiter


def build(responses=(), *, clock=None, **kwargs):
    transport = FakeTransport(responses)
    limiter = (RateLimiter(50, 1.0, clock=clock, sleep=clock.sleep)
               if clock else RateLimiter())
    client = OzonClient(
        "111", "secret-key",
        transport=transport, limiter=limiter,
        sleep=clock.sleep if clock else (lambda _: None),
        **kwargs,
    )
    return client, transport


# --- защита от записи в боевой магазин ------------------------------------


def test_writing_method_blocked_by_default():
    """У Ozon нет песочницы — случайный POST меняет живые цены."""
    client, transport = build()
    with pytest.raises(OzonWriteBlockedError) as exc:
        client.call("prices_import", {"prices": []})
    assert transport.calls == []
    assert "песочниц" in str(exc.value)
    assert "allow_writes=True" in str(exc.value)


def test_reading_method_allowed_by_default():
    client, _ = build([ok({"result": {"items": []}})])
    assert client.call("product_list") == {"result": {"items": []}}


def test_writing_allowed_when_asked():
    client, transport = build([ok({"result": "ok"})], allow_writes=True)
    client.call("stocks_update", {"stocks": []})
    assert len(transport.calls) == 1


@pytest.mark.parametrize("name", ["product_import", "product_delete", "fbs_ship"])
def test_all_writing_methods_are_blocked(name):
    client, _ = build()
    with pytest.raises(OzonWriteBlockedError):
        client.call(name, {})


# --- маршрутизация и заголовки --------------------------------------------


def test_path_comes_from_registry_with_right_version():
    client, transport = build([ok()])
    client.call("prices_info", {"limit": 10})
    assert transport.calls[0]["url"] == (
        "https://api-seller.ozon.ru/v5/product/info/prices"
    )


def test_auth_headers():
    client, transport = build([ok()])
    client.call("product_list")
    headers = transport.calls[0]["headers"]
    assert headers["Client-Id"] == "111"
    assert headers["Api-Key"] == "secret-key"
    assert "Authorization" not in headers


def test_oauth_token_replaces_api_key():
    """Методы Ozon Доставки требуют OAuth, а не Api-Key."""
    client, transport = build([ok()], oauth_token="tok")
    client.call("product_list")
    headers = transport.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    assert "Api-Key" not in headers


def test_posts_by_default_with_empty_body():
    client, transport = build([ok()])
    client.call("product_list")
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["json"] == {}


def test_unknown_method_fails_before_network():
    client, transport = build()
    with pytest.raises(UnknownMethodError):
        client.call("product_prices")
    assert transport.calls == []


def test_client_requires_credentials():
    with pytest.raises(ValueError):
        OzonClient("", "key")
    with pytest.raises(ValueError):
        OzonClient("111", "")


# --- ошибки и повторы -----------------------------------------------------


def test_validation_error_is_not_retried():
    client, transport = build([err(400, "bad payload")])
    with pytest.raises(OzonValidationError):
        client.call("product_list")
    assert len(transport.calls) == 1


def test_dead_key_is_not_retried(clock):
    client, transport = build([err(500, "Api-key is deactivated")], clock=clock)
    with pytest.raises(OzonAuthError):
        client.call("product_list")
    assert len(transport.calls) == 1


def test_circle_is_open_is_retried_then_succeeds(clock):
    """Временная блокировка Ozon проходит сама — ждём дольше обычного."""
    client, transport = build(
        [err(500, "Circle is open"), ok({"result": 1})], clock=clock
    )
    assert client.call("product_list") == {"result": 1}
    assert len(transport.calls) == 2
    assert clock.slept[0] == 30.0


def test_internal_error_is_retried(clock):
    client, transport = build([err(500, "Internal error"), ok({"ok": True})],
                              clock=clock)
    assert client.call("product_list") == {"ok": True}
    assert len(transport.calls) == 2


def test_retries_give_up_and_raise(clock):
    client, transport = build([err(500, "Internal error")] * 3, clock=clock)
    with pytest.raises(OzonTemporaryError):
        client.call("product_list")
    assert len(transport.calls) == 3


def test_rate_limit_is_retried(clock):
    client, _ = build(
        [err(429, "You have reached request rate limit per second"), ok({"ok": 1})],
        clock=clock,
    )
    assert client.call("product_list") == {"ok": 1}


def test_wrong_version_reads_as_not_found():
    client, _ = build([err(404, "method is not allowed")])
    with pytest.raises(OzonNotFoundError):
        client.call("product_list")


def test_max_retries_respected(clock):
    client, transport = build([fail(503)] * 5, clock=clock, max_retries=5)
    with pytest.raises(OzonError):
        client.call("product_list")
    assert len(transport.calls) == 5


# --- батчи ----------------------------------------------------------------


def test_batched_splits_by_hundred():
    """Ozon принимает до 100 товаров и на 150 отвечает ошибкой."""
    client, transport = build([ok({"result": 1}), ok({"result": 2})],
                              allow_writes=True)
    items = [{"offer_id": str(i)} for i in range(150)]
    results = client.call_batched("stocks_update", items, key="stocks")

    assert len(results) == 2
    assert len(transport.calls[0]["json"]["stocks"]) == 100
    assert len(transport.calls[1]["json"]["stocks"]) == 50


def test_batched_passes_extra_fields():
    client, transport = build([ok()], allow_writes=True)
    client.call_batched("prices_import", [{"offer_id": "a"}], key="prices",
                        extra={"currency": "RUB"})
    assert transport.calls[0]["json"]["currency"] == "RUB"


def test_batched_respects_write_protection():
    client, transport = build()
    with pytest.raises(OzonWriteBlockedError):
        client.call_batched("stocks_update", [{"a": 1}], key="stocks")
    assert transport.calls == []


# --- срок действия ключа --------------------------------------------------


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_key_info_reads_expiry():
    client, _ = build([ok({"result": {"expires_at": _iso(40)}})])
    info = client.key_info()
    assert info.days_left in (39, 40)
    assert not info.is_expired


def test_key_info_handles_z_suffix():
    client, _ = build([ok({"expires_at": "2030-01-01T00:00:00Z"})])
    assert client.key_info().expires_at.year == 2030


def test_key_info_without_expiry():
    client, _ = build([ok({"result": {}})])
    info = client.key_info()
    assert info.expires_at is None
    assert info.days_left is None
    assert not info.is_expired


def test_key_info_reads_roles():
    client, _ = build([ok({"result": {"roles": [{"name": "admin"}, "seller"]}})])
    assert client.key_info().roles == ("admin", "seller")


def test_expired_key_raises_on_ensure():
    client, _ = build([ok({"result": {"expires_at": _iso(-1)}})])
    with pytest.raises(OzonKeyExpiredError):
        client.ensure_key_alive()


def test_ensure_key_alive_warns_but_passes(caplog):
    client, _ = build([ok({"result": {"expires_at": _iso(3)}})])
    with caplog.at_level("WARNING"):
        info = client.ensure_key_alive(warn_days=14)
    assert not info.is_expired
    assert any("истекает" in r.message for r in caplog.records)


def test_garbage_expiry_is_ignored():
    client, _ = build([ok({"result": {"expires_at": "скоро"}})])
    assert client.key_info().expires_at is None


# --- ожидание асинхронной операции ---------------------------------------


def test_wait_task_polls_until_done(clock):
    client, transport = build(
        [ok({"status": "pending"}), ok({"status": "pending"}), ok({"status": "done"})],
        clock=clock,
    )
    result = client.wait_task(
        "product_import_info", {"task_id": 7},
        is_done=lambda r: r["status"] == "done", interval=1.0,
    )
    assert result["status"] == "done"
    assert len(transport.calls) == 3


def test_wait_task_gives_up():
    client, _ = build([ok({"status": "pending"})] * 3)
    with pytest.raises(OzonError) as exc:
        client.wait_task("product_import_info", {"task_id": 1},
                         is_done=lambda r: False, interval=0, attempts=3)
    assert "не завершилась" in str(exc.value)
