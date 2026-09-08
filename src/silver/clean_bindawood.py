"""BinDawood Silver Cleaning Pipeline (Best Store Discounts & Canonical Sizing).

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

# توحيد مسميات الوحدات مع الحفاظ على مقياسها الطبيعي المقروء
CANONICAL_UNITS = {
    # وحدات الحجم والسوائل
    "l": "L", "ltr": "L", "litre": "L", "liter": "L", "لتر": "L", "ل": "L",
    "ml": "ml", "milliliter": "ml", "مل": "ml", "ملل": "ml",
    
    # وحدات الوزن
    "kg": "kg", "kilo": "kg", "kilogram": "kg", "كيلو": "kg", "كجم": "kg", "كغ": "kg", "كغم": "kg",
    "g": "g", "gram": "g", "grams": "g", "غرام": "g", "جرام": "g", "غم": "g", "جم": "g",
    
    # وحدات العدد
    "pcs": "pcs", "pc": "pcs", "حبة": "pcs", "حبات": "pcs", "قطع": "pcs", "قطعة": "pcs",
}

UNIT_PATTERN = r"(?:milliliter|kilogram|litre|liter|grams|kilo|pack|cans|pack|can|pcs|ltr|ltr|ml|kg|gm|pc|l|g|كيلو|جرام|غرام|كغم|كجم|ملل|لتر|قطع|قطعة|حبات|حبة|علب|علبة|كغ|غم|جم|مل|ل)"


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
    # استبدال الفواصل بين الأرقام بنقطة عشرية (مثل 1,3 -> 1.3)
    t = re.sub(r"(\d+)[,،](\d+)", r"\1.\2", t)
    return t


def parse_pack_and_size(text: str | None) -> dict[str, Any]:
    """استخراج عدد الحبات والوحدة الطبيعية والحجم بدقة عالية."""
    empty_res = {
        "pack_qty": 1,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }
    if not text:
        return empty_res

    text = clean_text_for_parsing(text)

    # 1. فحص الشدات والعبوات المتعددة: 48 * 200 مل أو 4x1L
    multi_pattern = rf"(\d+)\s*[\*xX×]\s*(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
    m_multi = re.search(multi_pattern, text, flags=re.IGNORECASE)
    if m_multi:
        qty = int(m_multi.group(1))
        val = float(m_multi.group(2))
        u_raw = m_multi.group(3).lower()
        std_unit = CANONICAL_UNITS.get(u_raw, u_raw)
        
        return {
            "pack_qty": qty,
            "unit_size_value": val,
            "total_size_value": round(val * qty, 2),
            "size_unit": std_unit,
        }

    # 2. فحص الأحجام الفردية (مع مراعاة التصاق الرقم بالحرف مثل 1.3L أو ١.٣لتر)
    single_pattern = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})"
    m_single = re.search(single_pattern, text, flags=re.IGNORECASE)
    if m_single:
        val = float(m_single.group(1))
        u_raw = m_single.group(2).lower()
        std_unit = CANONICAL_UNITS.get(u_raw, u_raw)

        # فحص إضافي إن وجد ذكر للشدات في جزء آخر من النص (مثل: 6 حبات)
        qty_pattern = r"(\d+)\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|قارورة|قوارير|كيس|صحن)\b"
        m_qty = re.search(qty_pattern, text, flags=re.IGNORECASE)
        qty = int(m_qty.group(1)) if m_qty else 1

        return {
            "pack_qty": qty,
            "unit_size_value": val,
            "total_size_value": round(val * qty, 2),
            "size_unit": std_unit,
        }

    # 3. فحص العبوات بالعدد فقط بدون وزن صريح (مثل: 30 بيضة أو 6 حبات)
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


def extract_best_price_and_discounts(item: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    """فحص جميع الفروع في inventory_modifiers واختيار السعر الأقل والخصم الأكبر."""
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
    print("=== [BinDawood] Starting Silver Clean Pipeline (Standard Units) ===")
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