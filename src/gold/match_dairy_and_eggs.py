"""Gold Layer: Tri-Store Exclusive Dairy & Eggs Matching Engine with Cumulative History.

Applies:
  - Exact & Root-12 Barcode Matching (Tier 1)
  - Normalized Brand + Token Overlap + Fat/Salt/Cheese Discriminators (Tier 2)
  - Filters strictly for 3-Store Matches (BinDawood + Lulu + Tamimi)
  - BinDawood-first canonical metadata precedence
  - Cumulative Price History Tracking for weekly Airflow runs
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

FLUFF_WORDS = {
    "fresh", "pure", "premium", "quality", "original", "natural", "classic",
    "plastic", "bottle", "bot", "tetra", "pack", "packet", "box", "can", "cans",
    "tray", "bag", "pouch", "drink", "product", "taste", "style", "offer", "promo",
    "طازج", "طازجة", "طبيعي", "بلاستيك", "علبة", "قارورة", "كرتون", "عرض", "شراب", "مشروب"
}

DAIRY_DISCRIMINATORS = [
    {"full", "skimmed", "low", "skim"},
    {"كامل", "قليل", "خالي", "منزوع"},
    {"salted", "unsalted"},
    {"مملح", "غير مملح"},
    {"large", "medium", "small"},
    {"كبير", "وسط", "صغير"},
    {"cheddar", "mozzarella", "halloumi", "feta", "gouda"},
    {"شيدر", "موزاريلا", "حلوم", "فيتا", "جودا"},
]


def normalize_brand(brand: str | None) -> str:
    if not brand:
        return "unbranded"
    return re.sub(r"[^a-zA-Z0-9\u0621-\u064A]", "", brand.lower())


def extract_core_tokens(name: str | None) -> set[str]:
    if not name:
        return set()
    raw = re.findall(r"\b[a-zA-Z\u0621-\u064A]{3,}\b", name.lower())
    return {w for w in raw if w not in FLUFF_WORDS}


def token_overlap_ratio(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    common = tokens_a.intersection(tokens_b)
    shorter = min(len(tokens_a), len(tokens_b))
    return len(common) / shorter if shorter > 0 else 0.0


def sizes_match(item_a: dict, item_b: dict, tolerance: float = 0.03) -> bool:
    s_a = item_a.get("size_value") or item_a.get("total_size_value")
    s_b = item_b.get("size_value") or item_b.get("total_size_value")
    u_a, u_b = item_a.get("size_unit"), item_b.get("size_unit")

    if not s_a or not s_b:
        return True
    if u_a == u_b:
        return (abs(s_a - s_b) / max(s_a, s_b)) <= tolerance
    return False


def select_canonical_product(prods: list[dict[str, Any]]) -> dict[str, Any]:
    store_priority = {"bindawood": 0, "lulu": 1, "tamimi": 2}
    sorted_prods = sorted(prods, key=lambda x: store_priority.get(x["store"], 99))
    return sorted_prods[0]


def load_dairy() -> list[dict[str, Any]]:
    items = []
    for store in STORES:
        path = SILVER_DIR / store / "dairy_and_eggs_clean.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
    return items


def load_existing_history(file_path: Path) -> dict[str, list[dict[str, Any]]]:
    """قراءة التاريخ التراكمي السابق لمنع مسح أسعار الأسابيع الماضية."""
    history_map = defaultdict(list)
    if not file_path.exists():
        return history_map

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
            for item in old_data:
                key = item.get("barcode") or item.get("product_name_en")
                if key and "price_history" in item:
                    history_map[str(key)] = item["price_history"]
    except Exception as e:
        print(f"  [!] Note: Could not read prior history: {e}")

    return history_map


def main():
    print("=== جاري مطابقة الألبان والبيض (3-STORES ONLY + التاريخ التراكمي للأسعار) ===")
    products = load_dairy()
    if not products:
        print("[!] لم يتم العثور على ملفات dairy_and_eggs_clean.json")
        return

    out_file = GOLD_DIR / "matched_dairy_and_eggs.json"
    prior_history = load_existing_history(out_file)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    visited = set()
    clusters = []

    # 1. مطابقة الباركود المباشر وجذور الأكواد (Tier 1)
    code_map = defaultdict(list)
    for p in products:
        for c in (p.get("barcodes") or []):
            code = str(c).strip().lstrip("0")
            if len(code) >= 8:
                code_map[f"full_{code}"].append(p)
                code_map[f"root12_{code[:12]}"].append(p)

    for _, prods in code_map.items():
        if len({x["store"] for x in prods}) > 1:
            cluster, seen_stores = [], set()
            for p in prods:
                uid = f"{p['store']}_{p['id']}"
                if p["store"] not in seen_stores and uid not in visited:
                    seen_stores.add(p["store"])
                    cluster.append(p)
                    visited.add(uid)
            if len(cluster) == 3:
                clusters.append({"tier": "exact_barcode", "confidence": 1.0, "products": cluster})

    # 2. مطابقة البراند والكلمات (Tier 2)
    remaining = [p for p in products if f"{p['store']}_{p['id']}" not in visited]
    brand_groups = defaultdict(list)
    for p in remaining:
        b = normalize_brand(p.get("brand"))
        if b != "unbranded":
            brand_groups[b].append(p)

    for _, items in brand_groups.items():
        for i, item_a in enumerate(items):
            uid_a = f"{item_a['store']}_{item_a['id']}"
            if uid_a in visited:
                continue
            cluster = [item_a]
            visited.add(uid_a)
            tok_a = extract_core_tokens(item_a.get("name_en"))

            for j in range(i + 1, len(items)):
                item_b = items[j]
                uid_b = f"{item_b['store']}_{item_b['id']}"
                if uid_b in visited or any(x["store"] == item_b["store"] for x in cluster):
                    continue

                if not sizes_match(item_a, item_b, tolerance=0.03):
                    continue

                tok_b = extract_core_tokens(item_b.get("name_en"))

                conflict = False
                for group in DAIRY_DISCRIMINATORS:
                    if tok_a.intersection(group) and tok_b.intersection(group):
                        if tok_a.intersection(group) != tok_b.intersection(group):
                            conflict = True
                            break
                if conflict:
                    continue

                if token_overlap_ratio(tok_a, tok_b) >= 0.75:
                    cluster.append(item_b)
                    visited.add(uid_b)

            if len(cluster) == 3:
                clusters.append({"tier": "dairy_brand_token", "confidence": 0.90, "products": cluster})

    # 3. تشكيل ملف الذهب مع التاريخ التراكمي
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    formatted = []

    for c in clusters:
        prods = c["products"]
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

        all_barcodes = canonical.get("barcodes") or []
        primary_barcode = all_barcodes[0] if all_barcodes else None

        # بناء سجل الأسعار التراكمي
        lookup_key = str(primary_barcode or canonical.get("name_en"))
        existing_history = prior_history.get(lookup_key, [])

        current_entry = {
            "date": today_str,
            "avg_price": avg_price,
            "min_price": min_price,
            "max_price": max_price,
            "stores_prices": {k: v["price"] for k, v in stores_data.items()},
        }

        updated_history = [h for h in existing_history if h.get("date") != today_str]
        updated_history.append(current_entry)

        formatted.append({
            "product_name_ar": canonical.get("name_ar"),
            "product_name_en": canonical.get("name_en"),
            "brand": canonical.get("brand"),
            "category": "dairy_and_eggs",
            "size": canonical.get("unit_size_value") or canonical.get("size_value"),
            "unit": canonical.get("size_unit"),
            "quantity": canonical.get("pack_qty", 1),
            "total_size": canonical.get("total_size_value") or canonical.get("size_value"),
            "barcode": primary_barcode,
            "image_url": canonical.get("image_url"),
            "canonical_source": canonical.get("store"),
            "match_tier": c["tier"],
            "confidence_score": c["confidence"],
            "matched_stores_count": 3,
            "matched_stores": ["bindawood", "lulu", "tamimi"],
            "current_pricing": {
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_diff": price_diff,
            },
            "price_history": updated_history,
            "stores_data": stores_data,
        })

    # حفظ الملف النشط
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    # حفظ لقطة مؤرخة في مجلد archive لـ Airflow
    archive_dir = GOLD_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"matched_dairy_and_eggs_{today_str}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    total_prods = len(products)
    matched_prods = len(formatted) * 3
    pct = round(matched_prods / total_prods * 100, 2) if total_prods else 0.0

    print("\n" + "=" * 60)
    print("📊 DAIRY & EGGS REPORT (EXCLUSIVE 3-STORE ONLY):")
    print(f"   • Total Products In Silver : {total_prods}")
    print(f"   • 3-Store Matches (Clusters): {len(formatted)} clusters")
    print(f"   • 2-Store Matches          : 0 (Excluded completely)")
    print(f"   • Matched Products Count   : {matched_prods}")
    print(f"   • Pure 3-Store Coverage    : {pct}%")
    print(f"   • Active File Saved        : {out_file.name}")
    print(f"   • Archive Snapshot Saved   : {archive_file.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()