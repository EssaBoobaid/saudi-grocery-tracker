"""BinDawood Silver Cleaning Pipeline (Standardized Canonical Sizing & Guards).

Reads raw items from data/bronze/bindawood/
Outputs standardized schemas to data/silver/bindawood/
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "bindawood"
SILVER_DIR = BASE_DIR / "data" / "silver" / "bindawood"

CATEGORIES = [
    "beverages",
    "dairy_and_eggs",
    "fruits_and_vegetables",
]

# تحويل الأرقام المشرقية/العربية والفواصل العشرية
ARABIC_DIGITS_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")

# توحيد الوحدات إلى المقياس المعتمد (ml / g / pcs / slices / triangles)
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

UNIT_PATTERN = r"(?:milliliter|kilogram|portions?|triangles?|slices?|litre|liter|grams|kilo|pack|cans|can|pcs|ltr|ml|kg|gm|pc|l|g|كيلو|جرام|غرام|كغم|كجم|ملل|لتر|قطع|قطعة|حبات|حبة|علب|علبة|كغ|غم|جم|مل|شريحة|شرائح|مثلث|مثلثات|ل)"


def calculate_ean13_check_digit(digits_12: str) -> str:
    """حساب الرقم الـ 13 الناقص (GS1 Check Digit)."""
    if len(digits_12) != 12 or not digits_12.isdigit():
        return ""
    odd = sum(int(digits_12[i]) for i in range(0, 12, 2))
    even = sum(int(digits_12[i]) for i in range(1, 12, 2))
    total = odd + (even * 3)
    return str((10 - (total % 10)) % 10)


def extract_barcodes_from_image_url(url: str | None) -> list[str]:
    """استخراج وتطبيع الباركود من اسم ملف الصورة."""
    if not url:
        return []

    filename = url.split("?")[0].split("/")[-1]
    match = re.search(r"(?<!\d)(\d{11,14})(?:[_\-\.A-Za-z]|$)", filename)
    if not match:
        return []

    raw_code = match.group(1)
    barcodes = {raw_code}

    if len(raw_code) == 11:
        padded_12 = "0" + raw_code
        barcodes.add(padded_12)
        chk = calculate_ean13_check_digit(padded_12)
        if chk:
            barcodes.add(padded_12 + chk)
    elif len(raw_code) == 12:
        chk = calculate_ean13_check_digit(raw_code)
        if chk:
            barcodes.add(raw_code + chk)
        barcodes.add("0" + raw_code)
    elif len(raw_code) == 13:
        barcodes.add(raw_code)

    return sorted(list(barcodes))


def clean_text_for_parsing(text: str) -> str:
    """تطبيع الفواصل العشرية والأرقام المشرقية والمسافات."""
    t = text.translate(ARABIC_DIGITS_MAP)
    t = re.sub(r"(\d+)[,،](\d+)", r"\1.\2", t)
    return t


def parse_pack_and_size(text: str | None) -> dict[str, Any]:
    """استخراج عدد الحبات والوحدة والحجم بالمقياس الموحد مع دعم الشرائح."""
    empty_res = {
        "pack_qty": 1,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }
    if not text:
        return empty_res

    text = clean_text_for_parsing(text)

    # 0. فحص صيغ الجمع والعروض الترويجية: 8+2 Slices أو 24+4 مثلثات
    plus_pattern = rf"(\d+)\s*\+\s*(\d+)\s*(?:slices?|portions?|شرائح|شريحة|مثلث|مثلثات)"
    m_plus = re.search(plus_pattern, text, flags=re.IGNORECASE)
    if m_plus:
        total_slices = int(m_plus.group(1)) + int(m_plus.group(2))
        return {
            "pack_qty": 1,
            "unit_size_value": float(total_slices),
            "total_size_value": float(total_slices),
            "size_unit": "slices",
        }

    # 1. فحص الشدات والعبوات المتعددة: 18*125ml أو 2*500g
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

    # 2. النمط العكسي: 500g x 2 أو 125ml * 18
    multi_rev = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*[\*xX×\-]\s*(\d+)"
    m_rev = re.search(multi_rev, text, flags=re.IGNORECASE)
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

    # 3. فحص الأحجام الفردية (الأوزان بالجرام والمل)
    single_pattern = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
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

    # 4. فحص العبوات بالعدد فقط (مثل 30 بيضة أو 10 شرائح)
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


def extract_best_price_and_discounts(item: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    default_price = item.get("price")
    default_orig = item.get("original_price")

    best_price = float(default_price) if default_price is not None else None
    best_orig = float(default_orig) if default_orig is not None else None
    max_discount_amount = 0.0

    modifiers = item.get("inventory_modifiers") or {}
    if isinstance(modifiers, dict):
        for mod in modifiers.values():
            if not isinstance(mod, dict):
                continue

            raw_p = mod.get("price")
            raw_orig = mod.get("original_price")

            try:
                cur_price = float(raw_p) if raw_p is not None else None
            except (ValueError, TypeError):
                cur_price = None

            try:
                cur_orig = float(raw_orig) if raw_orig is not None else None
            except (ValueError, TypeError):
                cur_orig = None

            if cur_price is None:
                continue

            cur_disc = 0.0
            if cur_orig and cur_orig > cur_price:
                cur_disc = round(cur_orig - cur_price, 2)

            if cur_disc > max_discount_amount:
                max_discount_amount = cur_disc
                best_price = cur_price
                best_orig = cur_orig
            elif best_price is None or cur_price < best_price:
                best_price = cur_price
                best_orig = cur_orig

    discount_amount = None
    discount_pct = None
    if best_orig and best_price and best_orig > best_price:
        discount_amount = round(best_orig - best_price, 2)
        discount_pct = round((discount_amount / best_orig) * 100, 2)
    elif best_orig and best_price and best_orig == best_price:
        best_orig = None

    return best_price, best_orig, discount_amount, discount_pct


def parse_item(item: dict[str, Any], cat_slug: str) -> dict[str, Any] | None:
    name_en = item.get("full_name_en") or item.get("name_en")
    name_ar = item.get("full_name_ar") or item.get("name_ar")
    full_text = f"{name_en or ''} {name_ar or ''}"

    brand = item.get("brand_en") or item.get("brand_ar")
    if not brand and name_en:
        brand = name_en.split()[0]

    price, orig_price, disc_amt, disc_pct = extract_best_price_and_discounts(item)
    size_data = parse_pack_and_size(full_text)

    # --- 1. حراس أمان المشروبات ---
    if cat_slug == "beverages" and price is not None:
        u_val = size_data.get("unit_size_value")
        p_qty = size_data.get("pack_qty", 1)

        if p_qty == 1 and u_val and u_val <= 500 and price >= 35.0:
            estimated_qty = round(price / 2.5)
            size_data["pack_qty"] = estimated_qty if estimated_qty in [24, 30, 12] else 24
            size_data["total_size_value"] = round(u_val * size_data["pack_qty"], 2)
        elif p_qty == 1 and u_val and u_val <= 250 and price >= 12.0:
            estimated_qty = round(price / 1.8)
            size_data["pack_qty"] = estimated_qty if estimated_qty in [10, 12, 18] else 10
            size_data["total_size_value"] = round(u_val * size_data["pack_qty"], 2)

    # --- 2. حراس أمان الألبان والبيض ---
    if cat_slug == "dairy_and_eggs" and price is not None:
        u_val = size_data.get("unit_size_value")
        p_qty = size_data.get("pack_qty", 1)
        s_unit = size_data.get("size_unit")
        name_lower = full_text.lower()

        # طبق البيض 30 حبة
        if ("egg" in name_lower or "بيض" in name_lower) and s_unit is None and price >= 14.0:
            size_data["pack_qty"] = 30
            size_data["unit_size_value"] = 1.0
            size_data["total_size_value"] = 30.0
            size_data["size_unit"] = "pcs"

        # شرائح الجبن المفقود حجمها
        elif ("slice" in name_lower or "شريحة" in name_lower or "شرائح" in name_lower) and size_data["total_size_value"] is None:
            if price <= 10.0:
                size_data["pack_qty"] = 1
                size_data["unit_size_value"] = 10.0
                size_data["total_size_value"] = 10.0
                size_data["size_unit"] = "slices"
            else:
                size_data["pack_qty"] = 1
                size_data["unit_size_value"] = 20.0
                size_data["total_size_value"] = 20.0
                size_data["size_unit"] = "slices"

        # شدات الزبادي
        elif ("زبادي" in name_lower or "yogurt" in name_lower) and p_qty == 1 and u_val and u_val <= 180 and price >= 7.0:
            size_data["pack_qty"] = 6
            size_data["total_size_value"] = round(u_val * 6, 2)

    image_url = item.get("image") or ""
    barcodes = extract_barcodes_from_image_url(image_url)

    for extra_code in (item.get("barcodes") or []):
        c_str = str(extra_code).strip()
        if c_str and c_str not in barcodes:
            barcodes.append(c_str)

    return {
        "id": str(item.get("master_id") or item.get("objectID")),
        "store": "bindawood",
        "category": cat_slug,
        "name_en": name_en.strip() if name_en else None,
        "name_ar": name_ar.strip() if name_ar else None,
        "brand": brand,
        "barcodes": sorted(barcodes),
        "price": price,
        "original_price": orig_price,
        "discount_amount": disc_amt,
        "discount_percentage": disc_pct,
        "pack_qty": size_data["pack_qty"],
        "unit_size_value": size_data["unit_size_value"],
        "total_size_value": size_data["total_size_value"],
        "size_unit": size_data["size_unit"],
        "image_url": image_url if image_url else None,
    }


def main():
    print("=== [BinDawood] Starting Silver Clean Pipeline (Dairy-Enhanced) ===")
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    for cat in CATEGORIES:
        bronze_file = BRONZE_DIR / f"{cat}_raw.json"
        if not bronze_file.exists():
            continue

        with open(bronze_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        cleaned, seen_ids = [], set()
        barcode_hits, discount_hits, size_hits = 0, 0, 0

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