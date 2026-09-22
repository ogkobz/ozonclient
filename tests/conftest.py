"""Общие заготовки для тестов.

Сети здесь нет ни в одном тесте: транспорт и часы подменяются.
"""

from __future__ import annotations

import pytest

from ozonclient.client import Response


class FakeTransport:
    """Отдаёт заранее заданные ответы и запоминает вызовы."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers, json, timeout):
        self.calls.append({
            "method": method, "url": url, "headers": headers,
            "json": json, "timeout": timeout,
        })
        if not self.responses:
            raise AssertionError(f"Лишний запрос: {method} {url}")
        item = self.responses.pop(0)
        return item() if callable(item) else item


def ok(body=None) -> Response:
    return Response(status=200, json=body)


def fail(status: int, body=None) -> Response:
    return Response(status=status, json=body)


def err(status: int, message: str, code: int | None = None) -> Response:
    """Ответ с ошибкой в том виде, в каком её шлёт Ozon."""
    body = {"message": message}
    if code is not None:
        body["code"] = code
    return Response(status=status, json=body)


class FakeClock:
    """Монотонные часы, которые двигает только тест."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
