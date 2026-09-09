"""Central Settings & Dynamic Path Configuration for Saudi Grocery Tracker."""

from __future__ import annotations

import os
from pathlib import Path

# المسار الجذري للمشروع
BASE_DIR = Path(__file__).resolve().parent.parent

# مسارات البيانات
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
OPEN_DATA_DIR = GOLD_DIR / "open_data"
REFERENCE_DIR = GOLD_DIR / "reference"

# مسارات برونز المتاجر
BRONZE_BINDAWOOD = BRONZE_DIR / "bindawood"
BRONZE_LULU = BRONZE_DIR / "lulu"
BRONZE_TAMIMI = BRONZE_DIR / "tamimi"

# مسارات سيلفر المتاجر
SILVER_BINDAWOOD = SILVER_DIR / "bindawood"
SILVER_LULU = SILVER_DIR / "lulu"
SILVER_TAMIMI = SILVER_DIR / "tamimi"

# إعدادات قاعدة البيانات PostgreSQL (تُقرأ تلقائياً من Docker أو Local)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME", "tracker_db"),
    "user": os.getenv("DB_USER", "grocery_user"),
    "password": os.getenv("DB_PASSWORD", "grocery_password123"),
}

# تصنيفات السلع المشتركة
CATEGORIES = [
    "fruits_and_vegetables",
    "dairy_and_eggs",
    "beverages",
]