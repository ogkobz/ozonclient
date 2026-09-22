"""Исключения Ozon Seller API.

Главное отличие от большинства API: Ozon часто отвечает одним и тем же
HTTP-кодом на состояния, которые лечатся по-разному. Различать их можно
только по тексту сообщения.

Два примера из документации, оба приходят как ошибка сервера:

    "Circle is open"  — временная блокировка метода из-за потока запросов,
                        через несколько минут метод заработает сам;
    "Internal error"  — сервер не успел обработать запрос.

Оба лечатся повтором. А вот эти — нет, сколько ни повторяй:

    "Invalid Api-Key, please check the key and try again"
    "Api-key is deactivated, use another one or generate a new one"
    "Api-Key is missing a required role for a method"
    "Api-Key is restricted to specific IP addresses"

Поэтому классификация идёт по коду И по тексту, а решение о повторе
принимается по типу исключения.
"""

from __future__ import annotations

import re


class OzonError(Exception):
    """Базовая ошибка Ozon Seller API."""

    def __init__(self, message: str, *, status: int | None = None,
                 code: int | None = None, details: object = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.status is not None:
            parts.append(f"HTTP {self.status}")
        if self.code is not None:
            parts.append(f"code {self.code}")
        return ". ".join(parts)


class OzonAuthError(OzonError):
    """Ключ неверен, деактивирован или у него нет нужной роли.

    Повтор бессмысленен: нужно проверить ключ в личном кабинете
    (Настройки → Seller API) или выпустить новый.
    """


class OzonKeyExpiredError(OzonAuthError):
    """Срок действия ключа истёк. Ключи Ozon живут три месяца."""


class OzonIPRestrictedError(OzonAuthError):
    """Ключ разрешён только с определённых IP-адресов."""


class OzonOfferNotSignedError(OzonError):
    """403 Offer not signed — оферта неактуальна, доступ к API закрыт.

    Лечится принятием оферты в личном кабинете, а не кодом.
    """


class OzonForbiddenError(OzonError):
    """403 по другой причине."""


class OzonNotFoundError(OzonError):
    """404 либо "method is not allowed".

    У Ozon это чаще всего означает не «ресурса нет», а «не та версия метода»:
    один и тот же ресурс живёт в /v3, /v4 и /v5 одновременно. См. methods.py.
    """


class OzonValidationError(OzonError):
    """400 — запрос не прошёл проверку. Повтор без правок не поможет."""


class OzonRateLimitError(OzonError):
    """Превышен лимит: 50 запросов в секунду на один Client-Id.

    Учитываются и отдельные лимиты конкретных методов, поэтому упереться
    можно и не достигнув пятидесяти.
    """

    def __init__(self, message: str, *, retry_after: float = 1.0, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class OzonTemporaryError(OzonError):
    """Временное состояние на стороне Ozon: "Circle is open", "Internal error".

    Само пройдёт, нужно подождать и повторить.
    """


class OzonServerError(OzonError):
    """5XX без распознанного текста."""


class OzonWriteBlockedError(OzonError):
    """Клиент запретил изменяющий запрос.

    У Ozon нет песочницы: любой POST бьёт по живому магазину. Поэтому
    запись разрешается явным allow_writes=True, а не по умолчанию.
    """


# Повтор осмыслен только для этих.
RETRYABLE = (OzonRateLimitError, OzonTemporaryError, OzonServerError)


# Текстовые маркеры из раздела «Частые ошибки» документации.
_PATTERNS: tuple[tuple[str, type[OzonError]], ...] = (
    (r"api-?key is deactivated", OzonAuthError),
    (r"invalid api-?key", OzonAuthError),
    (r"missing a required role", OzonAuthError),
    (r"restricted to specific ip", OzonIPRestrictedError),
    (r"token must be issued for seller", OzonAuthError),
    (r"offer not signed", OzonOfferNotSignedError),
    (r"circle is open", OzonTemporaryError),
    (r"internal error", OzonTemporaryError),
    (r"request rate limit", OzonRateLimitError),
    (r"method is not allowed", OzonNotFoundError),
)


def _match(message: str) -> type[OzonError] | None:
    low = (message or "").lower()
    for pattern, cls in _PATTERNS:
        if re.search(pattern, low):
            return cls
    return None


def error_from_response(status: int, body: object) -> OzonError:
    """Собирает исключение по ответу Ozon.

    Тело ошибки обычно выглядит так:
        {"code": 16, "message": "Invalid Api-Key...", "details": [...]}
    но на части ошибок приходит просто текст, поэтому разбор терпимый
    к любому из вариантов.
    """
    message, code, details = _unpack(body)
    if not message:
        message = f"HTTP {status}"

    common = {"status": status, "code": code, "details": details}

    # Текст точнее кода: он отличает «подожди» от «чини ключ».
    matched = _match(message)
    if matched is not None:
        return matched(message, **common)

    if status == 400:
        return OzonValidationError(message, **common)
    if status in (401, 403):
        return OzonAuthError(message, **common) if status == 401 \
            else OzonForbiddenError(message, **common)
    if status == 404:
        return OzonNotFoundError(message, **common)
    if status == 429:
        return OzonRateLimitError(message, **common)
    if status >= 500:
        return OzonServerError(message, **common)
    return OzonError(message, **common)


def _unpack(body: object) -> tuple[str, int | None, object]:
    """Достаёт message, code и details из тела любого вида."""
    if isinstance(body, dict):
        message = body.get("message") or body.get("error") or ""
        if not message and isinstance(body.get("result"), dict):
            message = body["result"].get("message", "")
        code = body.get("code")
        return str(message), code if isinstance(code, int) else None, body.get("details")
    if isinstance(body, str):
        return body.strip(), None, None
    return "", None, None
