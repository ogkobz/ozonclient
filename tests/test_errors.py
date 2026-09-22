"""Разбор ошибок Ozon.

Главное, что здесь проверяется: одинаковый HTTP-код может означать
«подожди и повтори» и «чини ключ», и различить их можно только по тексту.
"""

from __future__ import annotations

import pytest

from ozonclient.errors import (
    RETRYABLE,
    OzonAuthError,
    OzonError,
    OzonForbiddenError,
    OzonIPRestrictedError,
    OzonNotFoundError,
    OzonOfferNotSignedError,
    OzonRateLimitError,
    OzonServerError,
    OzonTemporaryError,
    OzonValidationError,
    error_from_response,
)


# --- классификация по тексту ---------------------------------------------


@pytest.mark.parametrize("message,expected", [
    ("Invalid Api-Key, please check the key and try again", OzonAuthError),
    ("Api-key is deactivated, use another one or generate a new one", OzonAuthError),
    ("Api-Key is missing a required role for a method", OzonAuthError),
    ("Api-Key is restricted to specific IP addresses", OzonIPRestrictedError),
    ("token must be issued for seller, not oauth-client", OzonAuthError),
    ("Offer not signed", OzonOfferNotSignedError),
    ("Circle is open", OzonTemporaryError),
    ("Internal error", OzonTemporaryError),
    ("You have reached request rate limit per second", OzonRateLimitError),
    ("method is not allowed", OzonNotFoundError),
])
def test_message_decides_the_type(message, expected):
    assert isinstance(error_from_response(500, {"message": message}), expected)


def test_text_beats_status_code():
    """«Circle is open» приходит как 500, но лечится повтором, а не разбором."""
    error = error_from_response(500, {"message": "Circle is open"})
    assert isinstance(error, OzonTemporaryError)
    assert isinstance(error, RETRYABLE)


def test_bad_key_on_500_is_not_retried():
    """А вот мёртвый ключ повтором не вылечишь, каким бы ни был код."""
    error = error_from_response(500, {"message": "Invalid Api-Key"})
    assert isinstance(error, OzonAuthError)
    assert not isinstance(error, RETRYABLE)


def test_case_does_not_matter():
    assert isinstance(
        error_from_response(200, {"message": "CIRCLE IS OPEN"}), OzonTemporaryError
    )


# --- классификация по коду ------------------------------------------------


@pytest.mark.parametrize("status,expected", [
    (400, OzonValidationError),
    (401, OzonAuthError),
    (403, OzonForbiddenError),
    (404, OzonNotFoundError),
    (429, OzonRateLimitError),
    (500, OzonServerError),
    (503, OzonServerError),
])
def test_status_maps_when_text_says_nothing(status, expected):
    error = error_from_response(status, {"message": "что-то пошло не так"})
    assert isinstance(error, expected)
    assert error.status == status


def test_unmapped_status_falls_back_to_base():
    assert type(error_from_response(418, {"message": "чайник"})) is OzonError


# --- разбор тела ----------------------------------------------------------


def test_reads_code_and_details():
    error = error_from_response(400, {
        "code": 16, "message": "нет такого товара", "details": [{"typeUrl": "x"}],
    })
    assert error.code == 16
    assert error.details == [{"typeUrl": "x"}]
    assert "нет такого товара" in str(error)


def test_plain_text_body():
    """Часть ошибок Ozon приходит простым текстом, а не JSON."""
    error = error_from_response(502, "Bad Gateway")
    assert error.message == "Bad Gateway"


def test_empty_body_falls_back_to_status():
    assert "HTTP 500" in error_from_response(500, None).message


def test_error_field_instead_of_message():
    assert error_from_response(400, {"error": "bad request"}).message == "bad request"


def test_message_nested_in_result():
    body = {"result": {"message": "product_is_not_created"}}
    assert error_from_response(400, body).message == "product_is_not_created"


def test_retryable_set():
    assert isinstance(error_from_response(503, None), RETRYABLE)
    assert isinstance(error_from_response(429, None), RETRYABLE)
    assert not isinstance(error_from_response(400, None), RETRYABLE)
    assert not isinstance(error_from_response(404, None), RETRYABLE)


def test_str_includes_status_and_code():
    text = str(error_from_response(400, {"message": "ошибка", "code": 3}))
    assert "HTTP 400" in text and "code 3" in text
