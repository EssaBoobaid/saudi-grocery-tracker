"""Snowflake Data Warehouse Loader - Unified Ingestion with GASTAT Benchmark (Deduplicated & Automated)."""

from __future__ import annotations

import getpass
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import snowflake.connector
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]

# تحميل المتغيرات تلقائياً من ملف .env في مسار المشروع الرئيسي
load_dotenv(BASE_DIR / ".env")

GOLD_DIR = BASE_DIR / "data" / "gold"

GOLD_FILES = [
    GOLD_DIR / "matched_dairy_and_eggs.json",
    GOLD_DIR / "matched_beverages.json",
    GOLD_DIR / "matched_fruits_and_vegetables.json",
]

GASTAT_FILE = GOLD_DIR / "gastat_fruits_and_vegetables_matched.json"

SNOWFLAKE_CONFIG = {
    "user": "ESSASA",
    "account": "BZYOXVH-UV32793",
    "host": "BZYOXVH-UV32793.snowflakecomputing.com",
    "warehouse": "COMPUTE_WH",
    "role": "ACCOUNTADMIN",
}


def load_gold_data() -> list[dict[str, Any]]:
    all_products = []

    for file_path in GOLD_FILES:
        if not file_path.exists():
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
            all_products.extend(items)

    return all_products


