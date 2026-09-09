"""Tamimi Bronze Normalizer.

Transforms nested API payload structure (variants: [...])
into the flattened legacy bronze schema (variant: {...})
matching the expected Silver ingestion contract.
"""

from __future__ import annotations

import json
from typing import Any

from config.settings import BRONZE_TAMIMI

FILES_TO_CONVERT = [
    "fruits_and_vegetables_raw.json",
    "dairy_and_eggs_raw.json",
    "beverages_raw.json",
]


def flatten_product_variants(raw_products: list[dict[str, Any]], category_key: str) -> list[dict[str, Any]]:
    flattened_records = []

    for item in raw_products:
        if not isinstance(item, dict):
            continue

        # استخراج مصفوفة المتغيرات (الأوزان / الأحجام)
        variants = item.get("variants") or []

        # إذا كان العنصر مسطحاً مسبقاً (يحتوي على variant مفرد)، يتم الإبقاء عليه
        if "variant" in item and not variants:
            item["_category_key"] = category_key
            flattened_records.append(item)
            continue

        # الحقول الأساسية المشتركة للمنتج الأب
        base_product = {
            "id": item.get("id"),
            "name": item.get("name"),
            "slug": item.get("slug"),
            "brand": item.get("brand"),
            "primaryCategory": item.get("primaryCategory"),
            "_category_key": category_key,
        }

        # إنشاء سجل مستقل لكل متغير مطابق لنمط البيانات التاريخية
        for var in variants:
            if not isinstance(var, dict):
                continue

            record = dict(base_product)
            record["variant"] = var
            flattened_records.append(record)

    return flattened_records


def main():
    print("=" * 65)
    print("🔄 NORMALIZING TAMIMI BRONZE SCHEMAS")
    print("=" * 65)

    for filename in FILES_TO_CONVERT:
        file_path = BRONZE_TAMIMI / filename
        if not file_path.exists():
            print(f"[!] File not found: {filename}, skipping.")
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            try:
                raw_data = json.load(f)
            except json.JSONDecodeError as err:
                print(f"[!] Error reading {filename}: {err}")
                continue

        category_key = filename.replace("_raw.json", "")
        normalized_records = flatten_product_variants(raw_data, category_key)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(normalized_records, f, ensure_ascii=False, indent=2)

        print(f"✓ Converted {file_path.name}:")
        print(f"   Root items: {len(raw_data)} ➔ Flattened records: {len(normalized_records)}\n")

    print("=" * 65)
    print("✅ BRONZE FILES STANDARDIZED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    main()