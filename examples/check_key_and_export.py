"""Проверка ключа и выгрузка товаров с ценами и остатками в CSV.

Пример показывает обычный сценарий: ежедневная выгрузка, которая должна
предупредить о смерти ключа раньше, чем встанет совсем.

    python examples/check_key_and_export.py catalog.csv

Реквизиты берутся из переменных окружения OZON_CLIENT_ID и OZON_API_KEY.
Скрипт только читает: клиент создаётся без allow_writes, поэтому магазину
он навредить не может даже при ошибке в коде.
"""

from __future__ import annotations

import csv
import os
import sys

from ozonclient import OzonClient, OzonError

FIELDS = ["offer_id", "product_id", "name", "price", "old_price",
          "marketing_price", "stock_fbs", "stock_fbo"]


def fetch_products(client: OzonClient) -> dict:
    """Забирает список товаров постранично.

    Ozon пагинирует курсором last_id: следующий запрос начинается с него.
    Пустой список товаров означает, что страницы кончились.
    """
    products: dict[str, dict] = {}
    last_id = ""

    while True:
        page = client.call("product_list", {
            "filter": {"visibility": "ALL"},
            "last_id": last_id,
            "limit": 1000,
        }) or {}
        result = page.get("result", {})
        items = result.get("items", []) or []
        if not items:
            break

        for item in items:
            offer_id = item.get("offer_id") or str(item.get("product_id", ""))
            products[offer_id] = {
                "offer_id": offer_id,
                "product_id": item.get("product_id", ""),
            }

        print(f"  товаров получено: {len(products)}")
        last_id = result.get("last_id") or ""
        if not last_id:
            break

    return products


def enrich_prices(client: OzonClient, products: dict) -> None:
    """Дописывает цены. Метод живёт в v5 — не в v3, как список товаров."""
    last_id = ""
    while True:
        page = client.call("prices_info", {
            "filter": {"visibility": "ALL"},
            "cursor": last_id,
            "limit": 1000,
        }) or {}
        items = (page.get("items") or page.get("result", {}).get("items") or [])
        if not items:
            break

        for item in items:
            row = products.get(item.get("offer_id"))
            if row is None:
                continue
            price = item.get("price", {}) or {}
            row["price"] = price.get("price", "")
            row["old_price"] = price.get("old_price", "")
            row["marketing_price"] = price.get("marketing_price", "")

        last_id = page.get("cursor") or ""
        if not last_id:
            break


def enrich_stocks(client: OzonClient, products: dict) -> None:
    """Дописывает остатки по схемам FBS и FBO."""
    cursor = ""
    while True:
        page = client.call("stocks_info", {
            "filter": {"visibility": "ALL"},
            "cursor": cursor,
            "limit": 1000,
        }) or {}
        items = page.get("items") or []
        if not items:
            break

        for item in items:
            row = products.get(item.get("offer_id"))
            if row is None:
                continue
            for stock in item.get("stocks", []) or []:
                kind = (stock.get("type") or "").lower()
                if kind == "fbs":
                    row["stock_fbs"] = stock.get("present", 0)
                elif kind == "fbo":
                    row["stock_fbo"] = stock.get("present", 0)

        cursor = page.get("cursor") or ""
        if not cursor:
            break


def main() -> int:
    client_id = os.environ.get("OZON_CLIENT_ID")
    api_key = os.environ.get("OZON_API_KEY")
    if not client_id or not api_key:
        print("Задайте OZON_CLIENT_ID и OZON_API_KEY", file=sys.stderr)
        return 1

    out_path = sys.argv[1] if len(sys.argv) > 1 else "catalog.csv"
    client = OzonClient(client_id, api_key)   # только чтение

    try:
        info = client.ensure_key_alive(warn_days=14)
        if info.days_left is not None:
            print(f"Ключ действует ещё {info.days_left} дн.")

        print("Забираю товары...")
        products = fetch_products(client)
        if not products:
            print("Товаров не найдено")
            return 0

        print("Забираю цены...")
        enrich_prices(client, products)
        print("Забираю остатки...")
        enrich_stocks(client, products)

    except OzonError as exc:
        print(f"Ozon вернул ошибку: {exc}", file=sys.stderr)
        return 1

    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(products.values())

    print(f"Готово: {len(products)} товаров в {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
