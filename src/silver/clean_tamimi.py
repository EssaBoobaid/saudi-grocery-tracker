"""Tamimi Markets Silver Cleaning Pipeline (Unified Clean Schema & Pack Sizes).

Cleans raw Tamimi items from data/bronze/tamimi/
and writes standardized schemas to data/silver/tamimi/
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "tamimi"
SILVER_DIR = BASE_DIR / "data" / "silver" / "tamimi"

CATEGORIES = [
    "beverages",
    "dairy_and_eggs",
    "fruits_and_vegetables",
]

ARABIC_DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

UNIT_MULTIPLIERS = {
    "l": ("ml", 1000.0),
    "ltr": ("ml", 1000.0),
    "litre": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "لتر": ("ml", 1000.0),
    "ل": ("ml", 1000.0),
    "ml": ("ml", 1.0),
    "milliliter": ("ml", 1.0),
    "مل": ("ml", 1.0),
    "ملل": ("ml", 1.0),
    "kg": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "kilogram": ("g", 1000.0),
    "كيلو": ("g", 1000.0),
    "كجم": ("g", 1000.0),
    "كغ": ("g", 1000.0),
    "g": ("g", 1.0),
    "gram": ("g", 1.0),
    "grams": ("g", 1.0),
    "غرام": ("g", 1.0),
    "جرام": ("g", 1.0),
    "غم": ("g", 1.0),
    "جم": ("g", 1.0),
}

UNIT_PATTERN = r"(?:ml|milliliter|liter|litre|ltr|l|kg|kilo|kilogram|g|gram|grams|مل|ملل|لتر|ل|غم|جم|غرام|جرام|كغم|كيلو)"


def parse_pack_and_size(text: str | None) -> dict[str, Any]:
    """استخراج عدد الحبات والوزن الفردي والحجم الإجمالي الفعلي."""
    empty_res = {
        "pack_qty": 1,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }
    if not text:
        return empty_res

    text = text.translate(ARABIC_DIGITS_MAP)

    # 1. صيغة الضرب والشدات: 48 * 200 ml أو 4x250ml
    multi_pattern = rf"(\d+)\s*[\*xX×]\s*(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
    m_multi = re.search(multi_pattern, text, flags=re.IGNORECASE)
    if m_multi:
        qty = int(m_multi.group(1))
        val = float(m_multi.group(2))
        u_raw = m_multi.group(3).lower()
        std_unit, mult = UNIT_MULTIPLIERS.get(u_raw, (u_raw, 1.0))
        unit_val = round(val * mult, 2)
        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": round(unit_val * qty, 2),
            "size_unit": std_unit,
        }

    # 2. صيغ الأحجام المفردة: 250 ML أو 1.5 L
    single_pattern = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\b"
    m_single = re.search(single_pattern, text, flags=re.IGNORECASE)
    if m_single:
        val = float(m_single.group(1))
        u_raw = m_single.group(2).lower()
        std_unit, mult = UNIT_MULTIPLIERS.get(u_raw, (u_raw, 1.0))
        unit_val = round(val * mult, 2)

        qty_pattern = r"(\d+)\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|قارورة|قوارير|كيس|صحن)\b"
        m_qty = re.search(qty_pattern, text, flags=re.IGNORECASE)
        qty = int(m_qty.group(1)) if m_qty else 1

        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": round(unit_val * qty, 2),
            "size_unit": std_unit,
        }

    # 3. عبوات بالعدد فقط بدون وحدة قياس (مثل 30 حبة أو 6 بيضات)
    count_pattern = r"(\d+)\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|بيض|بيضة)\b"
    m_count = re.search(count_pattern, text, flags=re.IGNORECASE)
    if m_count:
        qty = int(m_count.group(1))
        return {
            "pack_qty": qty,
            "unit_size_value": 1.0,
            "total_size_value": float(qty),
            "size_unit": "pcs",
        }

    return empty_res


def extract_tamimi_barcodes(variant: dict[str, Any]) -> list[str]:
    barcodes = set()
    raw_codes = variant.get("barcodes") or []
    for code in raw_codes:
        c = str(code).strip()
        if c:
            barcodes.add(c)
            c_clean = c.lstrip("0")
            if len(c_clean) >= 7:
                barcodes.add(c_clean)
    return sorted(barcodes)


def parse_item(item: dict[str, Any], cat_slug: str) -> dict[str, Any] | None:
    # قراءة الفارينت المفرز أو من القائمة
    v = item.get("variant")
    if not v and (item.get("variants") or []):
        v = item["variants"][0]
    if not isinstance(v, dict):
        v = {}

    name_en = v.get("fullName") or item.get("name")
    if not name_en:
        return None

    # دمج نص الفارينت مع اسم المنتج العام لضمان التقاط الحجم كاملاً
    full_text = f"{name_en} {v.get('name', '')}"

    brand_obj = item.get("brand") or {}
    brand = brand_obj.get("name") if isinstance(brand_obj, dict) else None

    # استخراج السعر والخصومات
    price = None
    original_price = None
    discount_amount = None
    discount_pct = None

    store_data = v.get("storeSpecificData") or []
    if store_data and isinstance(store_data, list):
        primary = store_data[0]
        try:
            mrp = float(primary.get("mrp") or 0)
            disc = float(primary.get("discount") or 0)
            if mrp > 0:
                price = round(mrp - disc, 2)
                if disc > 0:
                    original_price = round(mrp, 2)
                    discount_amount = round(disc, 2)
                    discount_pct = round((disc / mrp) * 100, 2)
        except (ValueError, TypeError):
            pass

    size_data = parse_pack_and_size(full_text)
    barcodes = extract_tamimi_barcodes(v)

    images = v.get("images") or []
    image_url = images[0] if images and isinstance(images, list) else None
    variant_id = str(v.get("id") or item.get("id"))

    return {
        "id": variant_id,
        "store": "tamimi",
        "category": cat_slug,
        "name_en": name_en.strip(),
        "name_ar": None,
        "brand": brand,
        "barcodes": barcodes,
        "price": price,
        "original_price": original_price,
        "discount_amount": discount_amount,
        "discount_percentage": discount_pct,
        "pack_qty": size_data["pack_qty"],
        "unit_size_value": size_data["unit_size_value"],
        "total_size_value": size_data["total_size_value"],
        "size_unit": size_data["size_unit"],
        "image_url": image_url,
    }


def main():
    print("=== [Tamimi] Starting Silver Clean Pipeline (Pack & Multi-Unit) ===")
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    for cat in CATEGORIES:
        bronze_file = BRONZE_DIR / f"{cat}_raw.json"
        if not bronze_file.exists():
            continue

        with open(bronze_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        cleaned, seen_ids = [], set()
        barcode_hits = 0
        discount_hits = 0
        size_hits = 0

        for raw_item in raw_data:
            parsed = parse_item(raw_item, cat)
            if parsed and parsed["id"] not in seen_ids:
                seen_ids.add(parsed["id"])
                if parsed["barcodes"]:
                    barcode_hits += 1
                if parsed["discount_amount"]:
                    discount_hits += 1
                if parsed["total_size_value"]:
                    size_hits += 1
                cleaned.append(parsed)

        out_file = SILVER_DIR / f"{cat}_clean.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)

        print(
            f"  ✓ Cleaned {len(cleaned)} products "
            f"(Sizes: {size_hits} | Barcodes: {barcode_hits} | Deals: {discount_hits}) -> {out_file.name}"
        )


if __name__ == "__main__":
    main()