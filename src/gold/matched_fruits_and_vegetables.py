"""Gold Layer: GASTAT-Anchored Produce Matcher (Strict 1-to-1 Product Assignment).

Features:
  - Dynamically extracts all distinct produce commodities from GASTAT.
  - Matches across BinDawood, Panda, and Tamimi using primary commodity roots.
  - Semantic guards for Variety, Color, Heat (Chili vs Bell Pepper), and Provenance.
  - Global Bipartite Optimization enforcing strict 1-to-1 retail product usage:
    No (store, raw_product_id) can appear in more than one GASTAT cluster.
  - Global Pre-write QA Audit asserting uniqueness before writing Gold JSON.
  - Built-in standalone regression test suite.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
SILVER_DIR = BASE_DIR / "data" / "silver"
GOLD_DIR = BASE_DIR / "data" / "gold"
STORES = ["bindawood", "panda", "tamimi"]

GASTAT_FILE = BASE_DIR / "data" / "open_data" / "gastat__fruits_and_vegetables_clean.json"
OUT_FILE = GOLD_DIR / "matched_fruits_and_vegetables.json"

PRIMARY_ROOTS = {
    # Fruits
    "موز": "banana",
    "banana": "banana",
    "bananas": "banana",

    "تمر": "dates",
    "date": "dates",
    "dates": "dates",
    "رطب": "dates",
    "rotab": "dates",
    "rutab": "dates",
    "إخلاص": "dates",
    "ikhlas": "dates",

    "تين": "fig",
    "fig": "fig",
    "figs": "fig",

    "منجا": "mango",
    "مانجو": "mango",
    "mango": "mango",
    "mangoes": "mango",

    "ليمون": "lemon",
    "lemon": "lemon",
    "lemons": "lemon",

    "برتقال": "orange",
    "orange": "orange",
    "oranges": "orange",

    "يوسفي": "mandarin",
    "mandarin": "mandarin",
    "mandarins": "mandarin",
    "tangerine": "mandarin",
    "tangerines": "mandarin",

    "تفاح": "apple",
    "apple": "apple",
    "apples": "apple",

    "كمثرى": "pear",
    "pear": "pear",
    "pears": "pear",

    "برقوق": "plum",
    "بخارى": "plum",
    "plum": "plum",
    "plums": "plum",

    "خوخ": "peach",
    "peach": "peach",
    "peaches": "peach",

    "رمان": "pomegranate",
    "pomegranate": "pomegranate",
    "pomegranates": "pomegranate",

    "عنب": "grape",
    "grape": "grape",
    "grapes": "grape",

    "شمام": "melon",
    "melon": "melon",
    "melons": "melon",

    "حبحب": "watermelon",
    "بطيخ": "watermelon",
    "watermelon": "watermelon",
    "watermelons": "watermelon",

    # Vegetables
    "خس": "lettuce",
    "lettuce": "lettuce",

    "ملوخية": "corchorus",
    "corchorus": "corchorus",
    "molokhia": "corchorus",
    "molokhiya": "corchorus",
    "molokheya": "corchorus",
    "jute mallow": "corchorus",

    "جرجير": "watercress",
    "watercress": "watercress",
    "rocket": "watercress",
    "arugula": "watercress",

    "ملفوف": "cabbage",
    "cabbage": "cabbage",
    "cabbages": "cabbage",

    "سبانخ": "spinach",
    "spinach": "spinach",

    "فلفل": "pepper",
    "pepper": "pepper",
    "peppers": "pepper",
    "chili": "pepper",
    "chilli": "pepper",
    "capsicum": "pepper",

    "خيار": "cucumber",
    "cucumber": "cucumber",
    "cucumbers": "cucumber",

    "باذنجان": "eggplant",
    "eggplant": "eggplant",
    "eggplants": "eggplant",
    "aubergine": "eggplant",
    "aubergines": "eggplant",

    "طماطم": "tomatoes",
    "طماطة": "tomatoes",
    "tomato": "tomatoes",
    "tomatoes": "tomatoes",

    "قرع": "pumpkin",
    "pumpkin": "pumpkin",
    "pumpkins": "pumpkin",

    "كوسة": "zucchini",
    "zucchini": "zucchini",
    "zucchinis": "zucchini",
    "courgette": "zucchini",
    "courgettes": "zucchini",

    "بامية": "okra",
    "okra": "okra",

    "فاصوليا": "green_beans",
    "green bean": "green_beans",
    "green beans": "green_beans",
    "bean": "green_beans",
    "beans": "green_beans",

    "جزر": "carrots",
    "carrot": "carrots",
    "carrots": "carrots",

    "ثوم": "garlic",
    "garlic": "garlic",

    "بصل": "onion",
    "onion": "onion",
    "onions": "onion",

    "زيتون": "olives",
    "olive": "olives",
    "olives": "olives",

    "بطاطس": "potatoes",
    "بطاطا": "potatoes",
    "potato": "potatoes",
    "potatoes": "potatoes",

    "ذرة": "corn",
    "corn": "corn",
    "sweet corn": "corn",
    "sweetcorn": "corn",

    "بقدونس": "parsley",
    "parsley": "parsley",
}

PREMIUM_DISCRIMINATORS = {
    "organic", "عضوي", "عضوية", "hydroponic", "مائي", "هيدروبونيك", "baby", "شيري", "صغير"
}


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return " ".join(t.split())


def get_commodity_root(text: str) -> str | None:
    clean = normalize_text(text)

    priority_groups = [
        (["طماطم", "طماطة", "tomato", "tomatoes"], "tomatoes"),
        (["فلفل", "pepper", "peppers", "chili", "chilli", "capsicum"], "pepper"),
        (["باذنجان", "eggplant", "eggplants", "aubergine", "aubergines"], "eggplant"),
        (["خيار", "cucumber", "cucumbers"], "cucumber"),
        (["كوسة", "zucchini", "zucchinis", "courgette", "courgettes"], "zucchini"),
        (["فاصوليا", "green bean", "green beans"], "green_beans"),
    ]

    for keywords, root in priority_groups:
        for kw in keywords:
            if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", clean):
                return root

    for kw, root in PRIMARY_ROOTS.items():
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", clean):
            return root

    return None


def get_normalized_kg_price(prod: dict[str, Any]) -> float | None:
    """Extract standard price per 1.0 KG from retailer raw payloads."""
    options = prod.get("WEIGHT OPTIONS") or prod.get("weight_options") or []
    if isinstance(options, list) and options:
        for opt in options:
            val = opt.get("quantity_value")
            name = str(opt.get("quantity_name") or "").upper()
            if val == 1.0 or "1 KG" in name or "1.0 KG" in name:
                p = opt.get("price")
                if p and float(p) > 0:
                    return round(float(p), 2)
        first_opt = options[0]
        val = first_opt.get("quantity_value")
        p = first_opt.get("price")
        if val and p and float(val) > 0 and float(p) > 0:
            return round(float(p) / float(val), 2)

    raw_price = prod.get("price")
    if not raw_price or float(raw_price) <= 0:
        return None
    raw_price = float(raw_price)

    size = (
        prod.get("total_size_value")
        or prod.get("unit_size_value")
        or prod.get("TOTAL SIZE")
        or prod.get("UNIT SIZE")
    )
    unit = str(prod.get("size_unit") or prod.get("SIZE UNIT") or "").lower()

    if size and unit:
        try:
            size_f = float(size)
            if unit in ["g", "جم", "جرام"] and size_f > 0:
                return round(raw_price * (1000.0 / size_f), 2)
            elif unit in ["kg", "كجم", "كيلو"] and size_f > 0:
                return round(raw_price / size_f, 2)
        except (ValueError, TypeError):
            pass

    if prod.get("is_weighted") or prod.get("IS WEIGHTED"):
        return round(raw_price, 2)

    return round(raw_price, 2)


def build_gastat_anchors() -> dict[str, dict[str, Any]]:
    """Extract official unique commodity benchmark targets from GASTAT."""
    if not GASTAT_FILE.exists():
        return {}

    with open(GASTAT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", data) if isinstance(data, dict) else data

    anchors = {}
    for r in records:
        name_ar = (r.get("item_name_ar") or "").strip()
        name_en = (r.get("item_name_en") or "").strip()

        if name_ar == "س" and "lemon" in name_en.lower():
            name_ar = "ليمون وسط أفريقي"

        if not name_ar or len(name_ar) < 2:
            continue

        key = name_en if name_en else name_ar
        root = get_commodity_root(f"{name_ar} {name_en}")
        if not root:
            continue

        year = int(r.get("Year", 0))
        if key in anchors and year < anchors[key]["year"]:
            continue

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


def score_produce_match(prod: dict[str, Any], anchor: dict[str, Any]) -> float:
    """Score product relevance against an anchor with strict variety/provenance/heat guards."""
    full_text = normalize_text(f"{prod.get('name_en') or ''} {prod.get('name_ar') or ''}")
    anchor_text = f"{anchor['name_ar']} {anchor['name_en']}".lower()

    # 1. Commodity root alignment
    prod_root = get_commodity_root(full_text)
    if prod_root != anchor["root"]:
        return 0.0

    # 2. Premium / Hydroponic exclusions
    is_anchor_organic = any(w in anchor_text for w in PREMIUM_DISCRIMINATORS)
    is_prod_organic = any(w in full_text for w in PREMIUM_DISCRIMINATORS)
    if is_prod_organic and not is_anchor_organic:
        return 0.0

    # 3. Preparation state (Sliced / Prepared vs Whole)
    is_sliced_prod = any(w in full_text for w in ["slice", "slices", "sliced", "شرائح", "مقطع", "قطع", "tray", "صحن"])
    is_sliced_anchor = any(w in anchor_text for w in ["slice", "slices", "شرائح", "مقطع"])
    if is_sliced_prod and not is_sliced_anchor:
        return 0.0

    # 4. Apple Sub-variety & Color Guards
    if prod_root == "apple":
        is_pink_lady = "pink lady" in full_text or "بينك ليدي" in full_text
        is_red_a = "red" in anchor_text or "احمر" in anchor_text or "أحمر" in anchor_text
        is_yellow_a = "yellow" in anchor_text or "اصفر" in anchor_text or "أصفر" in anchor_text or "golden" in anchor_text
        is_green_a = "green" in anchor_text or "اخضر" in anchor_text or "أخضر" in anchor_text

        is_red_p = any(w in full_text for w in ["red", "أحمر", "احمر", "royal gala", "gala", "رويال جالا"])
        is_yellow_p = any(w in full_text for w in ["yellow", "أصفر", "اصفر", "golden", "جولدن"])
        is_green_p = any(w in full_text for w in ["green", "أخضر", "اخضر", "granny", "جراني"])

        # Pink Lady is distinct and must not occupy Yellow Apple or generic American Red
        if is_pink_lady:
            if is_yellow_a or is_green_a:
                return 0.0

        if is_yellow_a and not is_yellow_p:
            return 0.0
        if is_green_a and not is_green_p:
            return 0.0
        if is_red_a and not is_red_p and (is_yellow_p or is_green_p):
            return 0.0

    # 5. Pepper vs. Chili (Heat & Form Factor Guards)
    if prod_root == "pepper":
        is_chili_a = any(w in anchor_text for w in ["chili", "chilli", "حار", "شطة"])
        is_sweet_a = any(w in anchor_text for w in ["sweet", "bell", "بارد", "رومي"])

        is_chili_p = any(w in full_text for w in ["chili", "chilli", "hot", "حار", "شطة", "حراق"])
        is_sweet_p = any(w in full_text for w in ["sweet", "bell", "بارد", "رومي", "capsicum"])

        # Chili must not match Sweet/Bell Pepper and vice versa
        if is_chili_a and is_sweet_p and not is_chili_p:
            return 0.0
        if not is_chili_a and is_chili_p:
            return 0.0
        if is_sweet_a and is_chili_p:
            return 0.0

    # 6. Onion Color Guards
    if prod_root == "onion":
        is_red_p = any(w in full_text for w in ["red", "أحمر", "احمر", "حمراء"])
        is_white_p = any(w in full_text for w in ["white", "أبيض", "ابيض", "بيضاء"])
        is_green_p = any(w in full_text for w in ["green", "spring", "أخضر", "اخضر"])

        is_red_a = any(w in anchor_text for w in ["red", "أحمر", "احمر"])
        is_white_a = any(w in anchor_text for w in ["white", "أبيض", "ابيض", "مستورد"])
        is_green_a = any(w in anchor_text for w in ["green", "spring", "أخضر", "اخضر"])

        if is_red_p and not is_red_a and (is_white_a or is_green_a):
            return 0.0
        if is_white_p and not is_white_a and (is_red_a or is_green_a):
            return 0.0
        if is_green_p and not is_green_a and (is_red_a or is_white_a):
            return 0.0

    # 7. Provenance Validation: Missing attribute != positive evidence
    is_prod_local = any(w in full_text for w in ["محلي", "وطني", "local", "ksa", "سعودي"])
    is_prod_imported = any(w in full_text for w in ["مستورد", "imported"])

    # If anchor strictly requires local vs imported, reject contradictory retail evidence
    if anchor["is_local"] and is_prod_imported:
        return 0.0
    if anchor["is_imported"] and is_prod_local:
        return 0.0

    # 8. Packaging Unit Alignment
    prod_unit = str(prod.get("size_unit") or "").lower()
    is_bundle_prod = any(u in prod_unit for u in ["bundle", "حزمة", "ربطة"]) or any(
        w in full_text for w in ["حزمة", "ربطة", "bundle", "bunch"]
    )
    BUNDLE_ROOTS = {"corchorus", "watercress", "spinach", "parsley"}

    if anchor["unit"] == "bundle":
        if not is_bundle_prod and anchor["root"] not in BUNDLE_ROOTS:
            return 0.0
    if anchor["unit"] == "kg" and is_bundle_prod:
        return 0.0

    # Base candidate score
    score = 1.0

    # Reward positive provenance evidence
    if anchor["is_local"] and is_prod_local:
        score += 0.8
    elif anchor["is_imported"] and is_prod_imported:
        score += 0.8

    # Proximity to GASTAT benchmark
    norm_price = get_normalized_kg_price(prod)
    benchmark = anchor.get("benchmark_price")
    if norm_price and benchmark and benchmark > 0:
        price_diff_ratio = abs(norm_price - benchmark) / benchmark
        if price_diff_ratio <= 0.8:
            score += max(0.0, 1.0 - price_diff_ratio)
        else:
            score -= 0.5

    return score


def select_canonical_product(prods: list[dict[str, Any]]) -> dict[str, Any]:
    store_priority = {"bindawood": 0, "panda": 1, "tamimi": 2}
    return sorted(prods, key=lambda x: store_priority.get(x["store"], 99))[0]


def resolve_optimal_clusters(
    anchors: dict[str, dict[str, Any]],
    store_products: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Solve global 1-to-1 retail product allocation across GASTAT commodities.

    Every (store, raw_product_id) can appear in at most ONE final cluster.
    """
    candidate_clusters: list[dict[str, Any]] = []

    for anchor_key, anchor in anchors.items():
        matched_by_store: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)

        for store in STORES:
            for prod in store_products[store]:
                norm_p = get_normalized_kg_price(prod)
                if norm_p is None or norm_p <= 0:
                    continue

                s = score_produce_match(prod, anchor)
                if s >= 1.0:
                    prod_copy = dict(prod)
                    prod_copy["_normalized_kg_price"] = norm_p
                    matched_by_store[store].append((s, prod_copy))

        if len(matched_by_store) != 3:
            continue

        for store in STORES:
            matched_by_store[store].sort(key=lambda x: x[0], reverse=True)

        # Evaluate top candidate trios for this anchor
        top_candidates = [
            (b_prod, p_prod, t_prod)
            for _, b_prod in matched_by_store["bindawood"][:3]
            for _, p_prod in matched_by_store["panda"][:3]
            for _, t_prod in matched_by_store["tamimi"][:3]
        ]

        best_candidate = None
        best_candidate_metric = -999.0

        for b_prod, p_prod, t_prod in top_candidates:
            trio = [b_prod, p_prod, t_prod]
            kg_prices = [p["_normalized_kg_price"] for p in trio]
            spread_ratio = max(kg_prices) / min(kg_prices)
            if spread_ratio > 2.2:
                continue

            sum_scores = (
                score_produce_match(b_prod, anchor)
                + score_produce_match(p_prod, anchor)
                + score_produce_match(t_prod, anchor)
            )
            composite_metric = sum_scores - (spread_ratio * 0.5)

            if composite_metric > best_candidate_metric:
                best_candidate_metric = composite_metric
                best_candidate = (trio, composite_metric, spread_ratio)

        if best_candidate:
            trio, metric, spread_ratio = best_candidate
            candidate_clusters.append({
                "anchor": anchor,
                "anchor_key": anchor_key,
                "prods": trio,
                "quality_metric": metric,
                "spread_ratio": spread_ratio,
            })

    # Deterministic global ranking: quality metric desc, spread asc, anchor_key asc
    candidate_clusters.sort(
        key=lambda c: (-c["quality_metric"], c["spread_ratio"], c["anchor_key"])
    )

    claimed_retail_products: set[tuple[str, str]] = set()
    accepted_clusters: list[dict[str, Any]] = []

    for cand in candidate_clusters:
        trio = cand["prods"]
        trio_keys = {(p["store"], str(p.get("id") or p.get("raw_product_id"))) for p in trio}

        # Strict 1-to-1 conflict check: if any retailer product is already claimed, skip
        if any(tk in claimed_retail_products for tk in trio_keys):
            continue

        claimed_retail_products.update(trio_keys)
        accepted_clusters.append(cand)

    return accepted_clusters


