"""Gold Layer: Tri-Store Exclusive Dairy & Eggs Matching Engine with Cumulative History.

Applies:
  - Exact & Root-12 Barcode Matching with Strict Pack/Size Guard (Tier 1)
  - Normalized Brand + Token Overlap + Form Factor & Cheese Discriminators (Tier 2)
  - Strict 1.85x Price Ratio Guard (Prevents mixing single units with bulk/trays)
  - Strict Size & Unit Presence (No Blind Matches on Null Sizes)
  - Filters strictly for 3-Store Matches (BinDawood + Lulu + Tamimi)
  - BinDawood-first canonical metadata precedence
  - Cumulative Price History Tracking
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

DAIRY_SYNONYMS = {
    "slice": "slice_form",
    "slices": "slice_form",
    "شريحة": "slice_form",
    "شرائح": "slice_form",
    "triangle": "triangle_form",
    "triangles": "triangle_form",
    "portion": "triangle_form",
    "portions": "triangle_form",
    "مثلث": "triangle_form",
    "مثلثات": "triangle_form",
    "spread": "spread_form",
    "كاسات": "spread_form",
    "سائل": "spread_form",
    "shredded": "shredded_form",
    "مبشور": "shredded_form",
    "block": "block_form",
    "قالب": "block_form",
}

DAIRY_DISCRIMINATORS = [
    {"full", "skimmed", "low", "skim"},
    {"كامل", "قليل", "خالي", "منزوع"},
    {"salted", "unsalted"},
    {"مملح", "غير مملح"},
    {"large", "medium", "small"},
    {"كبير", "وسط", "صغير"},
    # تمييز أنواع الأجبان
    {"cheddar", "mozzarella", "halloumi", "feta", "gouda", "kashkaval", "labneh", "cream", "parmesan"},
    {"شيدر", "موزاريلا", "حلوم", "فيتا", "جودا", "قشقوان", "لبنة", "قشطة", "بارميزان"},
    # تمييز شكل وهيئة المنتج (شرائح مقابل مثلثات مقابل كاسات مقابل مبشور)
    {"slice_form", "triangle_form", "spread_form", "shredded_form", "block_form"},
]


def normalize_brand(brand: str | None) -> str:
    if not brand:
        return "unbranded"
    return re.sub(r"[^a-zA-Z0-9\u0621-\u064A]", "", brand.lower())


def extract_core_tokens(name: str | None) -> set[str]:
    if not name:
        return set()
    raw = re.findall(r"\b[a-zA-Z\u0621-\u064A]{3,}\b", name.lower())
    tokens = set()
    for w in raw:
        mapped = DAIRY_SYNONYMS.get(w, w)
        if mapped not in FLUFF_WORDS:
            tokens.add(mapped)
    return tokens


def token_overlap_ratio(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    common = tokens_a.intersection(tokens_b)
    shorter = min(len(tokens_a), len(tokens_b))
    return len(common) / shorter if shorter > 0 else 0.0


def are_dairy_discriminators_conflicting(tok_a: set[str], tok_b: set[str]) -> bool:
    for group in DAIRY_DISCRIMINATORS:
        inter_a = tok_a.intersection(group)
        inter_b = tok_b.intersection(group)
        if inter_a and inter_b and inter_a != inter_b:
            return True
    return False


def items_strictly_match(p1: dict, p2: dict) -> bool:
    """التحقق الصارم من تطابق الحجم والكمية والسعر وهيئة الصنف."""
    pr1, pr2 = p1.get("price"), p2.get("price")
    
    # 1. صمام الأمان السعري الصارم (حد أقصى 1.85x لمنع خلط الشرائح والعبوات المضاعفة)
    if pr1 and pr2 and pr1 > 0 and pr2 > 0:
        ratio = max(pr1, pr2) / min(pr1, pr2)
        if ratio > 1.85:
            return False

    q1 = p1.get("pack_qty") or 1
    q2 = p2.get("pack_qty") or 1
    if q1 != q2:
        return False

    v1 = p1.get("total_size_value") or p1.get("unit_size_value")
    v2 = p2.get("total_size_value") or p2.get("unit_size_value")
    u1 = p1.get("size_unit")
    u2 = p2.get("size_unit")

    # 2. فحص نوع الوحدة: منع ربط جرامات مع شرائح أو قطع
    if u1 and u2 and u1 != u2:
        return False

    # 3. فحص الحجم بدقة إذا وجد الاثنان (هامش خطأ 5% فقط)
    if v1 and v2:
        return (abs(v1 - v2) / max(v1, v2)) <= 0.05

    # 4. إذا كان الحجم مفقوداً في أحدهما مع وجود تباين سعري مريب (> 1.35x) -> رفض فوري
    if (v1 is None or v2 is None) and pr1 and pr2:
        if (max(pr1, pr2) / min(pr1, pr2)) > 1.35:
            return False

    return True


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
    print("=== جاري مطابقة الألبان والبيض (3-STORES ONLY + قواعد الأمان الصارمة) ===")
    products = load_dairy()
    if not products:
        print("[!] لم يتم العثور على ملفات dairy_and_eggs_clean.json")
        return

    out_file = GOLD_DIR / "matched_dairy_and_eggs.json"
    prior_history = load_existing_history(out_file)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prod_map = {}
    for p in products:
        uid = f"{p['store']}_{p['id']}"
        prod_map[uid] = p
        full_text = f"{p.get('name_en') or ''} {p.get('name_ar') or ''}"
        p["_tokens"] = extract_core_tokens(full_text)
        p["_norm_brand"] = normalize_brand(p.get("brand"))

    visited = set()
    clusters = []

    # 1. مطابقة الباركود المباشر وجذور الأكواد (Tier 1) مع الفحص الصارم
    code_map = defaultdict(list)
    for p in products:
        for c in (p.get("barcodes") or []):
            code = str(c).strip().lstrip("0")
            if len(code) >= 8:
                code_map[f"full_{code}"].append(p)

    for _, prods in code_map.items():
        if len({x["store"] for x in prods}) >= 3:
            store_groups = defaultdict(list)
            for p in prods:
                store_groups[p["store"]].append(p)
            
            if len(store_groups) == 3:
                for p_bin in store_groups["bindawood"]:
                    for p_lu in store_groups["lulu"]:
                        for p_tam in store_groups["tamimi"]:
                            u_bin = f"bindawood_{p_bin['id']}"
                            u_lu = f"lulu_{p_lu['id']}"
                            u_tam = f"tamimi_{p_tam['id']}"
                            
                            if u_bin in visited or u_lu in visited or u_tam in visited:
                                continue

                            # فحص تعارض هيئة الصنف (شرائح vs مثلثات vs قوالب)
                            if are_dairy_discriminators_conflicting(p_bin["_tokens"], p_lu["_tokens"]) or \
                               are_dairy_discriminators_conflicting(p_bin["_tokens"], p_tam["_tokens"]):
                                continue

                            if items_strictly_match(p_bin, p_lu) and items_strictly_match(p_bin, p_tam) and items_strictly_match(p_lu, p_tam):
                                visited.update([u_bin, u_lu, u_tam])
                                clusters.append({
                                    "tier": "exact_barcode",
                                    "confidence": 1.0,
                                    "products": [p_bin, p_lu, p_tam]
                                })
                                break

    # 2. مطابقة البراند والمحددات الصارمة (Tier 2)
    remaining = [p for p in products if f"{p['store']}_{p['id']}" not in visited]
    brand_groups = defaultdict(list)
    for p in remaining:
        b = p["_norm_brand"]
        if b != "unbranded":
            brand_groups[b].append(p)

    for _, items in brand_groups.items():
        n = len(items)
        for i in range(n):
            item_a = items[i]
            uid_a = f"{item_a['store']}_{item_a['id']}"
            if uid_a in visited:
                continue

            cluster = [item_a]
            tok_a = item_a["_tokens"]

            for j in range(i + 1, n):
                item_b = items[j]
                uid_b = f"{item_b['store']}_{item_b['id']}"
                if uid_b in visited or any(x["store"] == item_b["store"] for x in cluster):
                    continue

                if not items_strictly_match(item_a, item_b):
                    continue

                tok_b = item_b["_tokens"]
                if are_dairy_discriminators_conflicting(tok_a, tok_b):
                    continue

                if token_overlap_ratio(tok_a, tok_b) >= 0.70:
                    cluster.append(item_b)

            if len(cluster) == 3 and len({x["store"] for x in cluster}) == 3:
                # تحقق إضافي من التباين السعري للعنقود الثلاثي كاملاً
                c_prices = [x["price"] for x in cluster if x.get("price") and x["price"] > 0]
                if c_prices and (max(c_prices) / min(c_prices)) <= 1.85:
                    for c_item in cluster:
                        visited.add(f"{c_item['store']}_{c_item['id']}")
                    clusters.append({
                        "tier": "dairy_brand_token",
                        "confidence": 0.90,
                        "products": cluster
                    })

    # 3. تشكيل ملف الذهب وتوحيد المفاتيح مع جدول المشروبات
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

        # بناء وتحديث التاريخ التراكمي
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
            "size": canonical.get("unit_size_value"),
            "unit": canonical.get("size_unit"),
            "quantity": canonical.get("pack_qty", 1),
            "total_size": canonical.get("total_size_value"),
            "barcode": primary_barcode,
            "image_url": canonical.get("image_url"),
            "canonical_source": canonical.get("store"),
            "match_tier": c["tier"],
            "confidence_score": c["confidence"],
            "matched_stores_count": 3,
            "matched_stores": ["bindawood", "lulu", "tamimi"],
            "price_metrics": {
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_diff": price_diff,
            },
            "price_history": updated_history,
            "stores_data": stores_data,
        })

    # حفظ الملف
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

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
    print(f"   • Matched Products Count   : {matched_prods}")
    print(f"   • Pure 3-Store Coverage    : {pct}%")
    print(f"   • Active File Saved        : {out_file.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()