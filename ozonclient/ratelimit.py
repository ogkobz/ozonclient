"""Соблюдение лимитов Ozon Seller API.

Из документации: «Вы можете отправить не больше 50 запросов в секунду
на все методы с одного Client ID». Плюс у отдельных методов есть свои,
более узкие ограничения.

Важное отличие от Wildberries: Ozon не сообщает состояние лимита
в заголовках ответа. Подсказки «сколько осталось» и «когда повторить»
не будет — считать приходится самому.

Отсюда конструкция: скользящее окно в одну секунду на весь Client-Id
плюс, при необходимости, отдельное окно на конкретный метод. Ozon
предупреждает, что при потоке одинаковых или ошибочных запросов доступ
могут ограничить без предупреждения, так что дешевле подождать, чем
упереться в блокировку.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Скользящее окно: не больше N запросов за period секунд.

    Потокобезопасен — один клиент можно использовать из нескольких потоков.
    """

    def __init__(self, limit: int = 50, period: float = 1.0, *,
                 clock=time.monotonic, sleep=time.sleep):
        """
        limit — сколько запросов разрешено за период. По умолчанию 50:
            это лимит Ozon на один Client-Id.
        clock и sleep вынесены в параметры, чтобы тесты не ждали реального
            времени.
        """
        if limit < 1:
            raise ValueError("Лимит должен быть положительным")
        self.limit = limit
        self.period = period
        self._clock = clock
        self._sleep = sleep
        self._hits: deque[float] = deque()
        self._method_hits: dict[str, deque[float]] = {}
        self._method_limits: dict[str, int] = {}
        self._lock = threading.Lock()

    def set_method_limit(self, method: str, limit: int) -> None:
        """Задаёт отдельный лимит для метода, более узкий чем общий."""
        with self._lock:
            self._method_limits[method] = limit

    def acquire(self, method: str | None = None) -> float:
        """Дожидается своей очереди. Возвращает, сколько пришлось ждать.

        Сначала считает общий лимит на Client-Id, потом — лимит метода,
        если он задан. Ждёт по большему из двух.
        """
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                self._trim(self._hits, now)
                delay = 0.0

                if len(self._hits) >= self.limit:
                    delay = self._hits[0] + self.period - now

                if method and method in self._method_limits:
                    hits = self._method_hits.setdefault(method, deque())
                    self._trim(hits, now)
                    if len(hits) >= self._method_limits[method]:
                        delay = max(delay, hits[0] + self.period - now)

                if delay <= 0:
                    self._hits.append(now)
                    if method and method in self._method_limits:
                        self._method_hits[method].append(now)
                    return waited

            # Спим вне блокировки, иначе остальные потоки встанут тоже.
            self._sleep(delay)
            waited += delay

    def penalize(self, seconds: float) -> None:
        """Отодвигает окно после отказа по лимиту.

        Ozon не говорит, сколько ждать, поэтому решение принимает вызывающий:
        окно просто заполняется отметками времени в будущем.
        """
        with self._lock:
            # Отметки ставятся так, чтобы окно освободилось ровно через
            # seconds: самая старая из них выпадет из окна в этот момент.
            oldest = self._clock() + seconds - self.period
            self._hits.clear()
            for _ in range(self.limit):
                self._hits.append(oldest)

    def _trim(self, hits: deque[float], now: float) -> None:
        """Выбрасывает отметки старше периода."""
        boundary = now - self.period
        while hits and hits[0] <= boundary:
            hits.popleft()

    @property
    def in_window(self) -> int:
        """Сколько запросов учтено в текущем окне — для диагностики."""
        with self._lock:
            self._trim(self._hits, self._clock())
            return len(self._hits)
