"""ozonclient — клиент Ozon Seller API.

Тонкая обёртка вокруг HTTP: реестр методов с версиями, защита от случайной
записи в боевой магазин, соблюдение лимита 50 запросов в секунду и разбор
ошибок по тексту, а не только по коду.

Бизнес-логики нет намеренно — она у каждого продавца своя.
"""

from .client import BASE_URL, KeyInfo, OzonClient, RequestsTransport, Response
from .errors import (
    RETRYABLE,
    OzonAuthError,
    OzonError,
    OzonForbiddenError,
    OzonIPRestrictedError,
    OzonKeyExpiredError,
    OzonNotFoundError,
    OzonOfferNotSignedError,
    OzonRateLimitError,
    OzonServerError,
    OzonTemporaryError,
    OzonValidationError,
    OzonWriteBlockedError,
    error_from_response,
)
from .methods import (
    BATCH_LIMITS,
    METHODS,
    Method,
    UnknownMethodError,
    batch_limit,
    chunked,
    get_method,
)
from .ratelimit import RateLimiter

__version__ = "0.1.0"

__all__ = [
    "OzonClient",
    "KeyInfo",
    "Response",
    "RequestsTransport",
    "BASE_URL",
    "RateLimiter",
    "Method",
    "METHODS",
    "BATCH_LIMITS",
    "get_method",
    "batch_limit",
    "chunked",
    "UnknownMethodError",
    "OzonError",
    "OzonAuthError",
    "OzonKeyExpiredError",
    "OzonIPRestrictedError",
    "OzonOfferNotSignedError",
    "OzonForbiddenError",
    "OzonNotFoundError",
    "OzonValidationError",
    "OzonRateLimitError",
    "OzonTemporaryError",
    "OzonServerError",
    "OzonWriteBlockedError",
    "RETRYABLE",
    "error_from_response",
    "__version__",
]