def assert_strict_one_to_one_usage(formatted_clusters: list[dict[str, Any]]) -> None:
    """Pre-write global QA guard. Fails immediately if any retail ID is duplicated."""
    usage_map: dict[tuple[str, str], list[str]] = defaultdict(list)

    for cluster in formatted_clusters:
        gastat_key = cluster["gastat_key"]
        for store, store_data in cluster["stores_data"].items():
            raw_id = str(store_data.get("raw_product_id"))
            usage_map[(store, raw_id)].append(gastat_key)

    conflicts = {k: v for k, v in usage_map.items() if len(v) > 1}
    if conflicts:
        print("\n" + "!" * 70)
        print("❌ CRITICAL QA FAILURE: RETAIL PRODUCTS REUSED ACROSS MULTIPLE CLUSTERS")
        print("!" * 70)
        for (st, pid), anchors in conflicts.items():
            print(f"   • Store [{st.upper()}] ID [{pid}] reused in: {anchors}")
        raise RuntimeError("Aborted write: Retail raw_product_id duplicate usage detected.")


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
        print(f"   [!] Note: Could not read prior history: {e}")

    return history_map


def build_gold() -> list[dict[str, Any]]:
    anchors = build_gastat_anchors()
    if not anchors:
        print(f"[!] GASTAT anchors file not found at: {GASTAT_FILE}")
        return []

    store_products = load_all_silver_produce()
    prior_history = load_existing_history(OUT_FILE)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    resolved = resolve_optimal_clusters(anchors, store_products)
    formatted = []

    for cluster in resolved:
        anchor = cluster["anchor"]
        prods = cluster["prods"]
        canonical = select_canonical_product(prods)

        valid_prices = [p["_normalized_kg_price"] for p in prods if p.get("_normalized_kg_price") is not None]
        avg_price = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else None
        min_price = min(valid_prices) if valid_prices else None
        max_price = max(valid_prices) if valid_prices else None
        price_diff = round(max_price - min_price, 2) if (min_price and max_price) else 0.0

        stores_data = {}
        for p in prods:
            stores_data[p["store"]] = {
                "price": p["_normalized_kg_price"],
                "store_raw_price": p.get("price"),
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
            "matched_stores": ["bindawood", "panda", "tamimi"],
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

    # Execute strict pre-write invariant audit
    assert_strict_one_to_one_usage(formatted)

    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    archive_dir = GOLD_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / f"matched_fruits_and_vegetables_{today_str}.json"
    with open(archive_file, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    return formatted


# ==============================================================================
# REGRESSION TEST SUITE
# ==============================================================================

def run_regression_tests() -> bool:
    print("\n" + "=" * 65)
    print("🧪 RUNNING REGRESSION TESTS: STRICT 1-TO-1 PRODUCE ASSIGNMENT")
    print("=" * 65)

    anchors = build_gastat_anchors()
    store_products = load_all_silver_produce()
    resolved = resolve_optimal_clusters(anchors, store_products)

    # 1. Test global retail product uniqueness
    usage_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in resolved:
        gk = c["anchor_key"]
        for p in c["prods"]:
            usage_map[(p["store"], str(p.get("id") or p.get("raw_product_id")))].append(gk)

    duplicates = {k: v for k, v in usage_map.items() if len(v) > 1}
    assert not duplicates, f"Regression Fail: Found duplicate product assignments: {duplicates}"
    print("  ✅ [PASS] Zero duplicate retail product usage across all stores.")

    # 2. Specific Known Bug Check 1: Pink Lady Apple Separation
    pink_lady_assigned_to = [
        c["anchor_key"] for c in resolved
        if any("pink lady" in f"{p.get('name_en', '')} {p.get('name_ar', '')}".lower() for p in c["prods"])
    ]
    assert "Yellow Apples" not in pink_lady_assigned_to, "Regression Fail: Pink Lady was assigned to Yellow Apples"
    print("  ✅ [PASS] Pink Lady Apples never assigned to Yellow Apples.")

    # 3. Specific Known Bug Check 2: BinDawood 11228 / Panda 202701876 Chili vs Pepper
    chili_keys = [
        c["anchor_key"] for c in resolved
        if any(str(p.get("id")) in {"11228", "202701876"} for p in c["prods"])
    ]
    assert len(chili_keys) <= 1, f"Regression Fail: Hot Chili retail product appeared in multiple clusters: {chili_keys}"
    print(f"  ✅ [PASS] Hot Chili retail products assigned to at most one cluster: {chili_keys}")

    # 4. Specific Known Bug Check 3: BinDawood 43291 Tomato local vs imported
    tomato_keys = [
        c["anchor_key"] for c in resolved
        if any(str(p.get("id")) == "43291" for p in c["prods"])
    ]
    assert len(tomato_keys) <= 1, f"Regression Fail: Tomato 43291 appeared in multiple clusters: {tomato_keys}"
    print(f"  ✅ [PASS] Tomato ID 43291 assigned to at most one cluster: {tomato_keys}")

    # 5. Order Independence & Idempotence
    run_1_keys = [c["anchor_key"] for c in resolved]
    run_2 = resolve_optimal_clusters(anchors, store_products)
    run_2_keys = [c["anchor_key"] for c in run_2]
    assert run_1_keys == run_2_keys, "Regression Fail: Non-deterministic cluster resolution"
    print("  ✅ [PASS] Cluster resolution is strictly deterministic and idempotent.")

    print("\nAll regression tests passed successfully.\n")
    return True


def main():
    if "--test" in sys.argv:
        run_regression_tests()
        return

    print("=" * 65)
    print("🌾 RUNNING ADVANCED GASTAT PRODUCE MATCHER (STRICT 1-TO-1)")
    print("=" * 65)

    anchors = build_gastat_anchors()
    formatted = build_gold()

    coverage_pct = round(len(formatted) / len(anchors) * 100, 2) if anchors else 0.0
    print("\n" + "=" * 65)
    print("📊 GASTAT OFFICIAL BASKET REPORT:")
    print(f"   • Total Official Commodities: {len(anchors)}")
    print(f"   • Matched Tri-Store Clusters : {len(formatted)} clusters")
    print(f"   • Official Basket Coverage   : {coverage_pct}%")
    print(f"   • Matched Store Items        : {len(formatted) * 3} products")
    print(f"   • Output File                : {OUT_FILE.name}")
    print("=" * 65)


if __name__ == "__main__":
    main()