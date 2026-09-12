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

ARABIC_DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")

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
    "كغم": ("g", 1000.0),
    "g": ("g", 1.0),
    "gram": ("g", 1.0),
    "grams": ("g", 1.0),
    "غرام": ("g", 1.0),
    "جرام": ("g", 1.0),
    "غم": ("g", 1.0),
    "جم": ("g", 1.0),
    "slice": ("slices", 1.0),
    "slices": ("slices", 1.0),
    "شريحة": ("slices", 1.0),
    "شرائح": ("slices", 1.0),
    "portion": ("triangles", 1.0),
    "portions": ("triangles", 1.0),
    "مثلث": ("triangles", 1.0),
    "مثلثات": ("triangles", 1.0),
    "pc": ("pcs", 1.0),
    "pcs": ("pcs", 1.0),
    "pack": ("pcs", 1.0),
    "can": ("pcs", 1.0),
    "cans": ("pcs", 1.0),
    "حبة": ("pcs", 1.0),
    "حبات": ("pcs", 1.0),
    "قطعة": ("pcs", 1.0),
    "قطع": ("pcs", 1.0),
    "علبة": ("pcs", 1.0),
    "علب": ("pcs", 1.0),
    "count": ("pcs", 1.0),
    "counts": ("pcs", 1.0),
}

UNIT_PATTERN = r"(?:milliliter|kilogram|portions?|triangles?|slices?|liter|litre|ltr|grams?|kilo|pack|cans|can|pcs|ml|kg|gm|pc|l|g|كيلو|جرام|غرام|كغم|كجم|ملل|لتر|قطع|قطعة|حبات|حبة|علب|علبة|كغ|غم|جم|مل|شريحة|شرائح|مثلث|مثلثات|ل|counts?|count)"


