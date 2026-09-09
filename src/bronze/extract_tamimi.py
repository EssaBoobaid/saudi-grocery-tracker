"""Tamimi Markets Bronze Ingestion Pipeline.

Pulls products from Tamimi API, normalizes variant structures,
and stores Bronze files into data/bronze/tamimi/.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
import requests

PRODUCT_API = "https://shop.tamimimarkets.com/api/product"
API_LIMIT = 100
MAX_PAGES_SAFETY = 50
REQUEST_DELAY_SECONDS = 0.3

CATEGORIES = {
    "fruits_and_vegetables": {
        "name": "Fresh Fruits & Veg",
        "query": "fruits vegetables",
        "category_id": 3,
        "category_slug": "fruits--vegetables",
        "output_filename": "fruits_and_vegetables_raw.json",
    },
    "dairy_and_eggs": {
        "name": "Dairy & Eggs",
        "query": "dairy",
        "category_id": 36,
        "category_slug": "dairy",
        "output_filename": "dairy_and_eggs_raw.json",
    },
    "beverages": {
        "name": "Beverages & Water",
        "query": "water beverages",
        "category_id": 82,
        "category_slug": "water--beverages",
        "output_filename": "beverages_raw.json",
    },
}

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "bronze" / "tamimi"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def get_all_category_nodes(product: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    current = product.get("primaryCategory")
    while isinstance(current, dict) and current:
        nodes.append(current)
        current = current.get("parentCategory")

    extra_cats = product.get("categories") or []
    if isinstance(extra_cats, list):
        for c in extra_cats:
            if isinstance(c, dict):
                nodes.append(c)

    return nodes


def product_belongs_to_category(product: dict[str, Any], target_id: int, target_slug: str) -> bool:
    for node in get_all_category_nodes(product):
        if node.get("id") == target_id:
            return True
        if clean_text(node.get("slug")) == target_slug:
            return True
    return False


def get_product_key(product: dict[str, Any]) -> str:
    pid = product.get("id")
    if pid is not None:
        return f"product:{pid}"
    slug = clean_text(product.get("slug"))
    name = clean_text(product.get("name"))
    return f"fallback:{slug}|{name}"


def get_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Origin": "https://shop.tamimimarkets.com",
        "Referer": "https://shop.tamimimarkets.com/",
    }


def fetch_page(query: str, offset: int) -> tuple[list[dict[str, Any]], int | None]:
    params = {"q": query, "limit": API_LIMIT, "offset": offset}
    response = requests.get(PRODUCT_API, params=params, headers=get_headers(), timeout=30)
    response.raise_for_status()

    payload = response.json()
    data = payload.get("data") or {}
    products = data.get("product") or []
    if not isinstance(products, list):
        products = []

    raw_total = data.get("count")
    try:
        total_count = int(raw_total) if raw_total is not None else None
    except (TypeError, ValueError):
        total_count = None

    return products, total_count


def flatten_product_variants(raw_products: list[dict[str, Any]], category_key: str) -> list[dict[str, Any]]:
    flattened_records = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue

        variants = item.get("variants") or []
        if "variant" in item and not variants:
            item["_category_key"] = category_key
            flattened_records.append(item)
            continue

        base_product = {
            "id": item.get("id"),
            "name": item.get("name"),
            "slug": item.get("slug"),
            "brand": item.get("brand"),
            "primaryCategory": item.get("primaryCategory"),
            "_category_key": category_key,
        }

        if variants:
            for var in variants:
                if isinstance(var, dict):
                    rec = dict(base_product)
                    rec["variant"] = var
                    flattened_records.append(rec)
        else:
            flattened_records.append(base_product)

    return flattened_records


def fetch_category_raw(config: dict[str, Any]) -> list[dict[str, Any]]:
    query = str(config["query"])
    category_id = int(config["category_id"])
    category_slug = str(config["category_slug"])
    cat_name = config["name"]

    print(f"\n[*] Processing: {cat_name}")
    category_products: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    offset = 0
    page_number = 0

    while page_number < MAX_PAGES_SAFETY:
        try:
            products, total_count = fetch_page(query=query, offset=offset)
        except Exception as err:
            print(f"    [!] Error at offset {offset}: {err}")
            break

        page_number += 1
        if not products:
            break

        for product in products:
            if not isinstance(product, dict):
                continue
            if not product_belongs_to_category(product, category_id, category_slug):
                continue

            pkey = get_product_key(product)
            if pkey in seen_keys:
                continue

            seen_keys.add(pkey)
            category_products.append(product)

        print(f"    • Page {page_number:<2} (offset {offset:<4}): Total kept: {len(category_products)}")
        offset += len(products)
        if total_count and offset >= total_count:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    return category_products


def main():
    print("=" * 65)
    print("🛒 EXTRACTING & NORMALIZING TAMIMI BRONZE DATA")
    print("=" * 65)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_all = 0

    for cat_key, config in CATEGORIES.items():
        try:
            raw_items = fetch_category_raw(config)
            flattened_items = flatten_product_variants(raw_items, cat_key)
            file_path = OUTPUT_DIR / config["output_filename"]

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(flattened_items, f, ensure_ascii=False, indent=2)

            total_all += len(flattened_items)
            print(f"  ✓ Saved {len(flattened_items)} normalized items to: {file_path.name}")
        except Exception as error:
            print(f"  ⚠️ Error on [{config['name']}]: {error}")

    print("\n" + "=" * 65)
    print(f"🎉 TAMIMI FINISHED! Total Saved: {total_all:,} items")
    print("=" * 65)


if __name__ == "__main__":
    main()