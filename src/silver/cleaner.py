"""Silver Layer Cleaner and Standardizer with Smart Barcode Completion.

Reads raw category JSON files from `data/bronze/{store}/` and saves cleaned,
normalized, and schema-aligned files to `data/silver/{store}/`.
Calculates missing GS1 check digits for BinDawood barcodes.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
BRONZE_DIR = BASE_DIR / "data" / "bronze"
SILVER_DIR = BASE_DIR / "data" / "silver"

STORES = ["bindawood", "lulu", "tamimi"]

CATEGORIES = [
    "beverages_raw.json",
    "dairy_and_eggs_raw.json",
    "fruits_and_vegetables_raw.json",
]

KNOWN_BRANDS = [
    # English
    "Florida's Natural", "The Ginger People", "Al Qasim Produce",
    "Philippine Brand", "La Vache Qui Rit", "Solan de Cabras",
    "The Three Cows", "Orient Gardens", "Cathedral City", "Philadelphia",
    "Mountain Dew", "S.Pellegrino", "Vitamin Well", "Power Horse",
    "Rude Health", "Driscoll's", "Martinelli", "Natureland", "Capri-Sun",
    "Dr.Pepper", "Coca Cola", "Starbucks", "President", "Schweppes",
    "Sun Blast", "Barbican", "Sunbulah", "Vitamizu", "Cofrutos",
    "Heineken", "Code Red", "Cacaolat", "Victoria", "Al Rabie",
    "Valbreso", "Rubicon", "Landana", "Actimel", "Belvoir", "Halwani",
    "Danette", "Forsana", "Perrier", "Mirinda", "Activia", "Babybel",
    "Beltion", "Mishkat", "Violife", "Almarai", "Al Safi", "Juhayna",
    "Caesar", "Suntop", "Balade", "Puvana", "Saudia", "Twisst", "Berain",
    "Lurpak", "Sprite", "Rockit", "Moussy", "Klasse", "Scotti", "Lipton",
    "Rauch", "Nerve", "Sante", "Vimto", "Milaf", "Nadec", "Ultra",
    "Pepsi", "Kraft", "Pinar", "Kinza", "Frico", "Yopro", "Safio",
    "Fanta", "Koita", "Akoya", "Vinut", "Twist", "Hotly", "Orasi",
    "Bonny", "Queen", "Monin", "Oatly", "Prime", "Pride", "Alpro",
    "Spada", "Evian", "Regal", "Danao", "Luna", "Nova", "Dari", "RARE",
    "Arwa", "Oska", "Rita", "Safa", "Kiri", "Puck", "Fifa", "Alsi",
    "Goro", "Noug", "Arla", "Nada", "7 Up", "Rani", "Zoi", "OKF", "May",
    "KDD", "Danube", "Original", "Rockstar", "Juicy", "Danya", "Shani",
    "Legero", "Senac", "Disfruta", "Canada", "Anchor", "Aquafina", "Ava",
    "Tania", "Nestlé", "Nescafe", "Fakieh", "Entaj", "Volvic", "Voss",
    "Zamzam", "Red Bull", "Al Gharbia", "Fresh",

    # Arabic
    "فلوريدا ناتشورال", "ذا جينجر بيبول", "القصيم بروديوس",
    "فيليبيني براند", "لافاش كيري", "سولان دي كابراس",
    "ذا ثري كاوز", "أورينت جاردنز", "كاتدرال سيتي", "فيلادلفيا",
    "ماونتن ديو", "سان بيليغرينو", "فيتامين ويل", "باور هورس",
    "رود هيلث", "دريسكولز", "مارتينيلي", "نيتشرلاند", "كابري صن",
    "دكتور بيبر", "كوكا كولا", "ستاربكس", "بريزيدنت", "شويبس",
    "صن بلاست", "باربيكان", "سنبل", "فيتاميزو", "كوفروتوس",
    "هاينكن", "كود ريد", "كاكاولات", "فيكتوريا", "الربيع",
    "فالبريزو", "روبيكون", "لاندانا", "أكتيميل", "بلفوار", "حلواني",
    "دانونيت", "فورسانا", "بيرييه", "ميرندا", "أكتيفيا", "بيبيبل",
    "بيلتيون", "مشكات", "فايلف", "المراعي", "الصافي", "جهينة",
    "سيزر", "سنتوب", "بالاد", "بوفانا", "سعوديا", "تويست", "بيرين",
    "لورباك", "سبرايت", "روكيت", "موسي", "كلاسي", "سكوتي", "ليبتون",
    "راوخ", "نيرف", "سانتي", "فيمتو", "ميلاف", "نادك", "ألترا",
    "بيبسي", "كرافت", "بينار", "كينزا", "فريكو", "يوبرو", "صافيو",
    "فانتا", "كويتا", "أكويا", "فينوت", "هوتلي", "أوراسي",
    "بوني", "كوين", "مونين", "أوتلي", "برايم", "برايد", "ألبرو",
    "سبادا", "إيفيان", "ريغال", "داناو", "لونا", "نوفا", "داري", "رير",
    "أروى", "أوسكا", "ريتا", "صفا", "كيري", "بوك", "فيفا", "ألسي",
    "جورو", "نوغ", "أرلا", "ندى", "7 أب", "راني", "زوي", "أوكاي إف",
    "ماي", "كي دي دي", "دانوب", "أوريجينال", "روكستار", "جوسي", "دانية",
    "شاني", "ليغيرو", "سيناك", "ديسفروتا", "كانادا", "أنكور", "أكوافينا",
    "آفا", "تانيا", "نستله", "نسكافيه", "فقيه", "إنتاج", "فولفيك", "فوس",
    "زمزم", "ريد بول", "الغربية", "فريش"
]

SORTED_BRANDS = sorted(KNOWN_BRANDS, key=len, reverse=True)

SIZE_PACK_PATTERNS = [
    r"\b\d+\s*[\*xX×]\s*\d+(?:\.\d+)?\s*(?:ml|l|ltr|kg|g|مل|لتر|ل|غم|جم|غرام|جرام|كغم|كيلو)?\b",
    r"\b\d+(?:\.\d+)?\s*(?:ml|milliliter|liter|litre|ltr|l|kg|g|gram|grams|مل|ملل|لتر|ل|غم|جم|غرام|جرام|كغم|كيلو)\b",
    r"\b\d+\s*(?:حبة|حبات|قطع|قطعة|pcs|pc|pack|can|cans|علبة|علب|قارورة|قوارير|كيس|صحن|count)\b",
    r"\b(?:تقريبا|تقريباً|approx|approximately)\b",
]

VOLUME_WEIGHT_RULES = [
    (r"(\d+(?:\.\d+)?)\s*(?:liter|litre|ltr|l|لتر|ل)\b", 1000.0, "ml"),
    (r"(\d+(?:\.\d+)?)\s*(?:ml|milliliter|مل|ملل)\b", 1.0, "ml"),
    (r"(\d+(?:\.\d+)?)\s*(?:kg|kilo|kilogram|كيلو|كجم|كغ)\b", 1000.0, "g"),
    (r"(\d+(?:\.\d+)?)\s*(?:g|gram|grams|غرام|جرام|غم|جم)\b", 1.0, "g"),
]


def calculate_ean13_check_digit(barcode_12: str) -> str:
    """حساب الرقم الـ 13 الناقص (GS1 Check Digit) لباركود 12 خانة."""
    if len(barcode_12) != 12 or not barcode_12.isdigit():
        return ""
    odd_sum = sum(int(barcode_12[i]) for i in range(0, 12, 2))
    even_sum = sum(int(barcode_12[i]) for i in range(1, 12, 2))
    total = odd_sum + (even_sum * 3)
    return str((10 - (total % 10)) % 10)


def detect_brand(text: str | None) -> str | None:
    if not text:
        return None
    for brand in SORTED_BRANDS:
        pattern = rf"(?<!\w){re.escape(brand)}(?!\w)"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return brand
    return None


def extract_unit_and_value(text: str | None) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    for pattern, multiplier, standard_unit in VOLUME_WEIGHT_RULES:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            raw_val = float(match.group(1))
            return round(raw_val * multiplier, 2), standard_unit
    return None, None


def clean_product_name(name: str | None, detected_brand: str | None) -> str | None:
    if not name:
        return None
    cleaned = name
    if detected_brand:
        cleaned = re.sub(rf"(?<!\w){re.escape(detected_brand)}(?!\w)", " ", cleaned, flags=re.IGNORECASE)
    for pat in SIZE_PACK_PATTERNS:
        cleaned = re.sub(pat, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\*×\-_/\\,]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else name.strip()


def parse_bindawood(item: dict[str, Any], category_name: str) -> dict[str, Any]:
    raw_name_en = item.get("name_en") or item.get("full_name_en")
    raw_name_ar = item.get("name_ar") or item.get("full_name_ar")
    full_text = f"{item.get('full_name_en', '')} {item.get('full_name_ar', '')}"

    brand = item.get("brand_en") or item.get("brand_ar") or detect_brand(full_text)

    price = item.get("price")
    original_price = item.get("original_price")
    modifiers = item.get("inventory_modifiers") or {}
    if modifiers and isinstance(modifiers, dict):
        first_mod = next(iter(modifiers.values()), {})
        if first_mod.get("price") is not None:
            try:
                price = float(first_mod.get("price"))
            except (ValueError, TypeError):
                pass
        if first_mod.get("original_price") is not None:
            try:
                original_price = float(first_mod.get("original_price"))
            except (ValueError, TypeError):
                pass

    size_val, size_unit = extract_unit_and_value(full_text)
    image_url = item.get("image") or ""

    # استخراج وتصحيح الباركود الناقص
    barcodes = set()
    if image_url:
        barcode_match = re.search(r"/(\d{8,14})\.(?:jpg|jpeg|png|webp)", image_url)
        if barcode_match:
            raw_code = barcode_match.group(1)
            barcodes.add(raw_code)

            if len(raw_code) == 12:
                check_digit = calculate_ean13_check_digit(raw_code)
                if check_digit:
                    barcodes.add(raw_code + check_digit)

    return {
        "id": str(item.get("master_id") or item.get("objectID")),
        "store": "bindawood",
        "category": category_name,
        "name_en": clean_product_name(raw_name_en, brand),
        "name_ar": clean_product_name(raw_name_ar, brand),
        "raw_name_en": raw_name_en,
        "raw_name_ar": raw_name_ar,
        "brand": brand,
        "barcodes": sorted(list(barcodes)),
        "price": float(price) if price is not None else None,
        "original_price": float(original_price) if original_price is not None else None,
        "on_sale": item.get("on_sale", False),
        "in_stock": item.get("in_stock", True),
        "size_value": size_val,
        "size_unit": size_unit,
        "image_url": image_url if image_url else None,
    }


def parse_lulu(item: dict[str, Any], category_name: str) -> dict[str, Any]:
    attrs = item.get("attributes") or {}
    raw_name_ar = item.get("name")
    raw_name_en = attrs.get("product_name") or attrs.get("Description")
    full_text = f"{raw_name_en or ''} {raw_name_ar or ''} {attrs.get('content', '')}"

    brand = attrs.get("brand")
    if not brand or brand.lower() == "fresh":
        brand = detect_brand(full_text) or brand

    price = None
    try:
        if item.get("price") is not None:
            price = float(item["price"])
    except (ValueError, TypeError):
        pass

    original_price = None
    try:
        if item.get("retail_price") is not None:
            original_price = float(item["retail_price"])
    except (ValueError, TypeError):
        pass

    size_val, size_unit = extract_unit_and_value(full_text)

    barcodes = set()
    if attrs.get("main_ean"):
        barcodes.add(str(attrs["main_ean"]).strip())
    if attrs.get("lulu_ean"):
        barcodes.add(str(attrs["lulu_ean"]).strip())
    if attrs.get("ean"):
        for code in str(attrs["ean"]).split(","):
            if code.strip():
                barcodes.add(code.strip())

    images = item.get("productimage_set") or []
    image_url = images[0].get("image") if images and isinstance(images, list) else None

    return {
        "id": str(item.get("sku") or item.get("pk")),
        "store": "lulu",
        "category": category_name,
        "name_en": clean_product_name(raw_name_en, brand),
        "name_ar": clean_product_name(raw_name_ar, brand),
        "raw_name_en": raw_name_en,
        "raw_name_ar": raw_name_ar,
        "brand": brand,
        "barcodes": sorted(list(barcodes)),
        "price": price,
        "original_price": original_price,
        "on_sale": (original_price is not None and price is not None and original_price > price),
        "in_stock": item.get("in_stock", True),
        "size_value": size_val,
        "size_unit": size_unit,
        "image_url": image_url,
    }


def parse_tamimi(item: dict[str, Any], category_name: str) -> dict[str, Any]:
    variants = item.get("variants") or []
    first_variant = variants[0] if variants and isinstance(variants, list) else {}

    raw_name_en = first_variant.get("fullName") or item.get("name")
    raw_name_ar = None

    brand_obj = item.get("brand") or {}
    brand = brand_obj.get("name") if isinstance(brand_obj, dict) else None
    if not brand:
        brand = detect_brand(raw_name_en)

    price = None
    original_price = None
    in_stock = True

    store_data = first_variant.get("storeSpecificData") or []
    if store_data and isinstance(store_data, list):
        primary_store = store_data[0]
        try:
            mrp = float(primary_store.get("mrp", 0))
            discount = float(primary_store.get("discount", 0))
            price = round(mrp - discount, 2)
            original_price = mrp if discount > 0 else None
            in_stock = int(primary_store.get("stock", 1)) > 0
        except (ValueError, TypeError):
            pass

    size_val, size_unit = extract_unit_and_value(raw_name_en)

    raw_barcodes = first_variant.get("barcodes") or []
    barcodes = [str(b).strip() for b in raw_barcodes if b]

    images = first_variant.get("images") or []
    image_url = images[0] if images and isinstance(images, list) else None

    return {
        "id": str(item.get("id")),
        "store": "tamimi",
        "category": category_name,
        "name_en": clean_product_name(raw_name_en, brand),
        "name_ar": None,
        "raw_name_en": raw_name_en,
        "raw_name_ar": None,
        "brand": brand,
        "barcodes": barcodes,
        "price": price,
        "original_price": original_price,
        "on_sale": bool(original_price is not None and original_price > (price or 0)),
        "in_stock": in_stock,
        "size_value": size_val,
        "size_unit": size_unit,
        "image_url": image_url,
    }


PARSERS = {
    "bindawood": parse_bindawood,
    "lulu": parse_lulu,
    "tamimi": parse_tamimi,
}


def clean_and_standardize_category(store: str, category_filename: str):
    bronze_path = BRONZE_DIR / store / category_filename
    if not bronze_path.exists():
        return

    with open(bronze_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    category_slug = category_filename.replace("_raw.json", "")
    parser = PARSERS[store]

    cleaned_items = []
    seen_ids = set()

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            # إذا كان المتجر لولو ولديه خيارات متعددة، فككها هنا
            items_to_parse = [item]
            if store == "lulu":
                variants = (item.get("extra_data") or {}).get("variants") or []
                if variants:
                    expanded = []
                    for v_group in variants:
                        for opt in (v_group.get("options") or []):
                            sub = opt.get("product")
                            if isinstance(sub, dict):
                                c = dict(item)
                                c["pk"] = sub.get("pk", c.get("pk"))
                                c["sku"] = sub.get("sku", c.get("sku"))
                                c["name"] = sub.get("name", c.get("name"))
                                c["price"] = sub.get("price", c.get("price"))
                                c["retail_price"] = sub.get("retail_price", c.get("retail_price"))
                                expanded.append(c)
                    if expanded:
                        items_to_parse = expanded

            for target_item in items_to_parse:
                standardized = parser(target_item, category_slug)
                prod_id = standardized["id"]
                if prod_id and prod_id not in seen_ids:
                    seen_ids.add(prod_id)
                    cleaned_items.append(standardized)
        except Exception:
            continue

    out_dir = SILVER_DIR / store
    out_dir.mkdir(parents=True, exist_ok=True)
    out_filename = category_filename.replace("_raw.json", "_clean.json")
    out_path = out_dir / out_filename

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_items, f, ensure_ascii=False, indent=2)

    print(f"  ✓ [{store}] {category_slug} -> Cleaned {len(cleaned_items)} products.")


def main():
    print("=== Starting Silver Layer Data Cleaning Pipeline ===")
    for store in STORES:
        print(f"\nProcessing Store: {store.upper()}")
        for cat_file in CATEGORIES:
            clean_and_standardize_category(store, cat_file)
    print("\n=== Silver Cleaning Finished Successfully ===")


if __name__ == "__main__":
    main()