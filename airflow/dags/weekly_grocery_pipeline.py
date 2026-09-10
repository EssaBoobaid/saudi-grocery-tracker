"""Weekly Grocery Price Tracking Pipeline (End-to-End Orchestration).

Orchestrates the Medallion data workflow:
1. Bronze: Parallel extraction from Tamimi, BinDawood, and Lulu
2. Silver: Standardizing schemas and cleaning text/prices
3. Gold: Category-level entity matching across all stores + GASTAT Open Data matching
4. Load: Upserting snapshots and pricing dimensions into Snowflake Cloud DWH
"""

from __future__ import annotations

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "shaleh",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="weekly_grocery_pipeline",
    default_args=default_args,
    description="Automated multi-store grocery tracker: Bronze -> Silver -> Gold -> Snowflake",
    schedule_interval="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["grocery", "etl", "scraping", "matching", "snowflake"],
) as dag:

    # -------------------------------------------------------------
    # 1. BRONZE LAYER (Parallel Extractions)
    # -------------------------------------------------------------
    bronze_tamimi = BashOperator(
        task_id="bronze_extract_tamimi",
        bash_command="python -m src.bronze.extract_tamimi",
    )

    bronze_bindawood = BashOperator(
        task_id="bronze_extract_bindawood",
        bash_command="python -m src.bronze.extract_bindawood",
    )

    bronze_lulu = BashOperator(
        task_id="bronze_extract_lulu",
        bash_command="python -m src.bronze.lulu_extractor",
    )

    # -------------------------------------------------------------
    # 2. SILVER LAYER (Cleaning & Standardization)
    # -------------------------------------------------------------
    silver_tamimi = BashOperator(
        task_id="silver_clean_tamimi",
        bash_command="python -m src.silver.clean_tamimi",
    )

    silver_bindawood = BashOperator(
        task_id="silver_clean_bindawood",
        bash_command="python -m src.silver.clean_bindawood",
    )

    silver_lulu = BashOperator(
        task_id="silver_clean_lulu",
        bash_command="python -m src.silver.clean_lulu",
    )

    # -------------------------------------------------------------
    # 3. GOLD LAYER (Matching & Open Data Integration)
    # -------------------------------------------------------------
    gold_beverages = BashOperator(
        task_id="gold_match_beverages",
        bash_command="python -m src.gold.match_beverages",
    )

    gold_dairy_and_eggs = BashOperator(
        task_id="gold_match_dairy_and_eggs",
        bash_command="python -m src.gold.match_dairy_and_eggs",
    )

    gold_fruits_and_veg = BashOperator(
        task_id="gold_match_fruits_and_veg",
        bash_command="python -m src.gold.matched_fruits_and_vegetables",
    )

    gold_open_data = BashOperator(
        task_id="gold_match_open_data_gastat",
        bash_command="python -m src.gold.match_open_data_with_fruits_vige",
    )

    # -------------------------------------------------------------
    # 4. DATABASE INGESTION (Snowflake Cloud Load)
    # -------------------------------------------------------------
    load_snowflake = BashOperator(
        task_id="load_to_snowflake_dwh",
        bash_command="python -m src.database.snowflake_loader",
    )

    # -------------------------------------------------------------
    # PIPELINE DEPENDENCY GRAPH
    # -------------------------------------------------------------
    bronze_tamimi >> silver_tamimi
    bronze_bindawood >> silver_bindawood
    bronze_lulu >> silver_lulu

    # مهام السيلفر تغذي مهام القولد
    all_silver = [silver_tamimi, silver_bindawood, silver_lulu]

    all_silver >> gold_beverages
    all_silver >> gold_dairy_and_eggs
    all_silver >> gold_fruits_and_veg

    # مطابقة بيانات الإحصاء تبدأ فور انتهاء مطابقة الخضار والفواكه
    gold_fruits_and_veg >> gold_open_data

    # الحقن في Snowflake يبدأ بعد اكتمال جميع ملفات القولد
    [gold_beverages, gold_dairy_and_eggs, gold_open_data] >> load_snowflake