def load_gastat_records() -> list[tuple]:
    if not GASTAT_FILE.exists():
        print(f"[!] تحذير: ملف GASTAT غير موجود في: {GASTAT_FILE}")
        return []

    with open(GASTAT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    gastat_dict = {}

    for r in records:
        barcodes = r.get("matched_barcodes", [])
        avg_price = (
            float(r.get("Annual average", 0))
            if r.get("Annual average")
            else None
        )
        year = int(r.get("Year", 0))

        for bc in barcodes:
            key = (
                r.get("gastat_id"),
                year,
                str(bc),
            )

            gastat_dict[key] = (
                r.get("gastat_id"),
                r.get("item_name_ar"),
                r.get("item_name_en"),
                year,
                r.get("unit_ar"),
                avg_price,
                str(bc),
            )

    return list(gastat_dict.values())


def init_database_objects(
    cursor: snowflake.connector.cursor.SnowflakeCursor,
) -> None:

    print("[*] Verifying database structure...")

    ddl_statements = [
        """
        CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH
        WITH
            WAREHOUSE_SIZE = 'XSMALL'
            AUTO_SUSPEND = 60
            AUTO_RESUME = TRUE;
        """,
        "USE WAREHOUSE COMPUTE_WH;",
        "CREATE DATABASE IF NOT EXISTS GROCERY_TRACKER_DB;",
        "USE DATABASE GROCERY_TRACKER_DB;",
        "CREATE SCHEMA IF NOT EXISTS ANALYTICS;",
        "USE SCHEMA ANALYTICS;",
        """
        CREATE TABLE IF NOT EXISTS GROCERY_TRACKER_DB.ANALYTICS.DIM_MATCHED_PRODUCTS (
            product_id VARCHAR(100) PRIMARY KEY,
            product_name_ar VARCHAR(500),
            product_name_en VARCHAR(500),
            brand VARCHAR(100),
            category VARCHAR(100),
            size FLOAT,
            unit VARCHAR(50),
            barcode VARCHAR(100),
            matched_stores_count INT,
            confidence_score FLOAT,
            match_tier VARCHAR(50),
            canonical_source VARCHAR(50),
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS GROCERY_TRACKER_DB.ANALYTICS.FCT_PRICE_SNAPSHOTS (
            snapshot_date DATE,
            product_id VARCHAR(100),
            avg_price FLOAT,
            min_price FLOAT,
            max_price FLOAT,
            price_diff FLOAT,
            bindawood_price FLOAT,
            panda_price FLOAT,
            tamimi_price FLOAT,
            created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
            PRIMARY KEY (snapshot_date, product_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS GROCERY_TRACKER_DB.ANALYTICS.REF_GASTAT_PRICES (
            gastat_id INT,
            item_name_ar VARCHAR(500),
            item_name_en VARCHAR(500),
            year INT,
            unit_ar VARCHAR(50),
            annual_avg_price FLOAT,
            barcode VARCHAR(100),
            PRIMARY KEY (gastat_id, year, barcode)
        );
        """,
    ]

    for stmt in ddl_statements:
        cursor.execute(stmt)

    print("✓ Schema & Tables verified.\n")


def main() -> None:

    print(f"[*] Snowflake User: {SNOWFLAKE_CONFIG['user']}")

    password = os.getenv("SNOWFLAKE_PASSWORD")

    if not password:
        password = getpass.getpass(
            "Enter Snowflake Password: "
        ).strip()

    if not password:
        print("[!] كلمة المرور فارغة.")
        return

    print("[*] Connecting to Snowflake Cloud...")

    conn = snowflake.connector.connect(
        user=SNOWFLAKE_CONFIG["user"],
        password=password,
        account=SNOWFLAKE_CONFIG["account"],
        host=SNOWFLAKE_CONFIG["host"],
        warehouse=SNOWFLAKE_CONFIG["warehouse"],
        role=SNOWFLAKE_CONFIG["role"],
    )

    cursor = conn.cursor()

    print("✓ Connected successfully!\n")

    init_database_objects(cursor)

    # ============================================================
    # Load current Gold
    # ============================================================

    products = load_gold_data()

    print(
        f"[*] Preparing batch payload for "
        f"{len(products)} store products..."
    )

    today = datetime.now().strftime("%Y-%m-%d")

    dim_dict: dict[str, tuple] = {}
    fct_dict: dict[tuple, tuple] = {}

    for p in products:

        raw_id = (
            p.get("barcode")
            or p.get("product_name_ar")
            or p.get("product_name_en")
        )

        if not raw_id:
            continue

        pid = str(raw_id).strip()

        p_metrics = p.get("price_metrics", {})
        s_data = p.get("stores_data", {})

        # ========================================================
        # DIM
        # ========================================================

        dim_dict[pid] = (
            pid,
            p.get("product_name_ar"),
            p.get("product_name_en"),
            p.get("brand"),
            p.get("category"),
            p.get("size"),
            p.get("unit"),
            p.get("barcode"),
            p.get("matched_stores_count"),
            p.get("confidence_score"),
            p.get("match_tier"),
            p.get("canonical_source"),
        )

        # ========================================================
        # FCT snapshot
        # ========================================================

        fct_dict[(today, pid)] = (
            today,
            pid,
            p_metrics.get("avg_price"),
            p_metrics.get("min_price"),
            p_metrics.get("max_price"),
            p_metrics.get("price_diff"),
            s_data.get("bindawood", {}).get("price"),
            s_data.get("panda", {}).get("price"),
            s_data.get("tamimi", {}).get("price"),
        )

    dim_rows = list(dim_dict.values())
    fct_rows = list(fct_dict.values())

    print(
        f"[*] Current Gold unique products: "
        f"{len(dim_rows)}"
    )

    # ============================================================
    # IMPORTANT:
    # Clean ONLY today's snapshot before reloading it.
    #
    # Yesterday / older history remains untouched.
    # This prevents stale products from previous runs
    # on the same day from remaining in Snowflake.
    # ============================================================

    print(
        f"[*] Cleaning existing FCT snapshot "
        f"for {today}..."
    )

    cursor.execute(
        """
        DELETE FROM
            GROCERY_TRACKER_DB.ANALYTICS.FCT_PRICE_SNAPSHOTS
        WHERE snapshot_date = %s
        """,
        (today,),
    )

    print(
        f"✓ Today's old snapshot cleared: {today}\n"
    )

    # ============================================================
    # 1. Upload DIM
    # ============================================================

    print(
        f"[*] Batch uploading DIM_MATCHED_PRODUCTS "
        f"({len(dim_rows)} unique items)..."
    )

    cursor.execute(
        """
        CREATE TEMPORARY TABLE IF NOT EXISTS temp_dim_stage (
            product_id VARCHAR(100),
            product_name_ar VARCHAR(500),
            product_name_en VARCHAR(500),
            brand VARCHAR(100),
            category VARCHAR(100),
            size FLOAT,
            unit VARCHAR(50),
            barcode VARCHAR(100),
            matched_stores_count INT,
            confidence_score FLOAT,
            match_tier VARCHAR(50),
            canonical_source VARCHAR(50)
        );
        """
    )

    cursor.execute(
        "TRUNCATE TABLE temp_dim_stage;"
    )

    cursor.executemany(
        """
        INSERT INTO temp_dim_stage
        VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        """,
        dim_rows,
    )

    cursor.execute(
        """
        MERGE INTO
            GROCERY_TRACKER_DB.ANALYTICS.DIM_MATCHED_PRODUCTS target

        USING (
            SELECT *
            FROM temp_dim_stage
            QUALIFY
                ROW_NUMBER() OVER (
                    PARTITION BY product_id
                    ORDER BY confidence_score DESC NULLS LAST
                ) = 1
        ) source

        ON target.product_id = source.product_id

        WHEN MATCHED THEN UPDATE SET
            product_name_ar = source.product_name_ar,
            product_name_en = source.product_name_en,
            brand = source.brand,
            category = source.category,
            size = source.size,
            unit = source.unit,
            barcode = source.barcode,
            matched_stores_count = source.matched_stores_count,
            confidence_score = source.confidence_score,
            match_tier = source.match_tier,
            canonical_source = source.canonical_source

        WHEN NOT MATCHED THEN INSERT (
            product_id,
            product_name_ar,
            product_name_en,
            brand,
            category,
            size,
            unit,
            barcode,
            matched_stores_count,
            confidence_score,
            match_tier,
            canonical_source
        )

        VALUES (
            source.product_id,
            source.product_name_ar,
            source.product_name_en,
            source.brand,
            source.category,
            source.size,
            source.unit,
            source.barcode,
            source.matched_stores_count,
            source.confidence_score,
            source.match_tier,
            source.canonical_source
        );
        """
    )

    # ============================================================
    # 2. Upload today's FCT snapshot
    # ============================================================

    print(
        f"[*] Batch uploading FCT_PRICE_SNAPSHOTS "
        f"({len(fct_rows)} unique items)..."
    )

    cursor.execute(
        """
        CREATE TEMPORARY TABLE IF NOT EXISTS temp_fct_stage (
            snapshot_date DATE,
            product_id VARCHAR(100),
            avg_price FLOAT,
            min_price FLOAT,
            max_price FLOAT,
            price_diff FLOAT,
            bindawood_price FLOAT,
            panda_price FLOAT,
            tamimi_price FLOAT
        );
        """
    )

    cursor.execute(
        "TRUNCATE TABLE temp_fct_stage;"
    )

    cursor.executemany(
        """
        INSERT INTO temp_fct_stage
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        """,
        fct_rows,
    )

    cursor.execute(
        """
        MERGE INTO
            GROCERY_TRACKER_DB.ANALYTICS.FCT_PRICE_SNAPSHOTS target

        USING (
            SELECT *
            FROM temp_fct_stage
            QUALIFY
                ROW_NUMBER() OVER (
                    PARTITION BY snapshot_date, product_id
                    ORDER BY snapshot_date DESC
                ) = 1
        ) source

        ON
            target.snapshot_date = source.snapshot_date
            AND target.product_id = source.product_id

        WHEN MATCHED THEN UPDATE SET
            avg_price = source.avg_price,
            min_price = source.min_price,
            max_price = source.max_price,
            price_diff = source.price_diff,
            bindawood_price = source.bindawood_price,
            panda_price = source.panda_price,
            tamimi_price = source.tamimi_price

        WHEN NOT MATCHED THEN INSERT (
            snapshot_date,
            product_id,
            avg_price,
            min_price,
            max_price,
            price_diff,
            bindawood_price,
            panda_price,
            tamimi_price
        )

        VALUES (
            source.snapshot_date,
            source.product_id,
            source.avg_price,
            source.min_price,
            source.max_price,
            source.price_diff,
            source.bindawood_price,
            source.panda_price,
            source.tamimi_price
        );
        """
    )

    # ============================================================
    # 3. Upload GASTAT
    # ============================================================

    gastat_rows = load_gastat_records()

    if gastat_rows:

        print(
            f"[*] Batch uploading REF_GASTAT_PRICES "
            f"({len(gastat_rows)} records)..."
        )

        cursor.execute(
            """
            CREATE TEMPORARY TABLE IF NOT EXISTS temp_gastat_stage (
                gastat_id INT,
                item_name_ar VARCHAR(500),
                item_name_en VARCHAR(500),
                year INT,
                unit_ar VARCHAR(50),
                annual_avg_price FLOAT,
                barcode VARCHAR(100)
            );
            """
        )

        cursor.execute(
            "TRUNCATE TABLE temp_gastat_stage;"
        )

        cursor.executemany(
            """
            INSERT INTO temp_gastat_stage
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s
            )
            """,
            gastat_rows,
        )

        cursor.execute(
            """
            MERGE INTO
                GROCERY_TRACKER_DB.ANALYTICS.REF_GASTAT_PRICES target

            USING (
                SELECT *
                FROM temp_gastat_stage
                QUALIFY
                    ROW_NUMBER() OVER (
                        PARTITION BY gastat_id, year, barcode
                        ORDER BY annual_avg_price DESC NULLS LAST
                    ) = 1
            ) source

            ON
                target.gastat_id = source.gastat_id
                AND target.year = source.year
                AND target.barcode = source.barcode

            WHEN MATCHED THEN UPDATE SET
                annual_avg_price = source.annual_avg_price,
                item_name_ar = source.item_name_ar,
                item_name_en = source.item_name_en,
                unit_ar = source.unit_ar

            WHEN NOT MATCHED THEN INSERT (
                gastat_id,
                item_name_ar,
                item_name_en,
                year,
                unit_ar,
                annual_avg_price,
                barcode
            )

            VALUES (
                source.gastat_id,
                source.item_name_ar,
                source.item_name_en,
                source.year,
                source.unit_ar,
                source.annual_avg_price,
                source.barcode
            );
            """
        )

    # ============================================================
    # Commit and close
    # ============================================================

    conn.commit()

    cursor.close()
    conn.close()

    print("\n" + "=" * 60)
    print("🚀 UNIFIED BATCH SUCCESS! Data Pipeline completed:")
    print(
        f"  • DIM_MATCHED_PRODUCTS: "
        f"{len(dim_rows)} records synced"
    )
    print(
        f"  • FCT_PRICE_SNAPSHOTS:  "
        f"{len(fct_rows)} records synced"
    )
    print(
        f"  • REF_GASTAT_PRICES:    "
        f"{len(gastat_rows)} records synced"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()