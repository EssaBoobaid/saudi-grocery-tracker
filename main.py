"""Master Pipeline Orchestrator for Saudi Grocery Tracker."""

from __future__ import annotations

import sys
import time


def execute_stage(stage_name: str, task):
    print("\n" + "=" * 70)
    print(f"🚀 RUNNING: {stage_name}")
    print("=" * 70)
    start_time = time.time()
    try:
        task()
        elapsed = round(time.time() - start_time, 2)
        print(f"✅ FINISHED: {stage_name} (took {elapsed}s)")
    except Exception as error:
        print(f"❌ FAILED IN [{stage_name}]: {error}")
        sys.exit(1)


# 1. BRONZE (Extraction)
def run_bronze():
    from src.bronze.extract_bindawood import main as bindawood_extract
    from src.bronze.lulu_extractor import main as lulu_extract
    from src.bronze.extract_tamimi import main as tamimi_extract

    bindawood_extract()
    lulu_extract()
    tamimi_extract()


# 2. SILVER (Cleaning & Normalization)
def run_silver():
    from src.silver.clean_bindawood import main as bindawood_clean
    from src.silver.clean_lulu import main as lulu_clean
    from src.silver.clean_tamimi import main as tamimi_clean

    bindawood_clean()
    lulu_clean()
    tamimi_clean()


# 3. GOLD (Matching & GASTAT Integration)
def run_gold():
    from src.gold.match_beverages import main as match_beverages
    from src.gold.match_dairy_and_eggs import main as match_dairy
    from src.gold.matched_fruits_and_vegetables import main as match_produce
    from src.gold.match_open_data_with_fruits_vige import main as match_gastat_produce

    print("[*] Matching Beverages...")
    match_beverages()

    print("[*] Matching Dairy & Eggs...")
    match_dairy()

    print("[*] Step 1: Matching Fruits & Vegetables...")
    match_produce()

    print("[*] Step 2: Aligning Fruits & Vegetables with GASTAT Open Data...")
    match_gastat_produce()


# 4. DATABASE (PostgreSQL Storage)
def run_database():
    from src.database.db_loader import main as load_to_db
    load_to_db()


def main():
    pipeline_start = time.time()
    print("\n" + "#" * 70)
    print("🛒 SAUDI GROCERY TRACKER — COMPLETE PIPELINE")
    print("#" * 70)

    execute_stage("1. BRONZE (Extraction)", run_bronze)
    execute_stage("2. SILVER (Cleaning & Normalization)", run_silver)
    execute_stage("3. GOLD (Clustering & Matching)", run_gold)
    execute_stage("4. DATABASE (PostgreSQL Storage)", run_database)

    total_time = round(time.time() - pipeline_start, 2)
    print("\n" + "#" * 70)
    print(f"🎉 PIPELINE COMPLETED SUCCESSFULLY IN {total_time}s")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    main()