"""Клиент Ozon Seller API.

Что он делает сверх обычного requests:

* **не даёт случайно изменить боевой магазин.** У Ozon нет песочницы:
  рабочая среда — это ваш настоящий кабинет, и любой POST меняет реальные
  цены, остатки и заказы. Поэтому изменяющие методы заблокированы,
  пока не разрешишь их явно;
* берёт путь метода из реестра, а не из памяти — у Ozon версия зашита
  в путь, и промах версией выглядит как «метода не существует»;
* считает лимит 50 запросов в секунду сам, потому что Ozon не сообщает
  состояние лимита в заголовках;
* различает ошибки по тексту, а не только по коду: «Circle is open»
  лечится ожиданием, «Api-key is deactivated» — нет.

Сетевой слой абстрагирован, поэтому клиент тестируется без сети.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from .errors import (
    RETRYABLE,
    OzonError,
    OzonKeyExpiredError,
    OzonRateLimitError,
    OzonWriteBlockedError,
    error_from_response,
)
from .methods import Method, batch_limit, chunked, get_method
from .ratelimit import RateLimiter

log = logging.getLogger("ozonclient")

BASE_URL = "https://api-seller.ozon.ru"


@dataclass
class Response:
    """Ответ транспорта в независимом от библиотеки виде."""

    status: int
    json: Any = None
    headers: dict = field(default_factory=dict)


class Transport(Protocol):
    """Минимум, который нужен клиенту от HTTP-слоя."""

    def request(self, method: str, url: str, *, headers: dict,
                json: Any, timeout: float) -> Response:
        ...


class RequestsTransport:
    """Транспорт на requests. Импорт внутри, чтобы ядро не зависело от него."""

    def __init__(self, session=None):
        import requests  # noqa: PLC0415 — зависимость нужна только здесь

        self._session = session or requests.Session()

    def request(self, method, url, *, headers, json, timeout) -> Response:
        resp = self._session.request(method, url, headers=headers,
                                     json=json, timeout=timeout)
        try:
            body = resp.json() if resp.content else None
        except ValueError:
            # На части ошибок Ozon отвечает простым текстом.
            body = resp.text
        return Response(status=resp.status_code, json=body,
                        headers=dict(resp.headers))


@dataclass(frozen=True)
class KeyInfo:
    """Что известно про ключ после обращения к /v1/roles."""

    expires_at: datetime | None
    roles: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return _now() >= self.expires_at

    @property
    def days_left(self) -> int | None:
        """Сколько дней осталось. Ключи Ozon живут три месяца."""
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - _now()).days)


class OzonClient:
    """Клиент Ozon Seller API.

    >>> client = OzonClient("123456", "ключ")          # doctest: +SKIP
    >>> client.call("product_list", {"limit": 10})     # doctest: +SKIP
    """

    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        allow_writes: bool = False,
        transport: Transport | None = None,
        limiter: RateLimiter | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        base_url: str = BASE_URL,
        oauth_token: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """
        allow_writes — разрешить методы, изменяющие данные магазина.
            По умолчанию False. Это не перестраховка: у Ozon нет тестового
            контура, и ошибочный вызов /v1/product/import/prices меняет
            цены в живом магазине немедленно.
        oauth_token — для методов Ozon Доставки, которые работают
            по OAuth, а не по Api-Key.
        """
        if not client_id or not api_key:
            raise ValueError("Нужны Client-Id и Api-Key из личного кабинета")

        self.client_id = str(client_id).strip()
        self.api_key = str(api_key).strip()
        self.oauth_token = oauth_token
        self.allow_writes = allow_writes
        self.base_url = base_url.rstrip("/")
        self.transport = transport or RequestsTransport()
        self.limiter = limiter or RateLimiter()
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep

    # --- основное ---------------------------------------------------------

    def call(self, name: str, payload: Any = None, *,
             http_method: str = "POST") -> Any:
        """Вызывает метод по короткому имени из реестра.

        Почти все методы Ozon — POST с телом JSON, даже те, что только
        читают данные.
        """
        method = get_method(name)
        self._check_write(name, method)

        url = self.base_url + method.path
        last: OzonError | None = None

        for attempt in range(1, self.max_retries + 1):
            self.limiter.acquire(name)
            resp = self.transport.request(
                http_method, url, headers=self._headers(),
                json=payload if payload is not None else {},
                timeout=self.timeout,
            )

            if 200 <= resp.status < 300:
                return resp.json

            error = error_from_response(resp.status, resp.json)

            if isinstance(error, OzonRateLimitError):
                self.limiter.penalize(error.retry_after)

            if not isinstance(error, RETRYABLE) or attempt == self.max_retries:
                raise error

            delay = _backoff(attempt, error)
            log.info("%s -> %s. Повтор %s из %s через %.1f с: %s",
                     method.path, resp.status, attempt, self.max_retries,
                     delay, error.message)
            self._sleep(delay)
            last = error

        raise last or OzonError("Запрос не выполнен")

    def call_batched(self, name: str, items: list, *,
                     key: str, extra: dict | None = None) -> list:
        """Разбивает список на куски по лимиту метода и шлёт по частям.

        Ozon принимает до 100 объектов за раз и на превышение отвечает
        ошибкой, а не обрезает молча. Возвращает список ответов по кускам.
        """
        size = batch_limit(name) or 100
        results = []
        for part in chunked(items, size):
            payload = dict(extra or {})
            payload[key] = part
            results.append(self.call(name, payload))
        return results

    # --- состояние ключа --------------------------------------------------

    def key_info(self) -> KeyInfo:
        """Читает права и срок действия ключа через /v1/roles.

        Ключи Ozon живут три месяца, и узнать дату окончания можно только
        запросом — в самом ключе её нет, в отличие от JWT у Wildberries.
        Проверку стоит держать в мониторинге: интеграция умирает тихо,
        в день истечения.
        """
        data = self.call("roles") or {}
        result = data.get("result", data)
        return KeyInfo(
            expires_at=_parse_time(result.get("expires_at")),
            roles=tuple(_role_names(result)),
            raw=result if isinstance(result, dict) else {},
        )

    def ensure_key_alive(self, warn_days: int = 14) -> KeyInfo:
        """Проверяет ключ и предупреждает, если он скоро истечёт."""
        info = self.key_info()
        if info.is_expired:
            raise OzonKeyExpiredError(
                "Срок действия Api-Key истёк. Сгенерируйте новый: "
                "личный кабинет → Настройки → Seller API."
            )
        if info.days_left is not None and info.days_left <= warn_days:
            log.warning("Api-Key истекает через %s дн. Пора выпускать новый.",
                        info.days_left)
        return info

    # --- асинхронные операции ---------------------------------------------

    def wait_task(self, status_method: str, payload: Any, *,
                  is_done: Callable[[Any], bool],
                  interval: float = 3.0, attempts: int = 20) -> Any:
        """Опрашивает статус асинхронной операции, пока она не завершится.

        Загрузка товаров, создание складов, грузоместа и наклейки у Ozon
        асинхронные: метод возвращает task_id или operation_id, а результат
        забирается отдельным вызовом. Готовность проверяет is_done —
        ответы у разных методов устроены по-разному.
        """
        last = None
        for _ in range(attempts):
            last = self.call(status_method, payload)
            if is_done(last):
                return last
            self._sleep(interval)
        raise OzonError(
            f"Операция не завершилась за {attempts} проверок "
            f"({status_method}). Последний ответ сохранён в details.",
        )

    # --- внутреннее -------------------------------------------------------

    def _headers(self) -> dict:
        if self.oauth_token:
            return {
                "Authorization": f"Bearer {self.oauth_token}",
                "Content-Type": "application/json",
            }
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _check_write(self, name: str, method: Method) -> None:
        if method.writes and not self.allow_writes:
            raise OzonWriteBlockedError(
                f"Метод «{name}» ({method.path}) изменяет данные магазина, "
                f"а запись не разрешена. У Ozon нет песочницы: этот вызов "
                f"подействует на живой кабинет. Если это осознанно, создайте "
                f"клиент с allow_writes=True."
            )


def _backoff(attempt: int, error: OzonError) -> float:
    """Задержка перед повтором.

    Для «Circle is open» Ozon пишет «в течение нескольких минут метод
    начнёт работать как обычно», поэтому пауза заметно длиннее обычной.
    """
    if isinstance(error, OzonRateLimitError):
        return float(error.retry_after)
    if "circle is open" in error.message.lower():
        return float(30 * attempt)
    return float(2 ** (attempt - 1))


def _now() -> datetime:
    """Ozon работает по UTC, поэтому и сравниваем в UTC."""
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _role_names(result: object) -> list:
    if not isinstance(result, dict):
        return []
    roles = result.get("roles") or []
    names = []
    for role in roles:
        if isinstance(role, dict):
            name = role.get("name") or role.get("role")
            if name:
                names.append(str(name))
        elif isinstance(role, str):
            names.append(role)
    return names
