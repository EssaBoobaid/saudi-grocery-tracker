"""Lulu Hypermarket Bronze Ingestion Pipeline (GCC API Engine).

Extracts targeted FMCG categories from Lulu Saudi API and saves them into the Bronze layer:
data/bronze/lulu/
  - beverages_raw.json
  - dairy_and_eggs_raw.json
  - fruits_and_vegetables_raw.json
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any
from curl_cffi import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "bronze" / "lulu"

# المعرفات الدقيقة للأقسام في GCC API
CATEGORIES = {
    "beverages": {
        "output_filename": "beverages_raw.json",
        "category_id": 5024,
    },
    "dairy_and_eggs": {
        "output_filename": "dairy_and_eggs_raw.json",
        "category_id": 5208,  # المعرف الشامل للألبان والبيض والأجبان
    },
    "fruits_and_vegetables": {
        "output_filename": "fruits_and_vegetables_raw.json",
        "category_id": 5231,  # المعرف الشامل للخضار والفواكه
    },
}

API_BASE = "https://gcc.luluhypermarket.com/api/client/category/{category_id}/"
PAGE_SIZE = 50
MAX_PAGES = 50
REQUEST_DELAY = 1.0

HEADERS = {
    "accept": "application/json",
    "accept-language": "ar-sa,en-US;q=0.9",
    "referer": "https://gcc.luluhypermarket.com/ar-sa/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "x-currency": "sar",
}

COOKIES = {
    "pz-locale": "ar-sa",
    "pz-currency": "sar",
    "pz-frontend-id": "6",
}


def unroll_lulu_product(prod: dict[str, Any], cat_key: str) -> list[dict[str, Any]]:
    """تفكيك خيارات الحبة الفردية والكرتون لتسجيل كل وحدة كمنتج مستقل."""
    variants = (prod.get("extra_data") or {}).get("variants") or prod.get("variants") or []
    if not variants:
        prod["_category_key"] = cat_key
        return [prod]

    unrolled = []
    seen_ids = set()

    for v_group in variants:
        options = v_group.get("options") if isinstance(v_group, dict) else [v_group]
        for opt in (options or []):
            sub_prod = opt.get("product") if isinstance(opt, dict) and "product" in opt else opt
            if not isinstance(sub_prod, dict):
                continue

            sub_pk = str(sub_prod.get("pk") or sub_prod.get("id") or sub_prod.get("sku") or "")
            if sub_pk and sub_pk not in seen_ids:
                seen_ids.add(sub_pk)
                item = dict(prod)
                item["pk"] = sub_pk
                item["id"] = sub_pk
                if sub_prod.get("sku"):
                    item["sku"] = sub_prod["sku"]
                if sub_prod.get("name"):
                    item["name"] = sub_prod["name"]
                if sub_prod.get("price"):
                    item["price"] = sub_prod["price"]
                if sub_prod.get("retail_price"):
                    item["retail_price"] = sub_prod["retail_price"]
                item["_category_key"] = cat_key
                unrolled.append(item)

    return unrolled if unrolled else [prod]


def fetch_category(cat_key: str, conf: dict[str, Any]) -> list[dict[str, Any]]:
    cat_id = conf["category_id"]
    url = API_BASE.format(category_id=cat_id)
    print(f"\n[{cat_key}] Extracting from Lulu GCC API (Category ID: {cat_id})...")

    session = requests.Session(impersonate="chrome124")
    session.headers.update(HEADERS)
    session.cookies.update(COOKIES)

    items = []
    seen_keys = set()
    page = 1

    while page <= MAX_PAGES:
        params = {
            "page": page,
            "page_size": PAGE_SIZE,
        }

        try:
            r = session.get(url, params=params, timeout=25)
            if r.status_code in (404, 400):
                break
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  -> Error on page {page}: {e}")
            break

        results = (
            data.get("results")
            or data.get("products")
            or (data.get("data") or {}).get("products")
            or []
        )

        # التوقف عند نهاية المنتجات
        if not results:
            print(f"  -> Reached end of category at page {page}.")
            break

        added_page = 0
        for p in results:
            for unrolled in unroll_lulu_product(p, cat_key):
                uid = str(unrolled.get("pk") or unrolled.get("id") or unrolled.get("sku"))
                if uid and uid not in seen_keys:
                    seen_keys.add(uid)
                    items.append(unrolled)
                    added_page += 1

        print(f"  page {page} | fetched {len(results)} | unrolled & kept {added_page} | total {len(items)}")

        # إذا كانت المنتجات المسترجعة أقل من حجم الصفحة المطلوب، فهذه آخر صفحة
        if len(results) < PAGE_SIZE:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return items


def main():
    print("=== Starting Lulu GCC Bronze Extraction ===")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for cat_key, conf in CATEGORIES.items():
        products = fetch_category(cat_key, conf)
        out_file = OUTPUT_DIR / conf["output_filename"]

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)

        print(f"  ✓ Saved {len(products)} items to: {out_file.name}")

    print("\n=== Lulu Extraction Completed Successfully ===")


if __name__ == "__main__":
    main()