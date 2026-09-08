"""Gold Layer: GASTAT-Anchored Produce Matcher (Targeting All 40+ Official Items).

Features:
  - Dynamically extracts all distinct produce commodities from GASTAT.
  - Matches across BinDawood, Lulu, and Tamimi using primary commodity roots.
  - Prioritizes origin/variety match (e.g. American, Local) while preventing drops.
  - Strict 3-Store Exclusive output with BinDawood precedence.
  - Injects latest official GASTAT benchmark price & maintains cumulative history.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
SILVER_DIR = BASE_DIR / "data" / "silver"
GOLD_DIR = BASE_DIR / "data" / "gold"
STORES = ["bindawood", "lulu", "tamimi"]

GASTAT_FILE = BASE_DIR / "data" / "open_data" / "gastat__fruits_and_vegetables_clean.json"
OUT_FILE = GOLD_DIR / "matched_fruits_and_vegetables.json"

# استخراج الجذر الزراعي الأساسي لكل صنف من أصناف الهيئة
PRIMARY_ROOTS = {
    "موز": "banana", "banana": "banana",
    "تمر": "dates", "dates": "dates", "رطب": "dates", "إخلاص": "dates",
    "تين": "fig", "fig": "fig",
    "منجا": "mango", "mango": "mango", "مانجو": "mango",
    "ليمون": "lemon", "lemon": "lemon",
    "برتقال": "orange", "orange": "orange",
    "يوسفي": "mandarin", "mandarin": "mandarin",
    "تفاح": "apple", "apple": "apple",
    "كمثرى": "pear", "pear": "pear",
    "برقوق": "plum", "plum": "plum", "بخارى": "plum",
    "خوخ": "peach", "peach": "peach",
    "رمان": "pomegranate", "pomegranate": "pomegranate",
    "عنب": "grape", "grape": "grape",
    "شمام": "melon", "melon": "melon",
    "حبحب": "watermelon", "بطيخ": "watermelon", "watermelon": "watermelon",
    "خس": "lettuce", "lettuce": "lettuce",
    "ملوخية": "corchorus", "corchorus": "corchorus",
    "جرجير": "watercress", "watercress": "watercress",
    "ملفوف": "cabbage", "cabbage": "cabbage",
    "سبانخ": "spinach", "spinach": "spinach",
    "فلفل": "pepper", "peppers": "pepper", "chili": "pepper",
    "خيار": "cucumber", "cucumbers": "cucumber",
    "باذنجان": "eggplant", "eggplants": "eggplant",
    "طماطم": "tomatoes", "tomatoes": "tomatoes",
    "قرع": "pumpkin", "pumpkin": "pumpkin",
    "كوسة": "zucchini", "zucchini": "zucchini",
    "بامية": "okra", "okra": "okra",
    "فاصوليا": "green_beans", "beans": "green_beans",
    "جزر": "carrots", "carrots": "carrots",
    "ثوم": "garlic", "garlic": "garlic",
    "بصل": "onion", "onion": "onion",
    "زيتون": "olives", "olives": "olives",
    "بطاطس": "potatoes", "potatoes": "potatoes",
    "ذرة": "corn", "corn": "corn",
    "بقدونس": "parsley", "parsley": "parsley",
}


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def get_commodity_root(text: str) -> str | None:
    clean = normalize_text(text)
    for kw, root in PRIMARY_ROOTS.items():
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", clean):
            return root
    return None


def build_gastat_anchors() -> dict[str, dict[str, Any]]:
    """استخراج قائمة الـ 40 صنفاً المعيارية من أحدث بيانات GASTAT."""
    if not GASTAT_FILE.exists():
        return {}

    with open(GASTAT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", data) if isinstance(data, dict) else data

    anchors = {}
    for r in records:
        name_ar = (r.get("item_name_ar") or "").strip()
        name_en = (r.get("item_name_en") or "").strip()
        
        # تصحيح الأخطاء المطبعية في بعض السجلات
        if name_ar == "س" and "lemon" in name_en.lower():
            name_ar = "ليمون وسط أفريقي"

        if not name_ar or len(name_ar) < 2:
            continue

        # تعريف معرّف فريد للصنف
        key = name_en if name_en else name_ar
        root = get_commodity_root(f"{name_ar} {name_en}")
        if not root:
            continue

        year = int(r.get("Year", 0))
        if key in anchors and year < anchors[key]["year"]:
            continue

        # أحدث سعر مسجل
        avg_price = None
        for col in ["Dec", "Nov", "Oct", "Annual average"]:
            val = r.get(col)
            if val:
                try:
                    avg_price = round(float(str(val).replace(",", "")), 2)
                    break
                except (ValueError, TypeError):
                    continue

        anchors[key] = {
            "key": key,
            "root": root,
            "name_ar": name_ar,
            "name_en": name_en,
            "unit": "bundle" if "حزمة" in r.get("unit_ar", "") else "kg",
            "benchmark_price": avg_price,
            "year": year,
            "is_local": "محلي" in name_ar or "local" in name_en.lower(),
            "is_imported": "مستورد" in name_ar or "imported" in name_en.lower(),
        }

    return anchors


def load_all_silver_produce() -> dict[str, list[dict[str, Any]]]:
    store_items = {}
    for store in STORES:
        path = SILVER_DIR / store / "fruits_and_vegetables_clean.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                store_items[store] = json.load(f)
        else:
            store_items[store] = []
    return store_items


def load_existing_history(file_path: Path) -> dict[str, list[dict[str, Any]]]:
    history_map = defaultdict(list)
    if not file_path.exists():
        return history_map

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for item in old_data:
                key = item.get("gastat_key") or item.get("commodity_type") or item.get("barcode")
                if key and "price_history" in item:
                    history_map[str(key)] = item["price_history"]
    except Exception as e:
        print(f"  [!] Note: Could not read prior history: {e}")

    return history_map


def score_produce_match(prod: dict[str, Any], anchor: dict[str, Any]) -> float:
    """تقييم مدى ملاءمة المنتج لسلعة GASTAT مع إعطاء أولوية للجذر."""
    full_text = normalize_text(f"{prod.get('name_en') or ''} {prod.get('name_ar') or ''}")

    # 1. مطابقة الجذر الأساسي شرط إلزامي (طماطم مع طماطم)
    prod_root = get_commodity_root(full_text)
    if prod_root != anchor["root"]:
        return 0.0

    # 2. فحص نوع العبوة (حزمة vs كيلو)
    prod_unit = str(prod.get("size_unit") or "").lower()
    is_bundle_prod = any(u in prod_unit for u in ["bundle", "حزمة", "ربطة"]) or any(
        w in full_text for w in ["حزمة", "ربطة", "bundle"]
    )
    if anchor["unit"] == "bundle" and not is_bundle_prod:
        return 0.0
    if anchor["unit"] == "kg" and is_bundle_prod:
        return 0.0

    score = 1.0

    # 3. ترجيح المنشأ (محلي vs مستورد)
    is_prod_local = "محلي" in full_text or "وطني" in full_text or "local" in full_text
    is_prod_imported = "مستورد" in full_text or "imported" in full_text

    if anchor["is_local"] and is_prod_local:
        score += 0.5
    elif anchor["is_imported"] and is_prod_imported:
        score += 0.5

    # ترجيح إضافي عند تطابق أجزاء من الاسم (مثل: مصري، باكستاني، أحمر، أصفر)
    for word in normalize_text(anchor["name_ar"]).split():
        if len(word) >= 3 and word in full_text:
            score += 0.2

    return score


def select_canonical_product(prods: list[dict[str, Any]]) -> dict[str, Any]:
    store_priority = {"bindawood": 0, "lulu": 1, "tamimi": 2}
    sorted_prods = sorted(prods, key=lambda x: store_priority.get(x["store"], 99))
    return sorted_prods[0]


def main():
    print("=" * 65)
    print("🌾 RUNNING ADVANCED GASTAT PRODUCE MATCHER (ALL OFFICIAL ITEMS)")
    print("=" * 65)

    anchors = build_gastat_anchors()
    if not anchors:
        print(f"[!] GASTAT anchors file not found at: {GASTAT_FILE}")
        return

    print(f"  • Successfully extracted {len(anchors)} distinct official GASTAT commodities.")

    store_products = load_all_silver_produce()
    prior_history = load_existing_history(OUT_FILE)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    matched_clusters = []

    # البحث عن تمثيل لكل صنف من أصناف الهيئة الـ 40 في كل متجر
    for key, anchor in anchors.items():
        matched_by_store = {}

        for store in STORES:
            best_prod = None
            best_score = 0.0

            for prod in store_products[store]:
                if prod.get("price") is None or prod.get("price") <= 0:
                    continue

                score = score_produce_match(prod, anchor)
                if score > best_score and score >= 1.0:
                    best_score = score
                    best_prod = prod

            if best_prod:
                matched_by_store[store] = best_prod

        # حصر العناقيد على التي تتوفر في المتاجر الـ 3 معاً
        if len(matched_by_store) == 3:
            matched_clusters.append({
                "anchor": anchor,
                "prods": list(matched_by_store.values()),
            })

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    formatted = []

    for cluster in matched_clusters:
        anchor = cluster["anchor"]
        prods = cluster["prods"]
        canonical = select_canonical_product(prods)

        valid_prices = [p["price"] for p in prods if p.get("price") is not None]
        avg_price = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else None
        min_price = min(valid_prices) if valid_prices else None
        max_price = max(valid_prices) if valid_prices else None
        price_diff = round(max_price - min_price, 2) if (min_price and max_price) else 0.0

        stores_data = {}
        for p in prods:
            stores_data[p["store"]] = {
                "price": p.get("price"),
                "original_price": p.get("original_price"),
                "discount_amount": p.get("discount_amount"),
                "discount_percentage": p.get("discount_percentage"),
                "has_discount": bool(p.get("discount_amount") and p["discount_amount"] > 0),
                "image_url": p.get("image_url"),
                "raw_product_id": p.get("id"),
            }

        lookup_key = str(anchor["key"])
        existing_history = prior_history.get(lookup_key, [])

        current_entry = {
            "date": today_str,
            "avg_price": avg_price,
            "min_price": min_price,
            "max_price": max_price,
            "gastat_benchmark": anchor["benchmark_price"],
            "stores_prices": {k: v["price"] for k, v in stores_data.items()},
        }

        updated_history = [h for h in existing_history if h.get("date") != today_str]
        updated_history.append(current_entry)

        all_barcodes = canonical.get("barcodes") or []
        primary_barcode = all_barcodes[0] if all_barcodes else None

        formatted.append({
            "gastat_key": anchor["key"],
            "commodity_root": anchor["root"],
            "product_name_ar": canonical.get("name_ar") or anchor["name_ar"],
            "product_name_en": canonical.get("name_en") or anchor["name_en"],
            "official_gastat_name_ar": anchor["name_ar"],
            "official_gastat_name_en": anchor["name_en"],
            "brand": canonical.get("brand"),
            "category": "fruits_and_vegetables",
            "unit": anchor["unit"],
            "size": canonical.get("unit_size_value") or canonical.get("size_value") or 1.0,
            "barcode": primary_barcode,
            "image_url": canonical.get("image_url"),
            "canonical_source": canonical.get("store"),
            "matched_stores_count": 3,
            "matched_stores": ["bindawood", "lulu", "tamimi"],
            "current_pricing": {
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_diff": price_diff,
                "gastat_benchmark_price": anchor["benchmark_price"],
                "variance_from_benchmark": round(avg_price - anchor["benchmark_price"], 2) if (avg_price and anchor["benchmark_price"]) else None,
            },
            "price_history": updated_history,
            "stores_data": stores_data,
        })

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    archive_dir = GOLD_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"matched_fruits_and_vegetables_{today_str}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    total_prods = sum(len(items) for items in store_products.values())
    matched_prods = len(formatted) * 3
    coverage_pct = round(len(formatted) / len(anchors) * 100, 2) if anchors else 0.0

    print("\n" + "=" * 65)
    print("📊 GASTAT OFFICIAL BASKET REPORT:")
    print(f"   • Total Official Commodities: {len(anchors)}")
    print(f"   • Matched Tri-Store Clusters : {len(formatted)} clusters")
    print(f"   • Official Basket Coverage   : {coverage_pct}%")
    print(f"   • Matched Store Items        : {matched_prods} products")
    print(f"   • Output File                : {OUT_FILE.name}")
    print("=" * 65)


if __name__ == "__main__":
    main()