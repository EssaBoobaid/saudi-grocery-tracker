from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any

from matching_utils import GOLD_DIR, load_silver_category
from match_beverages import run_beverages_matching
from match_dairy_and_eggs import run_dairy_and_eggs_matching
from match_fruits_and_vegetables import run_fruits_and_vegetables_matching

ENGINES = [
    ("beverages", "beverages_clean.json", run_beverages_matching),
    ("dairy_and_eggs", "dairy_and_eggs_clean.json", run_dairy_and_eggs_matching),
    ("fruits_and_vegetables", "fruits_and_vegetables_clean.json", run_fruits_and_vegetables_matching),
]

def main():
    print("=== Running Modular Gold Matchers Pipeline ===")
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    all_unified = []
    stats = []

    for slug, filename, engine_func in ENGINES:
        products = load_silver_category(filename)
        if not products:
            continue

        raw_clusters = engine_func(products)
        three_cnt, two_cnt = 0, 0
        two_breakdown = defaultdict(int)
        cat_clusters = []

        for c in raw_clusters:
            prods = c["products"]
            stores = sorted(list({x["store"] for x in prods}))
            cnt = len(stores)

            if cnt == 3:
                three_cnt += 1
            elif cnt == 2:
                two_cnt += 1
                two_breakdown[" + ".join(stores)] += 1

            ref = next((x for x in prods if x.get("name_ar")), prods[0])
            entry = {
                "category": slug,
                "match_tier": c["tier"],
                "confidence_score": c["confidence"],
                "matched_stores_count": cnt,
                "stores": stores,
                "common_name_en": ref.get("name_en"),
                "common_name_ar": ref.get("name_ar"),
                "brand": ref.get("brand"),
                "size_value": ref.get("size_value"),
                "size_unit": ref.get("size_unit"),
                "prices": {x["store"]: x.get("price") for x in prods},
                "products": prods,
            }
            cat_clusters.append(entry)
            all_unified.append(entry)

        matched_prods = sum(len(c["products"]) for c in cat_clusters)
        stats.append({
            "category": slug,
            "total": len(products),
            "matched": matched_prods,
            "three_stores": three_cnt,
            "two_stores": two_cnt,
            "two_breakdown": dict(two_breakdown),
            "pct": round((matched_prods / len(products) * 100), 2) if products else 0
        })

    # حفظ الملفات
    with open(GOLD_DIR / "matched_products.json", "w", encoding="utf-8") as f:
        json.dump(all_unified, f, ensure_ascii=False, indent=2)

    three_stores_only = [x for x in all_unified if x["matched_stores_count"] == 3]
    with open(GOLD_DIR / "matched_in_all_three_stores.json", "w", encoding="utf-8") as f:
        json.dump(three_stores_only, f, ensure_ascii=False, indent=2)

    # التقرير
    print("\n" + "=" * 75)
    print("                    تقرير نتائج الأقسام المكتملة")
    print("=" * 75)
    for s in stats:
        print(f"\n📁 القسم: {s['category'].upper()}")
        print(f"   • إجمالي المنتجات : {s['total']}")
        print(f"   • متطابقة بالـ 3 متاجر: {s['three_stores']} مجموعة")
        print(f"   • متطابقة بمتجرين فقط  : {s['two_stores']} مجموعة:")
        for pair, count in s["two_breakdown"].items():
            print(f"       └─ {pair}: {count}")
        print(f"   • نسبة المطابقة   : {s['pct']}%")
    print("=" * 75)

if __name__ == "__main__":
    main()