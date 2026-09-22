"""Реестр методов.

Смысл реестра в том, что версию метода нельзя вывести по аналогии:
список товаров живёт в v3, характеристики в v4, цены в v5. Ошибка
версии возвращает «method is not allowed», то есть маскируется
под несуществующий метод.
"""

from __future__ import annotations

import pytest

from ozonclient.methods import (
    BATCH_LIMITS,
    METHODS,
    UnknownMethodError,
    batch_limit,
    chunked,
    get_method,
)


def test_versions_differ_between_neighbouring_resources():
    """Один и тот же «product», но три разные версии — это и есть ловушка."""
    assert get_method("product_list").path == "/v3/product/list"
    assert get_method("product_attributes").path == "/v4/product/info/attributes"
    assert get_method("prices_info").path == "/v5/product/info/prices"


def test_every_path_starts_with_version():
    for name, method in METHODS.items():
        assert method.path.startswith("/v"), f"{name}: {method.path}"


def test_paths_are_unique():
    paths = [m.path for m in METHODS.values()]
    assert len(paths) == len(set(paths))


def test_unknown_method_lists_known_ones():
    with pytest.raises(UnknownMethodError) as exc:
        get_method("product_prices")
    assert "product_list" in str(exc.value)


# --- признак записи -------------------------------------------------------


@pytest.mark.parametrize("name", [
    "product_import", "prices_import", "stocks_update", "product_delete",
    "product_archive", "fbs_ship", "fbs_cancel", "actions_activate",
])
def test_writing_methods_are_marked(name):
    assert get_method(name).writes is True


@pytest.mark.parametrize("name", [
    "product_list", "prices_info", "stocks_info", "fbs_list",
    "returns_list", "warehouse_list", "roles", "category_tree",
])
def test_reading_methods_are_not_marked(name):
    assert get_method(name).writes is False


def test_import_is_async_and_declares_its_task_field():
    assert get_method("product_import").task_field == "task_id"
    assert get_method("product_list").task_field is None


# --- батчи ----------------------------------------------------------------


def test_batch_limits_are_hundred():
    """Документация: до 100 товаров в одном запросе."""
    for name, limit in BATCH_LIMITS.items():
        assert limit == 100, name
        assert name in METHODS


def test_batch_limit_unknown_method_is_none():
    assert batch_limit("product_list") is None


def test_chunked_splits_evenly():
    assert list(chunked(list(range(5)), 2)) == [[0, 1], [2, 3], [4]]


def test_chunked_exact_fit():
    assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_chunked_empty():
    assert list(chunked([], 10)) == []


def test_chunked_rejects_zero():
    with pytest.raises(ValueError):
        list(chunked([1, 2], 0))
