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
    "cl": ("ml", 10.0),
    "centiliter": ("ml", 10.0),
    "centiliters": ("ml", 10.0),
    "kg": ("g", 1000.0),
    "kilo": ("g", 1000.0),
    "kilogram": ("g", 1000.0),
    "كيلو": ("g", 1000.0),
    "كجم": ("g", 1000.0),
    "كغ": ("g", 1000.0),
    "كغم": ("g", 1000.0),
    "g": ("g", 1.0),
    "gm": ("g", 1.0),
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
        # Count units -> canonical pcs
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
}

UNIT_PATTERN = r"(?:centiliters?|milliliter|kilogram|portions?|triangles?|slices?|litre|liter|grams|kilo|pack|cans|can|pcs|ltr|cl|ml|kg|gm|pc|l|g|كيلو|جرام|غرام|كغم|كجم|ملل|لتر|قطع|قطعة|حبات|حبة|علب|علبة|كغ|غم|جم|مل|شريحة|شرائح|مثلث|مثلثات|ل)"


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


def parse_pack_and_size(text: str | None, category: str | None = None) -> dict[str, Any]:
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

    # Ounces:
    # - beverages: plain oz is treated as US fluid ounce -> ml
    # - other categories: plain oz is treated as weight ounce -> g
    # Explicit "fl oz" is always liquid.
    fluid_oz = re.search(
        r"(\d+(?:\.\d+)?)\s*fl\.?\s*oz\b",
        text,
        flags=re.IGNORECASE,
    )
    if fluid_oz:
        value = round(float(fluid_oz.group(1)) * 29.5735, 2)
        return {
            "pack_qty": 1,
            "unit_size_value": value,
            "total_size_value": value,
            "size_unit": "ml",
        }

    oz_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:oz|ounce|ounces)\b",
        text,
        flags=re.IGNORECASE,
    )
    if oz_match:
        oz = float(oz_match.group(1))
        if category == "beverages":
            value = round(oz * 29.5735, 2)
            unit = "ml"
        else:
            value = round(oz * 28.3495, 2)
            unit = "g"

        return {
            "pack_qty": 1,
            "unit_size_value": value,
            "total_size_value": value,
            "size_unit": unit,
        }

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

    # 2. النمط العكسي: 500g x 2 أو 125ml * 18
    multi_rev = rf"(\d+(?:\.\d+)?)\s*({UNIT_PATTERN})\s*[\*xX×]\s*(\d+)"
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
    count_pattern = r"(\d+)\s*(?:counts?|eggs?|حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|بيض|بيضة|slices?|شرائح|شريحة)\b"
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

def extract_best_price_and_discounts(
    item: dict[str, Any],
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
]:
    """
    BinDawood pricing policy:

    1. Check all branches in inventory_modifiers.
    2. Ignore explicitly unavailable / out-of-stock branches.
    3. If ANY branch has a real sale
       (original_price > price), use the best sale price.
    4. Otherwise use the best available normal price.
    """

    def to_float(value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    candidates = []

    modifiers = item.get("inventory_modifiers") or {}

    if isinstance(modifiers, dict):
        for branch_id, mod in modifiers.items():

            if not isinstance(mod, dict):
                continue

            # Skip branch only when Panda/BinDawood explicitly
            # tells us it is unavailable or out of stock.
            if mod.get("available") is False:
                continue

            if mod.get("in_stock") is False:
                continue

            price = to_float(mod.get("price"))
            original = to_float(
                mod.get("original_price")
            )

            if price is None or price <= 0:
                continue

            is_sale = (
                original is not None
                and original > price
            )

            candidates.append({
                "branch_id": branch_id,
                "price": price,
                "original_price": original,
                "is_sale": is_sale,
            })

    # -------------------------------------------------
    # First priority: ANY branch with a real offer.
    # -------------------------------------------------

    sale_candidates = [
        c for c in candidates
        if c["is_sale"]
    ]

    if sale_candidates:

        best = min(
            sale_candidates,
            key=lambda x: x["price"],
        )

        price = round(
            best["price"],
            2,
        )

        original = round(
            best["original_price"],
            2,
        )

        discount_amount = round(
            original - price,
            2,
        )

        discount_percentage = round(
            (discount_amount / original) * 100,
            2,
        )

        return (
            price,
            original,
            discount_amount,
            discount_percentage,
        )

    # -------------------------------------------------
    # No offer anywhere: use lowest available price.
    # -------------------------------------------------

    if candidates:

        best = min(
            candidates,
            key=lambda x: x["price"],
        )

        return (
            round(best["price"], 2),
            None,
            None,
            None,
        )

    # -------------------------------------------------
    # Fallback to top-level product price.
    # -------------------------------------------------

    price = to_float(
        item.get("price")
    )

    original = to_float(
        item.get("original_price")
    )

    if (
        price is not None
        and original is not None
        and original > price
    ):

        discount_amount = round(
            original - price,
            2,
        )

        discount_percentage = round(
            (discount_amount / original) * 100,
            2,
        )

        return (
            round(price, 2),
            round(original, 2),
            discount_amount,
            discount_percentage,
        )

    return (
        round(price, 2)
        if price is not None else None,
        None,
        None,
        None,
    )


def parse_item(item: dict[str, Any], cat_slug: str) -> dict[str, Any] | None:
    name_en = item.get("full_name_en") or item.get("name_en")
    name_ar = item.get("full_name_ar") or item.get("name_ar")
    full_text = f"{name_en or ''} {name_ar or ''}"

    brand = item.get("brand_en") or item.get("brand_ar")
    if not brand and name_en:
        brand = name_en.split()[0]

    price, orig_price, disc_amt, disc_pct = extract_best_price_and_discounts(item)
    size_data = parse_pack_and_size(full_text, cat_slug)

    
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