"""Database Loader Engine for Saudi Grocery Tracker."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from config.settings import DATA_DIR, GOLD_DIR
from src.database.connection import get_connection

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"
GASTAT_FILE = GOLD_DIR / "gastat_fruits_and_vegetables_matched.json"
REFERENCE_DIR = DATA_DIR / "reference"

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def init_schema(conn):
    """Safely apply schema DDL using autocommit to avoid silent rollbacks."""
    if not SCHEMA_FILE.exists():
        print(f"[!] Schema file not found: {SCHEMA_FILE}")
        return

    old_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        print("✓ Applied schema.sql successfully.")
    except Exception as err:
        print(f"[!] Schema initialization message: {err}")
    finally:
        conn.autocommit = old_autocommit


def load_branches(conn):
    branch_files = [
        "bindawood_branches.json",
        "lulu_branches.json",
        "tamimi_branches.json",
    ]
    total_branches = 0
    with conn.cursor() as cur:
        # مسح الفروع القديمة قبل إعادة التعبئة لمنع التكرار
        cur.execute("TRUNCATE TABLE store_branches RESTART IDENTITY;")
        for fname in branch_files:
            fpath = REFERENCE_DIR / fname
            if not fpath.exists():
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                branches = json.load(f)
            for b in branches:
                cur.execute("""
                    INSERT INTO store_branches (brand, city_ar, city_en, name_ar, name_en, map_url)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (
                    b.get("brand"),
                    b.get("city_ar"),
                    b.get("city_en"),
                    b.get("name_ar"),
                    b.get("name_en"),
                    b.get("map_url"),
                ))
                total_branches += 1
    conn.commit()
    print(f"  ✓ Ingested {total_branches} store branches.")


