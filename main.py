from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from config.settings import BRONZE_DIR, DATABASE_PATH, GOLD_DIR, SILVER_DIR, ensure_directories
from src.bronze.hala_extractor import HalaExtractor
from src.bronze.lulu_extractor import LuluExtractor
from src.bronze.panda_extractor import PandaExtractor
from src.gold.db_loader import DatabaseLoader
from src.gold.matcher import match_products
from src.silver.cleaner import clean_products
from silver.clean_tamimi import normalize_units

DEMO_DATA = {
    "panda": [
        {"id": "p-1", "name": "حليب كامل الدسم 1 لتر", "category": "milk", "price": 7.25, "url": "https://panda.sa/p-1"},
        {"id": "p-2", "name": "أرز بسمتي 5 كجم", "category": "rice", "price": 38.50, "url": "https://panda.sa/p-2"},
    ],
    "hala": [
        {"id": "c-1", "name": "حليب كامل الدسم 1000 مل", "category": "milk", "price": 6.95, "url": "https://carrefourksa.com/c-1"},
        {"id": "c-2", "name": "أرز بسمتي 5 كيلو", "category": "rice", "price": 37.99, "url": "https://carrefourksa.com/c-2"},
    ],
    "lulu": [
        {"id": "l-1", "name": "حليب كامل الدسم 1 لتر", "category": "milk", "price": 7.50, "url": "https://luluhypermarket.com/l-1"},
        {"id": "l-2", "name": "أرز بسمتي 5 كجم", "category": "rice", "price": 39.00, "url": "https://luluhypermarket.com/l-2"},
    ],
}
EXTRACTORS = {
    "panda": PandaExtractor,
    "hala": HalaExtractor,
    "lulu": LuluExtractor,
}


def write_bronze(store: str, records: list[dict]) -> Path:
    extractor = EXTRACTORS[store]()
    return extractor.save_raw({"products": records}, suffix="demo_products")


def run_pipeline(records_by_store: dict[str, list[dict]]) -> pd.DataFrame:
    ensure_directories()
    frames = []
    for store, records in records_by_store.items():
        write_bronze(store, records)
        frames.append(normalize_units(clean_products(records, store)))

    products = match_products(pd.concat(frames, ignore_index=True))
    try:
        products.to_parquet(SILVER_DIR / "products.parquet", index=False)
    except ImportError:
        products.to_csv(SILVER_DIR / "products.csv", index=False)

    loader = DatabaseLoader(DATABASE_PATH, Path(__file__).parent / "src" / "gold" / "schema.sql")
    loader.load(products)
    comparison = loader.comparison()
    comparison.to_csv(GOLD_DIR / "comparison.csv", index=False)
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description="Saudi grocery price comparison pipeline")
    parser.add_argument("--demo", action="store_true", help="run with local sample data")
    args = parser.parse_args()
    if not args.demo:
        parser.error("The initial version supports --demo; connect store API clients before live extraction.")
    comparison = run_pipeline(DEMO_DATA)
    print(json.dumps(comparison.to_dict(orient="records"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
