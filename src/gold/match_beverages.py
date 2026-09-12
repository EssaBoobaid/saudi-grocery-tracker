"""Gold Layer: Tri-Store Exclusive Beverage Matching Engine (BinDawood + Panda + Tamimi).

Applies:
  - Exact Barcode Matching (Tier 1)
  - GS1 Company Prefix + Pack/Volume Matching (Tier 2)
  - Brand + Strict Total Volume & Pack Quantity + Token Overlap (Tier 3)
  - Strict Flavor & Variant Guards (Plain vs Flavored & Cross-Flavor Exclusion)
  - Trio Strict Validation (Prevents graph transitivity false positives)
  - Filters strictly for 3-Store Matches (BinDawood + Panda + Tamimi)
  - Outlier Price Guard
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any
from datetime import datetime, timezone


BASE_DIR = Path(__file__).resolve().parents[2]
SILVER_DIR = BASE_DIR / "data" / "silver"
GOLD_DIR = BASE_DIR / "data" / "gold"
STORES = ["bindawood", "panda", "tamimi"]

FLUFF_WORDS = {
    "fresh", "pure", "premium", "quality", "original", "natural", "classic",
    "plastic", "bottle", "bot", "tetra", "pack", "packet", "box", "can", "cans",
    "tray", "bag", "pouch", "drink", "product", "taste", "style", "offer", "promo",
    "soft", "carbonated", "flavoured", "flavored",
    "طازج", "طازجة", "طبيعي", "بلاستيك", "علبة", "قارورة", "كرتون", "عرض", "شراب", "مشروب", "غازي"
}

BEVERAGE_SYNONYMS = {
    "zero": "diet_var",
    "diet": "diet_var",
    "max": "diet_var",
    "light": "diet_var",
    "lite": "diet_var",
    "دايت": "diet_var",
    "زيرو": "diet_var",
    "ماكس": "diet_var",
    "لايت": "diet_var",
    "regular": "regular_var",
    "عادي": "regular_var",
    "lemon": "lemon_flavor",
    "lime": "lemon_flavor",
    "ليمون": "lemon_flavor",
    "pomegranate": "pom_flavor",
    "رمان": "pom_flavor",
    "punch": "punch_var",
    "mixed": "punch_var",
    "مشكل": "punch_var",
    "فواكه": "punch_var",
    "orange": "orange_flavor",
    "برتقال": "orange_flavor",
    "apple": "apple_flavor",
    "تفاح": "apple_flavor",
    "mango": "mango_flavor",
    "مانجو": "mango_flavor",
    "berry": "berry_flavor",
    "raspberry": "berry_flavor",
    "strawberry": "berry_flavor",
    "توت": "berry_flavor",
    "فراولة": "berry_flavor",
    "peach": "peach_flavor",
    "خوخ": "peach_flavor",
    "mojito": "mojito_flavor",
    "موهيتو": "mojito_flavor",
    "mint": "mint_flavor",
    "نعناع": "mint_flavor",
    "soda": "plain_soda",
    "صودا": "plain_soda",
    "mastic": "mastic_flavor",
    "مستكة": "mastic_flavor",
}

# قائمة النكهات المحددة
ALL_FLAVORS = {
    "lemon_flavor", "pom_flavor", "punch_var", "orange_flavor",
    "apple_flavor", "mango_flavor", "berry_flavor", "peach_flavor",
    "mojito_flavor", "mint_flavor", "mastic_flavor"
}

BEVERAGE_DISCRIMINATORS = [
    {"diet_var", "regular_var"},
    ALL_FLAVORS,
    {"sparkling", "still"},
]


def normalize_barcode(code: Any) -> str:
    cleaned = re.sub(r"\D", "", str(code or "").strip())
    stripped = cleaned.lstrip("0")
    return stripped if len(stripped) >= 7 else cleaned


def get_canonical_barcodes(barcodes: list[Any]) -> set[str]:
    res = set()
    for b in barcodes:
        norm = normalize_barcode(b)
        if norm:
            res.add(norm)
    return res


def get_barcode_prefixes(barcodes: list[Any], prefix_len: int = 8) -> set[str]:
    prefixes = set()
    for b in barcodes:
        norm = normalize_barcode(b)
        if len(norm) >= prefix_len:
            prefixes.add(norm[:prefix_len])
    return prefixes


def get_barcode_families(barcodes: list[Any]) -> set[str]:
    return {
        normalized[:-1]
        for barcode in barcodes
        if len(normalized := normalize_barcode(barcode)) >= 8
    }


def full_name_similarity(p1: dict, p2: dict) -> float:
    def normalized_name(product: dict) -> str:
        value = f"{product.get('name_en') or ''} {product.get('name_ar') or ''}".lower()
        value = re.sub(
            r"\b(ml|ltr|liter|litre|pack|bottle|can|cans|drink|beverage|soft|carbonated|fresh|original|offer|promo)\b",
            " ",
            value,
        )
        value = re.sub(r"\d+(?:\.\d+)?", " ", value)
        return re.sub(r"[^a-z\u0621-\u064a]+", " ", value).strip()

    left, right = normalized_name(p1), normalized_name(p2)
    if not left or not right:
        return 0.0

    left_tokens, right_tokens = set(left.split()), set(right.split())
    overlap = (
        len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
        if left_tokens and right_tokens
        else 0.0
    )
    return max(SequenceMatcher(None, left, right).ratio(), overlap)


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
        mapped = BEVERAGE_SYNONYMS.get(w, w)
        if mapped not in FLUFF_WORDS:
            tokens.add(mapped)
    return tokens


def token_overlap_ratio(tok_a: set[str], tok_b: set[str]) -> float:
    if not tok_a or not tok_b:
        return 0.0
    common = tok_a.intersection(tok_b)
    shorter = min(len(tok_a), len(tok_b))
    return len(common) / shorter if shorter > 0 else 0.0


def are_discriminators_conflicting(tok_a: set[str], tok_b: set[str]) -> bool:
    """فحص صارم للتضارب بين النكهات والأنواع (بما في ذلك منتج بنكهة ضد منتج سادة)."""
    # 1. فحص المجموعات المتضاربة الكلاسيكية
    for group in BEVERAGE_DISCRIMINATORS:
        inter_a = tok_a.intersection(group)
        inter_b = tok_b.intersection(group)
        if inter_a and inter_b and inter_a != inter_b:
            return True

    # 2. فحص: منتج يحتوي نكهة صريحة ضد منتج لا يحتوي أي نكهة (مثل ماء ليمون ضد ماء سادة، أو صودا رمان ضد صودا سادة)
    flavors_a = tok_a.intersection(ALL_FLAVORS)
    flavors_b = tok_b.intersection(ALL_FLAVORS)
    if (flavors_a and not flavors_b) or (flavors_b and not flavors_a):
        return True

    # 3. فحص الدايت ضد العادي الصريح أو الضمني
    if ("diet_var" in tok_a and "diet_var" not in tok_b) or ("diet_var" in tok_b and "diet_var" not in tok_a):
        # إذا كان أحدهما دايت والآخر ليس دايت إطلاقاً -> تعارض
        return True

    return False


def packages_strictly_match(p1: dict, p2: dict) -> bool:
    pr1, pr2 = p1.get("price"), p2.get("price")
    
    if pr1 and pr2 and pr1 > 0 and pr2 > 0:
        ratio = max(pr1, pr2) / min(pr1, pr2)
        if ratio > 1.55:  # يمنع دمج منتج بـ 29 مع منتج بـ 47 (النسبة 1.59)
            return False

    q1 = p1.get("pack_qty") or 1
    q2 = p2.get("pack_qty") or 1
    if q1 != q2:
        return False

    v1 = p1.get("total_size_value")
    v2 = p2.get("total_size_value")
    u1 = p1.get("size_unit")
    u2 = p2.get("size_unit")

    if v1 and v2:
        if u1 != u2:
            return False
        return (abs(v1 - v2) / max(v1, v2)) <= 0.05

    return True


def three_store_packages_match(prods: list[dict[str, Any]]) -> bool:
    """التحقق الصارم من كل الأزواج المتقابلة داخل الثلاثي لمنع أخطاء التعدي."""
    pairs = ((prods[0], prods[1]), (prods[0], prods[2]), (prods[1], prods[2]))
    for left, right in pairs:
        if are_discriminators_conflicting(left["_tokens"], right["_tokens"]):
            return False
        if not packages_strictly_match(left, right):
            return False

    prices = [p["price"] for p in prods if p.get("price") and p["price"] > 0]
    return bool(prices) and max(prices) / min(prices) <= 1.8


def find_barcode_family_supplemental_clusters(
    products: list[dict[str, Any]],
    used_uids: set[str],
) -> list[tuple[list[dict[str, Any]], str]]:
    additions: list[tuple[list[dict[str, Any]], str]] = []

    by_brand = defaultdict(lambda: defaultdict(list))
    for product in products:
        uid = f"{product['store']}_{product['id']}"
        if uid not in used_uids and product["_norm_brand"] != "unbranded":
            by_brand[product["_norm_brand"]][product["store"]].append(product)

    candidates: list[tuple[list[dict[str, Any]], str, float]] = []
    for store_groups in by_brand.values():
        if not all(store_groups[store] for store in STORES):
            continue
        for trio in (
            [bindawood, panda, tamimi]
            for bindawood in store_groups["bindawood"]
            for panda in store_groups["panda"]
            for tamimi in store_groups["tamimi"]
        ):
            if not three_store_packages_match(trio):
                continue
            similarities = [
                full_name_similarity(left, right)
                for left, right in ((trio[0], trio[1]), (trio[0], trio[2]), (trio[1], trio[2]))
            ]
            min_similarity = min(similarities)
            families = [product["_barcode_families"] for product in trio]
            pair_links = sum(
                bool(families[i].intersection(families[j]))
                for i, j in ((0, 1), (0, 2), (1, 2))
            )
            common_family = set.intersection(*families)

            if common_family and min_similarity >= 0.55:
                candidates.append((trio, "barcode_family_package_match", min_similarity))
            elif pair_links >= 2 and min_similarity >= 0.70:
                candidates.append((trio, "barcode_connected_package_match", min_similarity))

    candidates.sort(key=lambda item: (item[1] != "barcode_family_package_match", -item[2]))
    for trio, tier, _ in candidates:
        trio_uids = {f"{p['store']}_{p['id']}" for p in trio}
        if trio_uids & used_uids:
            continue
        additions.append((trio, tier))
        used_uids.update(trio_uids)

    return additions


def select_canonical_product(prods: list[dict[str, Any]]) -> dict[str, Any]:
    store_priority = {"bindawood": 0, "panda": 1, "tamimi": 2}
    sorted_prods = sorted(prods, key=lambda x: store_priority.get(x["store"], 99))
    return sorted_prods[0]


def load_silver_beverages() -> list[dict[str, Any]]:
    items = []
    for store in STORES:
        path = SILVER_DIR / store / "beverages_clean.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                items.extend(json.load(f))
    return items


def main():
    print("=== جاري تشغيل محرك المطابقة لقسم المشروبات (حصر التطابق الثلاثي 3-STORES) ===")
    products = load_silver_beverages()
    if not products:
        print("[!] لم يتم العثور على ملفات beverages_clean.json في مجلدات السيلفر")
        return

    prod_map = {}
    for p in products:
        uid = f"{p['store']}_{p['id']}"
        prod_map[uid] = p
        p["_norm_barcodes"] = get_canonical_barcodes(p.get("barcodes") or [])
        p["_prefixes"] = get_barcode_prefixes(p.get("barcodes") or [], prefix_len=8)
        p["_barcode_families"] = get_barcode_families(p.get("barcodes") or [])
        full_text = f"{p.get('name_en') or ''} {p.get('name_ar') or ''}"
        p["_tokens"] = extract_core_tokens(full_text)
        p["_norm_brand"] = normalize_brand(p.get("brand"))

    adj = defaultdict(set)
    edge_tier = {}

    n = len(products)

    for i in range(n):
        p1 = products[i]
        u1 = f"{p1['store']}_{p1['id']}"

        for j in range(i + 1, n):
            p2 = products[j]
            if p1["store"] == p2["store"]:
                continue

            u2 = f"{p2['store']}_{p2['id']}"
            edge_key = tuple(sorted([u1, u2]))

            # حارس التضارب الصارم في النكهات والأنواع
            if are_discriminators_conflicting(p1["_tokens"], p2["_tokens"]):
                continue

            # 1. تطابق الباركود (Tier 1)
            common_barcodes = p1["_norm_barcodes"] & p2["_norm_barcodes"]
            if common_barcodes:
                if packages_strictly_match(p1, p2):
                    adj[u1].add(u2)
                    adj[u2].add(u1)
                    edge_tier[edge_key] = "exact_barcode"
                    continue

            # 2. بادئة المصنع (Tier 2)
            common_prefix = p1["_prefixes"] & p2["_prefixes"]
            same_brand = (p1["_norm_brand"] != "unbranded") and (p1["_norm_brand"] == p2["_norm_brand"])

            if common_prefix and same_brand:
                if packages_strictly_match(p1, p2):
                    overlap = token_overlap_ratio(p1["_tokens"], p2["_tokens"])
                    near_barcode_family = any(
                        len(a) >= 8
                        and len(b) >= 8
                        and a[:-1] == b[:-1]
                        for a in p1["_norm_barcodes"]
                        for b in p2["_norm_barcodes"]
                    )

                    if overlap >= 0.40 or near_barcode_family:
                        adj[u1].add(u2)
                        adj[u2].add(u1)
                        edge_tier[edge_key] = (
                            "near_barcode_package_match"
                            if near_barcode_family and overlap < 0.40
                            else "gs1_prefix_match"
                        )
                        continue

            # 3. تطابق الماركة والنصوص (Tier 3)
            if same_brand and packages_strictly_match(p1, p2):
                overlap = token_overlap_ratio(p1["_tokens"], p2["_tokens"])
                if overlap >= 0.60:
                    adj[u1].add(u2)
                    adj[u2].add(u1)
                    edge_tier[edge_key] = "brand_package_token"

    # دمج العناقيد
    visited = set()
    raw_clusters = []

    for uid in prod_map:
        if uid in visited or uid not in adj:
            continue

        comp = []
        queue = [uid]
        visited.add(uid)

        while queue:
            curr = queue.pop(0)
            comp.append(prod_map[curr])
            for neighbor in adj[curr]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        canonical = select_canonical_product(comp)
        canon_barcodes = canonical["_norm_barcodes"]

        store_records = {}
        by_store = defaultdict(list)
        for item in comp:
            by_store[item["store"]].append(item)

        for st, items in by_store.items():
            if len(items) == 1:
                store_records[st] = items[0]
            else:
                barcode_matching_items = [it for it in items if (it["_norm_barcodes"] & canon_barcodes)]
                if barcode_matching_items:
                    store_records[st] = barcode_matching_items[0]
                else:
                    base_price = canonical.get("price") or 0.0
                    sorted_by_proximity = sorted(items, key=lambda it: abs((it.get("price") or 0.0) - base_price))
                    store_records[st] = sorted_by_proximity[0]

        # فحص صارم: هل تتوفر المتاجر الثلاثة وهل تخلو أزواجها من أي تضارب نكهات؟
        if len(store_records) == 3:
            cluster_prods = list(store_records.values())
            if three_store_packages_match(cluster_prods):
                raw_clusters.append(cluster_prods)

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    used_uids = {
        f"{product['store']}_{product['id']}"
        for cluster in raw_clusters
        for product in cluster
    }
    supplemental_tiers = {}
    for cluster, tier in find_barcode_family_supplemental_clusters(products, used_uids):
        raw_clusters.append(cluster)
        supplemental_tiers[frozenset(
            f"{product['store']}_{product['id']}" for product in cluster
        )] = tier

    formatted = []

    for prods in raw_clusters:
        canonical = select_canonical_product(prods)

        uids = [f"{x['store']}_{x['id']}" for x in prods]
        tier_found = supplemental_tiers.get(frozenset(uids), "brand_package_token")
        if tier_found == "brand_package_token":
            for i in range(len(uids)):
                for j in range(i + 1, len(uids)):
                    k = tuple(sorted([uids[i], uids[j]]))
                    if k in edge_tier:
                        if edge_tier[k] == "exact_barcode":
                            tier_found = "exact_barcode"
                            break
                        elif edge_tier[k] == "gs1_prefix_match":
                            tier_found = "gs1_prefix_match"
                        elif (
                            edge_tier[k] == "near_barcode_package_match"
                            and tier_found == "brand_package_token"
                        ):
                            tier_found = "near_barcode_package_match"

        confidence_map = {
            "exact_barcode": 1.0,
            "gs1_prefix_match": 0.94,
            "near_barcode_package_match": 0.92,
            "barcode_family_package_match": 0.96,
            "barcode_connected_package_match": 0.93,
            "brand_package_token": 0.88,
        }

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

        formatted.append({
            "product_name_ar": canonical.get("name_ar"),
            "product_name_en": canonical.get("name_en"),
            "brand": canonical.get("brand"),
            "category": "beverages",
            "size": canonical.get("unit_size_value"),
            "unit": canonical.get("size_unit"),
            "quantity": canonical.get("pack_qty", 1),
            "total_size": canonical.get("total_size_value"),
            "barcode": primary_barcode,
            "image_url": canonical.get("image_url"),
            "canonical_source": canonical.get("store"),
            "match_tier": tier_found,
            "confidence_score": confidence_map.get(tier_found, 0.85),
            "matched_stores_count": 3,
            "matched_stores": ["bindawood", "panda", "tamimi"],
            "price_metrics": {
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "price_diff": price_diff,
            },
            "stores_data": stores_data,
        })

    out_file = GOLD_DIR / "matched_beverages.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    total_prods = len(products)
    matched_prods = len(formatted) * 3
    pct = round(matched_prods / total_prods * 100, 2) if total_prods else 0.0

    print("\n" + "=" * 60)
    print("📊 GOLD BEVERAGES REPORT (EXCLUSIVE 3-STORE ONLY):")
    print(f"   • Total Products In Silver : {total_prods}")
    print(f"   • 3-Store Matches (Clusters): {len(formatted)} clusters")
    print(f"   • 2-Store Matches          : 0 (Excluded completely)")
    print(f"   • Matched Products Count   : {matched_prods}")
    print(f"   • Pure 3-Store Coverage    : {pct}%")
    print(f"   • Output Saved To          : {out_file.name}")
    print("=" * 60)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    archive_dir = GOLD_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"matched_beverages_{today_str}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()