def parse_pack_and_size(text: str | None) -> dict[str, Any]:
    """استخراج عدد الحبات والوزن الفردي والحجم الإجمالي الفعلي بدقة أعلى للألبان والعصائر."""
    empty_res = {
        "pack_qty": 1,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }
    if not text:
        return empty_res

    text = text.translate(ARABIC_DIGITS_MAP)
    text = re.sub(r"(\d+)[,،](\d+)", r"\1.\2", text)

    # Fix obvious source-data unit typo:
    # Example: 1500Kg on a retail grocery product
    # is clearly intended as 1500g, not 1,500,000g.
    def fix_impossible_kg(match):
        value = float(match.group(1))

        if value >= 100:
            return f"{match.group(1)} G"

        return match.group(0)

    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*(kg|kilogram|kilo)\b",
        fix_impossible_kg,
        text,
        flags=re.IGNORECASE,
    )

    
        # 0A. Multipack with size range:
    # 6 X 250-300 ML
    # 18 X 330-355 ML
    multi_range_pattern = (
        rf"(\d+)\s*[\*xX×]\s*"
        rf"(\d+(?:\.\d+)?)\s*-\s*"
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
    )

    m_multi_range = re.search(
        multi_range_pattern,
        text,
        flags=re.IGNORECASE,
    )

    if m_multi_range:
        qty = int(m_multi_range.group(1))
        max_val = float(m_multi_range.group(3))
        u_raw = m_multi_range.group(4).lower()

        std_unit, mult = UNIT_MULTIPLIERS.get(
            u_raw,
            (u_raw, 1.0),
        )

        unit_val = round(max_val * mult, 2)

        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": round(unit_val * qty, 2),
            "size_unit": std_unit,
        }

    # 0B. Single product with size range:
    # 250-300 ML
    # 375-400 G
    range_pattern = (
        rf"(\d+(?:\.\d+)?)\s*-\s*"
        rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
    )

    m_range = re.search(
        range_pattern,
        text,
        flags=re.IGNORECASE,
    )

    if m_range:
        max_val = float(m_range.group(2))
        u_raw = m_range.group(3).lower()

        std_unit, mult = UNIT_MULTIPLIERS.get(
            u_raw,
            (u_raw, 1.0),
        )

        unit_val = round(max_val * mult, 2)

        return {
            "pack_qty": 1,
            "unit_size_value": unit_val,
            "total_size_value": unit_val,
            "size_unit": std_unit,
        }

        # Count + total weight:
    # 24 Portions-336 G
    # 12 Slices-200 G
    count_total_weight_pattern = (
        rf"(\d+)\s*"
        rf"(?:portions?|triangles?|slices?|"
        rf"حبة|حبات|قطعة|قطع|شريحة|شرائح|مثلث|مثلثات)"
        rf"\s*[-–]?\s*"
        rf"(\d+(?:\.\d+)?)\s*"
        rf"(g|gm|gram|grams|kg|ml|l|ltr|litre|liter|"
        rf"جرام|غرام|جم|غم|كجم|كغ|مل|لتر)"
    )

    m_count_weight = re.search(
        count_total_weight_pattern,
        text,
        flags=re.IGNORECASE,
    )

    if m_count_weight:
        qty = int(m_count_weight.group(1))
        total_raw = float(m_count_weight.group(2))
        u_raw = m_count_weight.group(3).lower()

        std_unit, mult = UNIT_MULTIPLIERS.get(
            u_raw,
            (u_raw, 1.0),
        )

        total_val = round(total_raw * mult, 2)
        unit_val = round(total_val / qty, 2)

        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": total_val,
            "size_unit": std_unit,
        }

        # Tamimi abbreviated weight formats:
    # 2K / 1.8K = kilograms
    # 3Z / 8Oz = ounces

    short_kg = re.search(
        r"(\d+(?:\.\d+)?)\s*K\b",
        text,
        flags=re.IGNORECASE,
    )

    if short_kg:
        value = float(short_kg.group(1))
        total_g = round(value * 1000.0, 2)

        return {
            "pack_qty": 1,
            "unit_size_value": total_g,
            "total_size_value": total_g,
            "size_unit": "g",
        }

    short_oz = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:OZ|Z)\b",
        text,
        flags=re.IGNORECASE,
    )

    if short_oz:
        value = float(short_oz.group(1))
        total_g = round(value * 28.3495, 2)

        return {
            "pack_qty": 1,
            "unit_size_value": total_g,
            "total_size_value": total_g,
            "size_unit": "g",
        }

    # 0. فحص عروض الجمع الترويجية: 8+2 Slices أو 24+4
    plus_pattern = rf"(\d+)\s*\+\s*(\d+)\s*(?:slices?|portions?|شرائح|شريحة|مثلث|مثلثات)"
    m_plus = re.search(plus_pattern, text, flags=re.IGNORECASE)
    if m_plus:
        total_cnt = int(m_plus.group(1)) + int(m_plus.group(2))
        return {
            "pack_qty": 1,
            "unit_size_value": float(total_cnt),
            "total_size_value": float(total_cnt),
            "size_unit": "slices",
        }

    # 1. صيغة الضرب والشدات: 10 X 200 ML أو 2*500g أو 24*330ml
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

    # 2. صيغة الضرب العكسية: 500g x 2 أو 200ml x 10
    multi_reverse_pattern = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*[\*xX×]\s*(\d+)"
    m_rev = re.search(multi_reverse_pattern, text, flags=re.IGNORECASE)
    if m_rev:
        val = float(m_rev.group(1))
        u_raw = m_rev.group(2).lower()
        qty = int(m_rev.group(3))
        std_unit, mult = UNIT_MULTIPLIERS.get(u_raw, (u_raw, 1.0))
        unit_val = round(val * mult, 2)
        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": round(unit_val * qty, 2),
            "size_unit": std_unit,
        }

    # 3. صيغ الأحجام المفردة
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

    # 4. عبوات بالعدد فقط (بيض، شرائح، مثلثات)
    count_pattern = r"(\d+)\s*(?:counts?|حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|بيض|بيضة|slices?|شرائح|شريحة)\b"
    m_count = re.search(count_pattern, text, flags=re.IGNORECASE)
    if m_count:
        qty = int(m_count.group(1))
        return {
            "pack_qty": 1,
            "unit_size_value": float(qty),
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
    v = item.get("variant")
    if not v and (item.get("variants") or []):
        v = item["variants"][0]
    if not isinstance(v, dict):
        v = {}

    name_en = v.get("fullName") or item.get("name")
    if not name_en:
        return None

    full_text = f"{name_en} {v.get('name', '')}"
    full_lower = full_text.lower()

    brand_obj = item.get("brand") or {}
    brand = brand_obj.get("name") if isinstance(brand_obj, dict) else None

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
    print("=== [Tamimi] Starting Silver Clean Pipeline (Dairy-Enhanced) ===")
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