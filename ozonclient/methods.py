"""Реестр методов Ozon Seller API.

Зачем он нужен. У Ozon один хост — api-seller.ozon.ru — но версия зашита
в путь, и разные ресурсы живут в разных версиях одновременно:

    /v3/product/list              список товаров
    /v4/product/info/attributes   характеристики
    /v5/product/info/prices       цены
    /v6/fbs/posting/product/exemplar/set   экземпляры

Угадать версию по аналогии нельзя: нет никакой закономерности, по которой
из «product/list это v3» следовало бы «product/info/prices это тоже v3».
Ошибка версии возвращает "method is not allowed" — то есть выглядит как
«такого метода не существует», хотя метод есть, просто в другой версии.

Поэтому пути не пишутся руками по памяти, а берутся по короткому имени.

Второе назначение реестра — флаг writes. У Ozon нет песочницы, рабочая
среда это боевой магазин продавца. Клиент должен знать, какой вызов
изменит данные, чтобы не дать сделать это случайно.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Method:
    """Метод API: путь с версией и признак изменения данных."""

    path: str
    writes: bool = False
    title: str = ""
    #: имя поля с идентификатором задачи, если метод асинхронный
    task_field: str | None = None


class UnknownMethodError(KeyError):
    """Метода нет в реестре."""


METHODS: dict[str, Method] = {
    # --- доступы и кабинет ---
    "roles": Method("/v1/roles", title="Права и срок действия ключа"),
    "seller_info": Method("/v1/seller/info", title="Информация о продавце"),

    # --- товары ---
    "product_list": Method("/v3/product/list", title="Список товаров"),
    "product_info_list": Method("/v3/product/info/list", title="Информация о товарах"),
    "product_attributes": Method("/v4/product/info/attributes",
                                 title="Характеристики товаров"),
    "product_description": Method("/v1/product/info/description",
                                  title="Название и описание"),
    "product_import": Method("/v3/product/import", writes=True,
                             title="Загрузка и обновление товаров",
                             task_field="task_id"),
    "product_import_info": Method("/v1/product/import/info",
                                  title="Статус загрузки товаров"),
    "product_attributes_update": Method("/v1/product/attributes/update", writes=True,
                                        title="Обновление характеристик"),
    "product_archive": Method("/v1/product/archive", writes=True,
                              title="В архив"),
    "product_unarchive": Method("/v1/product/unarchive", writes=True,
                                title="Из архива"),
    "product_delete": Method("/v2/products/delete", writes=True,
                             title="Удаление товара"),
    "pictures_import": Method("/v2/product/pictures/import", writes=True,
                              title="Загрузка изображений"),
    "pictures_info": Method("/v2/product/pictures/info",
                            title="Статус загрузки изображений"),

    # --- цены и остатки ---
    "prices_info": Method("/v5/product/info/prices", title="Цены и комиссии"),
    "prices_import": Method("/v1/product/import/prices", writes=True,
                            title="Обновление цен"),
    "stocks_update": Method("/v2/products/stocks", writes=True,
                            title="Обновление остатков"),
    "stocks_info": Method("/v4/product/info/stocks", title="Остатки"),
    "stocks_by_warehouse": Method("/v2/product/info/stocks-by-warehouse/fbs",
                                  title="Остатки FBS по складам"),

    # --- заказы FBO ---
    "fbo_list": Method("/v2/posting/fbo/list", title="Отправления FBO"),
    "fbo_get": Method("/v2/posting/fbo/get", title="Отправление FBO"),

    # --- заказы FBS и rFBS ---
    "fbs_list": Method("/v3/posting/fbs/list", title="Отправления FBS"),
    "fbs_get": Method("/v3/posting/fbs/get", title="Отправление FBS"),
    "fbs_unfulfilled": Method("/v3/posting/fbs/unfulfilled/list",
                              title="Необработанные отправления"),
    "fbs_get_by_barcode": Method("/v2/posting/fbs/get-by-barcode",
                                 title="Отправление по штрихкоду"),
    "fbs_ship": Method("/v4/posting/fbs/ship", writes=True, title="Сборка заказа"),
    "fbs_ship_package": Method("/v4/posting/fbs/ship/package", writes=True,
                               title="Частичная сборка"),
    "fbs_cancel": Method("/v2/posting/fbs/cancel", writes=True,
                         title="Отмена отправления"),
    "fbs_cancel_reasons": Method("/v2/posting/fbs/cancel-reason/list",
                                 title="Причины отмены"),
    "fbs_product_cancel": Method("/v2/posting/fbs/product/cancel", writes=True,
                                 title="Отмена части товаров"),
    "fbs_act_create": Method("/v2/posting/fbs/act/create", writes=True,
                             title="Создание отгрузки"),
    "fbs_act_check": Method("/v2/posting/fbs/act/check-status",
                            title="Статус отгрузки"),
    "package_label_create": Method("/v3/posting/fbs/package-label/create", writes=True,
                                   title="Создание наклеек", task_field="task_id"),
    "package_label_get": Method("/v2/posting/fbs/package-label/get",
                                title="Получение наклеек"),

    # --- склады ---
    "warehouse_list": Method("/v2/warehouse/list", title="Список складов"),
    "delivery_method_list": Method("/v2/delivery-method/list",
                                   title="Методы доставки"),
    "warehouse_operation_status": Method("/v1/warehouse/operation/status",
                                         title="Статус операции со складом"),

    # --- возвраты ---
    "returns_list": Method("/v1/returns/list", title="Возвраты"),

    # --- аналитика и финансы ---
    "analytics_stocks": Method("/v1/analytics/stocks", title="Отчёт по остаткам"),

    # --- акции ---
    "actions": Method("/v1/actions", title="Акции Ozon"),
    "actions_candidates": Method("/v1/actions/candidates",
                                 title="Товары-кандидаты в акцию"),
    "actions_products": Method("/v1/actions/products", title="Товары в акции"),
    "actions_activate": Method("/v1/actions/products/activate", writes=True,
                               title="Добавить товары в акцию"),
    "actions_deactivate": Method("/v1/actions/products/deactivate", writes=True,
                                 title="Убрать товары из акции"),

    # --- категории и характеристики ---
    "category_tree": Method("/v1/description-category/tree",
                            title="Дерево категорий"),
    "category_attribute": Method("/v1/description-category/attribute",
                                 title="Характеристики категории"),
    "category_attribute_values": Method("/v1/description-category/attribute/values",
                                        title="Значения характеристики"),
}

#: Максимум объектов в одном запросе у батчевых методов (из документации).
BATCH_LIMITS: dict[str, int] = {
    "product_import": 100,
    "stocks_update": 100,
    "prices_import": 100,
}


def get_method(name: str) -> Method:
    try:
        return METHODS[name]
    except KeyError:
        raise UnknownMethodError(
            f"Неизвестный метод «{name}». Доступные: {', '.join(sorted(METHODS))}"
        ) from None


def batch_limit(name: str) -> int | None:
    """Сколько объектов можно передать за один вызов, если лимит известен."""
    return BATCH_LIMITS.get(name)


def chunked(items: list, size: int):
    """Режет список на куски по size элементов.

    Ozon принимает до 100 товаров за раз; превышение — ошибка, а не
    молчаливое усечение, поэтому резать нужно на своей стороне.
    """
    if size < 1:
        raise ValueError("Размер куска должен быть положительным")
    for start in range(0, len(items), size):
        yield items[start:start + size]
