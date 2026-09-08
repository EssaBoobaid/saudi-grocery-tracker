"""BinDawood Algolia Ingestion Pipeline.

Extracts targeted FMCG categories and saves them into the Bronze layer:
data/bronze/bindawood/
  - beverages_raw.json
  - dairy_and_eggs_raw.json
  - fruits_and_vegetables_raw.json
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from urllib.parse import urlencode
import requests

ALGOLIA_APP_ID = "KBGHG5MR5E"
ALGOLIA_API_KEY = "8c6b85b7bdebb06d260ccde6b810884b"
INDEX_NAME = "spree_products"

# إضافة اسم ملف التخزين المقابل لكل فئة في البرونز
TARGET_CATEGORIES = [
    {
        "name": "Beverages & Water",
        "output_filename": "beverages_raw.json",
        "facet_candidates": [
            "الأقسام > الماء و المشروبات",
            "الأقسام > الماء والمشروبات",
        ],
    },
    {
        "name": "Dairy & Eggs",
        "output_filename": "dairy_and_eggs_raw.json",
        "facet_candidates": [
            "الأقسام > الألبان و البيض",
            "الأقسام > الألبان والبيض",
            "الأقسام > منتجات الألبان والبيض",
        ],
    },
    {
        "name": "Fresh Fruits & Veg",
        "output_filename": "fruits_and_vegetables_raw.json",
        "facet_candidates": [
            "الأقسام > فواكه و خضروات طازجة",
            "الأقسام > فواكه وخضروات طازجة",
            "الأقسام > خضار وفواكه طازجة",
        ],
    },
]

HEADERS = {
    "Origin": "https://www.bindawood.sa",
    "Referer": "https://www.bindawood.sa/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json",
}

HITS_PER_PAGE = 100
MAX_PAGES = 10

# المسار الديناميكي لجذر المشروع (يرجع درجتين للخلف: src/bronze -> src -> root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "bronze" / "bindawood"


def fetch_category_hits(cat_meta: dict) -> list[dict]:
    url = (
        f"https://{ALGOLIA_APP_ID.lower()}-dsn.algolia.net/1/indexes/*/queries?"
        f"x-algolia-application-id={ALGOLIA_APP_ID}&x-algolia-api-key={ALGOLIA_API_KEY}"
    )

    cat_name = cat_meta["name"]
    working_facet = None

    # 1. فحص الفلتر النصي المطابق فعلياً داخل الفهرس
    for candidate in cat_meta["facet_candidates"]:
        probe_params = {
            "query": "",
            "hitsPerPage": 1,
            "page": 0,
            "filters": "tenant_id = 2",
            "facetFilters": json.dumps([[f"taxons_ar.lvl1:{candidate}"]]),
        }
        probe_payload = {"requests": [{"indexName": INDEX_NAME, "params": urlencode(probe_params)}]}
        try:
            r = requests.post(url, headers=HEADERS, json=probe_payload, timeout=15)
            hits = r.json().get("results", [])[0].get("hits", [])
            if hits:
                working_facet = candidate
                print(f"[{cat_name}] Matched Facet -> '{candidate}'")
                break
        except Exception:
            continue

    if not working_facet:
        print(f"[{cat_name}] ⚠️ No matching facet found among candidates. Skipping.")
        return []

    # 2. سحب كافة الصفحات للفئة المطابقة
    category_items = []
    seen_ids = set()

    for page in range(MAX_PAGES):
        params_dict = {
            "query": "",
            "hitsPerPage": HITS_PER_PAGE,
            "page": page,
            "filters": "tenant_id = 2",
            "facetFilters": json.dumps([[f"taxons_ar.lvl1:{working_facet}"]]),
        }
        payload = {"requests": [{"indexName": INDEX_NAME, "params": urlencode(params_dict)}]}

        try:
            res = requests.post(url, headers=HEADERS, json=payload, timeout=20)
            if res.status_code != 200:
                break

            result = res.json().get("results", [])[0]
            hits = result.get("hits", [])
            if not hits:
                break

            for h in hits:
                obj_id = h.get("objectID") or h.get("master_id")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    h["_category_name"] = cat_name
                    category_items.append(h)

            nb_pages = result.get("nbPages", 1)
            print(f"  -> Page {page + 1}/{nb_pages}: Retrieved {len(hits)} items.")

            if page + 1 >= nb_pages:
                break

            time.sleep(0.3)
        except Exception as e:
            print(f"  -> Error fetching page {page}: {e}")
            break

    return category_items


def main():
    print("=== Starting BinDawood Extraction Pipeline ===")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for category in TARGET_CATEGORIES:
        print(f"\nProcessing Category: {category['name']}...")
        items = fetch_category_hits(category)
        
        file_path = OUTPUT_DIR / category["output_filename"]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

        print(f"  ✓ Saved {len(items)} items to: {file_path}")

    print("\n=== BinDawood Extraction Completed Successfully ===")


if __name__ == "__main__":
    main()