def load_gastat(conn):
    if not GASTAT_FILE.exists():
        print(f"  [!] Missing GASTAT file: {GASTAT_FILE}")
        return

    with open(GASTAT_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    records = payload.get("records", payload) if isinstance(payload, dict) else payload
    commodities_seen = set()
    history_count = 0

    with conn.cursor() as cur:
        for r in records:
            gid = r.get("gastat_id")
            if not gid:
                continue

            if gid not in commodities_seen:
                cur.execute("""
                    INSERT INTO gastat_commodities 
                    (gastat_id, gastat_slug, item_name_ar, item_name_en, unit_ar, unit_en, matched_barcodes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (gastat_id) DO UPDATE SET
                        item_name_ar = EXCLUDED.item_name_ar,
                        item_name_en = EXCLUDED.item_name_en,
                        matched_barcodes = EXCLUDED.matched_barcodes;
                """, (
                    gid,
                    r.get("gastat_slug"),
                    r.get("item_name_ar"),
                    r.get("item_name_en"),
                    r.get("unit_ar"),
                    r.get("unit_en"),
                    r.get("matched_barcodes", []),
                ))
                commodities_seen.add(gid)

            year = int(r.get("Year", 0))
            raw_avg = r.get("Annual average")
            ann_avg = float(raw_avg) if raw_avg and str(raw_avg).strip() else None

            for m in MONTHS:
                m_val = r.get(m)
                if m_val is not None and str(m_val).strip():
                    try:
                        price = float(str(m_val).replace(",", ""))
                        cur.execute("""
                            INSERT INTO gastat_price_history (gastat_id, year, month, price, annual_average)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (gastat_id, year, month) DO UPDATE SET
                                price = EXCLUDED.price,
                                annual_average = EXCLUDED.annual_average;
                        """, (gid, year, m, price, ann_avg))
                        history_count += 1
                    except ValueError:
                        continue

    conn.commit()
    print(f"  ✓ Ingested {len(commodities_seen)} GASTAT commodities ({history_count} price history records).")


def load_gold_category(conn, file_name: str, fallback_cat: str):
    file_path = GOLD_DIR / file_name
    if not file_path.exists():
        print(f"  [!] Missing gold file: {file_name}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with conn.cursor() as cur:
        for item in items:
            cat = item.get("category") or fallback_cat
            barcode = item.get("barcode")
            name_en = item.get("product_name_en")
            name_ar = item.get("product_name_ar")
            gid = item.get("gastat_id")

            cur.execute("""
                SELECT product_id FROM matched_products 
                WHERE (barcode IS NOT NULL AND barcode = %s)
                   OR (product_name_en = %s AND category = %s)
                LIMIT 1;
            """, (barcode, name_en, cat))
            row = cur.fetchone()

            if row:
                prod_id = row[0]
                cur.execute("""
                    UPDATE matched_products SET
                        gastat_id = COALESCE(%s, gastat_id),
                        product_name_ar = COALESCE(%s, product_name_ar),
                        image_url = COALESCE(%s, image_url),
                        matched_stores = %s
                    WHERE product_id = %s;
                """, (gid, name_ar, item.get("image_url"), item.get("matched_stores", []), prod_id))
            else:
                cur.execute("""
                    INSERT INTO matched_products 
                    (gastat_id, category, product_name_ar, product_name_en, brand, barcode, size, unit, quantity, total_size, image_url, canonical_source, match_tier, confidence_score, matched_stores)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING product_id;
                """, (
                    gid,
                    cat,
                    name_ar,
                    name_en,
                    item.get("brand"),
                    barcode,
                    item.get("size"),
                    item.get("unit"),
                    item.get("quantity", 1),
                    item.get("total_size"),
                    item.get("image_url"),
                    item.get("canonical_source"),
                    item.get("match_tier"),
                    item.get("confidence_score"),
                    item.get("matched_stores", []),
                ))
                prod_id = cur.fetchone()[0]

            # تجميع بيانات الأسعار
            price_history = item.get("price_history") or []
            if not price_history:
                metrics = item.get("current_pricing") or item.get("price_metrics") or {}
                if metrics:
                    price_history = [{
                        "date": today_str,
                        "avg_price": metrics.get("avg_price"),
                        "min_price": metrics.get("min_price"),
                        "max_price": metrics.get("max_price"),
                        "gastat_benchmark": metrics.get("gastat_benchmark_price"),
                        "variance": metrics.get("variance_from_benchmark"),
                        "price_diff": metrics.get("price_diff"),
                        "stores_prices": {st: d.get("price") for st, d in item.get("stores_data", {}).items() if "price" in d},
                    }]

            for snap in price_history:
                s_date = snap.get("date") or today_str
                diff = snap.get("price_diff") or (item.get("current_pricing") or item.get("price_metrics") or {}).get("price_diff")
                bench = snap.get("gastat_benchmark") or (item.get("current_pricing") or {}).get("gastat_benchmark_price")
                variance = snap.get("variance") or (item.get("current_pricing") or {}).get("variance_from_benchmark")

                cur.execute("""
                    INSERT INTO product_price_snapshots 
                    (product_id, snapshot_date, avg_price, min_price, max_price, price_diff, gastat_benchmark_price, variance_from_benchmark)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, snapshot_date) DO UPDATE SET
                        avg_price = EXCLUDED.avg_price,
                        min_price = EXCLUDED.min_price,
                        max_price = EXCLUDED.max_price,
                        price_diff = EXCLUDED.price_diff,
                        gastat_benchmark_price = EXCLUDED.gastat_benchmark_price,
                        variance_from_benchmark = EXCLUDED.variance_from_benchmark;
                """, (prod_id, s_date, snap.get("avg_price"), snap.get("min_price"), snap.get("max_price"), diff, bench, variance))

                stores_prices = snap.get("stores_prices", {})
                for store_name, price_val in stores_prices.items():
                    store_meta = item.get("stores_data", {}).get(store_name, {})
                    store_pid = store_meta.get("store_product_id") or store_meta.get("raw_product_id")

                    cur.execute("""
                        INSERT INTO store_item_prices 
                        (product_id, snapshot_date, store_name, store_product_id, price, original_price, discount_amount, discount_percentage, has_discount, image_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (
                        prod_id,
                        s_date,
                        store_name,
                        str(store_pid) if store_pid else None,
                        price_val,
                        store_meta.get("original_price"),
                        store_meta.get("discount_amount"),
                        store_meta.get("discount_percentage"),
                        bool(store_meta.get("has_discount", False)),
                        store_meta.get("image_url"),
                    ))

    conn.commit()
    print(f"  ✓ Ingested {len(items)} items from {file_name}")


def main():
    print("=" * 65)
    print("🐘 RUNNING COMPLETE POSTGRESQL INGESTION")
    print("=" * 65)

    conn = get_connection()
    init_schema(conn)

    print("\n[*] 1. Ingesting Store Branches...")
    load_branches(conn)

    print("\n[*] 2. Ingesting GASTAT Benchmarks...")
    load_gastat(conn)

    print("\n[*] 3. Ingesting Gold Matched Categories...")
    load_gold_category(conn, "matched_beverages.json", "beverages")
    load_gold_category(conn, "matched_dairy_and_eggs.json", "dairy_and_eggs")
    load_gold_category(conn, "matched_fruits_and_vegetables.json", "fruits_and_vegetables")

    conn.close()
    print("\n" + "=" * 65)
    print("✅ DATABASE INGESTION COMPLETED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    main()