"""Lulu Hypermarket Silver Cleaning Pipeline (Unified Clean Schema & Pack Sizes).

Cleans raw Lulu GCC items from data/bronze/lulu/
and writes standardized schemas to data/silver/lulu/
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "lulu"
SILVER_DIR = BASE_DIR / "data" / "silver" / "lulu"

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
}

UNIT_PATTERN = r"(?:milliliter|kilogram|portions?|triangles?|slices?|liter|litre|ltr|grams?|kilo|pack|cans|can|pcs|ml|kg|gm|pc|l|g|كيلو|جرام|غرام|كغم|كجم|ملل|لتر|قطع|قطعة|حبات|حبة|علب|علبة|كغ|غم|جم|مل|شريحة|شرائح|مثلث|مثلثات|ل)"


def parse_pack_and_size(text: str | None, default_qty: int = 1) -> dict[str, Any]:
    """استخراج عدد الحبات والوزن الفردي والحجم الإجمالي الفعلي بدقة للألبان والعصائر."""
    empty_res = {
        "pack_qty": default_qty,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }
    if not text:
        return empty_res

    text = text.translate(ARABIC_DIGITS_MAP)
    text = re.sub(r"(\d+)[,،](\d+)", r"\1.\2", text)

    # 0. صيغ العروض الترويجية والجمع: 8+2 Slices أو 24+4 مثلثات
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

    # 1. صيغة الضرب والشدات العادية: 10 x 200 ml أو 2*500g أو 24*330ml
    multi_pattern = rf"(\d+)\s*[\*xX×\-]\s*(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
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

    # 2. صيغة الضرب العكسية (شائعة جداً في لولو): 200 مل × 10 أو 500g x 2
    multi_reverse = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*[\*xX×\-]\s*(\d+)"
    m_rev = re.search(multi_reverse, text, flags=re.IGNORECASE)
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

        qty = default_qty
        if qty == 1:
            qty_pattern = r"(\d+)\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|قارورة|قوارير|كيس|صحن)\b"
            m_qty = re.search(qty_pattern, text, flags=re.IGNORECASE)
            if m_qty:
                qty = int(m_qty.group(1))

        return {
            "pack_qty": qty,
            "unit_size_value": unit_val,
            "total_size_value": round(unit_val * qty, 2),
            "size_unit": std_unit,
        }

    # 4. عبوات بالعدد فقط (بيض، شرائح، مثلثات)
    count_pattern = r"(\d+)\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|بيض|بيضة|slices?|شرائح|شريحة)\b"
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


def extract_lulu_barcodes(attrs: dict[str, Any]) -> list[str]:
    barcodes = set()
    for key in ["main_ean", "lulu_ean", "ean"]:
        val = attrs.get(key)
        if not val:
            continue
        for code in str(val).split(","):
            c = code.strip()
            if c:
                barcodes.add(c)
                c_clean = c.lstrip("0")
                if len(c_clean) >= 8:
                    barcodes.add(c_clean)
    return sorted(barcodes)


def parse_item(item: dict[str, Any], cat_slug: str) -> dict[str, Any] | None:
    attrs = item.get("attributes") or {}

    name_ar = item.get("name") or attrs.get("product_name_ar") or attrs.get("l_name")
    name_en = attrs.get("product_name") or attrs.get("Description") or attrs.get("product_title")
    if not name_en and not name_ar:
        name_en = item.get("name")

    brand = (
        attrs.get("brand")
        or (item.get("attributes_kwargs", {}).get("brand", {}) or {}).get("value")
        or (item.get("brand") or {}).get("name")
    )
    if brand and str(brand).lower() == "fresh":
        brand = None

    price = None
    try:
        if item.get("price") is not None:
            price = round(float(item["price"]), 2)
    except (ValueError, TypeError):
        pass

    original_price = None
    try:
        if item.get("retail_price") is not None:
            original_price = round(float(item["retail_price"]), 2)
    except (ValueError, TypeError):
        pass

    discount_amount = None
    discount_pct = None
    if original_price and price and original_price > price:
        discount_amount = round(original_price - price, 2)
        discount_pct = round((discount_amount / original_price) * 100, 2)
    elif original_price and price and original_price == price:
        original_price = None

    default_pack_qty = 1
    conv = attrs.get("convtobuom")
    if conv:
        try:
            default_pack_qty = max(1, int(float(conv)))
        except (ValueError, TypeError):
            pass

    size_ar = parse_pack_and_size(name_ar, default_qty=default_pack_qty) if name_ar else None
    size_en = parse_pack_and_size(name_en, default_qty=default_pack_qty) if name_en else None

    # اختيار الحجم الأكثر تفصيلاً
    if size_ar and size_ar.get("unit_size_value"):
        size_data = size_ar
        if size_en and size_en.get("pack_qty", 1) > 1 and size_ar.get("pack_qty", 1) == 1:
            if price is not None and price >= 12.0:
                size_data = size_en
    elif size_en and size_en.get("unit_size_value"):
        size_data = size_en
    else:
        full_text = f"{name_en or ''} {name_ar or ''} {attrs.get('content', '')}"
        size_data = parse_pack_and_size(full_text, default_qty=default_pack_qty)

    full_check_text = f"{name_en or ''} {name_ar or ''}".lower()

    # --- 1. حراس أمان المشروبات ---
    if cat_slug == "beverages" and price is not None:
        u_val = size_data.get("unit_size_value")
        p_qty = size_data.get("pack_qty", 1)

        if price < 12.0 and p_qty > 1:
            size_data["pack_qty"] = 1
            if u_val:
                size_data["total_size_value"] = u_val
        elif p_qty == 1 and u_val and u_val <= 250 and price >= 12.0:
            estimated_qty = round(price / 1.8)
            size_data["pack_qty"] = estimated_qty if estimated_qty in [10, 12, 18] else 10
            size_data["total_size_value"] = round(u_val * size_data["pack_qty"], 2)
        elif p_qty == 1 and u_val and u_val <= 500 and price >= 35.0:
            estimated_qty = round(price / 2.5)
            size_data["pack_qty"] = estimated_qty if estimated_qty in [24, 30, 12] else 24
            size_data["total_size_value"] = round(u_val * size_data["pack_qty"], 2)

    # --- 2. حراس أمان الألبان والبيض في لولو ---
    if cat_slug == "dairy_and_eggs" and price is not None:
        u_val = size_data.get("unit_size_value")
        p_qty = size_data.get("pack_qty", 1)
        s_unit = size_data.get("size_unit")

        # طبق البيض 30 حبة
        if ("egg" in full_check_text or "بيض" in full_check_text) and s_unit is None and price >= 14.0:
            size_data["pack_qty"] = 30
            size_data["unit_size_value"] = 1.0
            size_data["total_size_value"] = 30.0
            size_data["size_unit"] = "pcs"

        # عبوات شرائح الجبن (المراعي/كرافت/برايد) إذا فُقد حجمها
        elif ("slice" in full_check_text or "شريحة" in full_check_text or "شرائح" in full_check_text) and size_data["total_size_value"] is None:
            if price <= 10.0:
                size_data["pack_qty"] = 1
                size_data["unit_size_value"] = 10.0
                size_data["total_size_value"] = 10.0
                size_data["size_unit"] = "slices"
            else:
                size_data["pack_qty"] = 1
                size_data["unit_size_value"] = 400.0
                size_data["total_size_value"] = 400.0
                size_data["size_unit"] = "g"

        # كراتين/شدات الزبادي
        elif ("زبادي" in full_check_text or "yogurt" in full_check_text) and p_qty == 1 and u_val and u_val <= 180 and price >= 7.0:
            size_data["pack_qty"] = 6
            size_data["total_size_value"] = round(u_val * 6, 2)

    barcodes = extract_lulu_barcodes(attrs)

    images = item.get("productimage_set") or item.get("images") or []
    image_url = None
    if images and isinstance(images, list):
        first = images[0]
        image_url = first.get("image") if isinstance(first, dict) else str(first)

    uid = str(item.get("pk") or item.get("sku") or item.get("id"))

    return {
        "id": uid,
        "store": "lulu",
        "category": cat_slug,
        "name_en": name_en.strip() if name_en else None,
        "name_ar": name_ar.strip() if name_ar else None,
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
    print("=== [Lulu] Starting Silver Clean Pipeline (Dairy-Enhanced) ===")
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