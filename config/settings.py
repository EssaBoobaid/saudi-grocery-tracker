from pathlib import Path

# المسارات الأساسية لمستودع البيانات
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"

# 1. إعدادات متجر أسواق هلا (Hala Markets)
HALA_STORE_CONFIG = {
    "store_name": "hala_markets",
    "base_url": "https://api.salla.dev/store/v1/products",
    "headers": {
        "accept": "*/*",
        "accept-language": "ar",
        "currency": "SAR",
        "origin": "https://hala-markets.sa",
        "referer": "https://hala-markets.sa/",
        "s-country": "SA",
        "s-scope-id": "449893082",
        "s-scope-type": "scope",
        "s-source": "twilight",
        "store-identifier": "1756322741",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    },
    "categories": {
        "dairy_and_eggs": "1721317509",
        "beverages": "1194445481",
        "fruits_and_vegetables": "1780859875",
    }
}

# 2. إعدادات متجر لولو هايبرماركت (LuLu Hypermarket)
LULU_STORE_CONFIG = {
    "store_name": "lulu_hypermarket",
    "base_url": "https://gcc.luluhypermarket.com",
    "product_api": "https://gcc.luluhypermarket.com/api/client/product/{product_id}/",
    "categories": {
        "dairy_and_cheese": "fresh-food-dairy-eggs-cheese",
        "fruits_and_vegetables": "fresh-food-fruits-vegetables",
        "beverages": "grocery-food-cupboard-beverage",
    },
    "headers": {
        "accept": "*/*",
        "accept-language": "ar-sa",
        "x-currency": "sar",
        "x-csrftoken": "Q63znmzMILd36Osm7wy34fmH8g55GCU9VilOUtOet1tWuxW5aNjXlqM1sqWEeViX",
    },
    "cookies": (
        "pz-locale=ar-sa; pz-currency=sar; "
        "csrftoken=Q63znmzMILd36Osm7wy34fmH8g55GCU9VilOUtOet1tWuxW5aNjXlqM1sqWEeViX; "
        "cf_clearance=jrUuX.LTvCzonSgQtrvAZfq3Yrk0IbODkEk43Ap2GUI-1788816137-1.2.1.1-BeTXuoO3g1hOCApB.5mhZNAEm27IwXErZIkdoiVVeyn4dfR21fBu4csajxsor8xUb6jRgOifnMH1I5EsF7Hf4rCAtxj.uR0CNttqShyMaqVccEpaJlPCRFnVMzuPd0A.DCv0STWTXCKjLRxjjFpSkF0megVu5UAcRbYExGem0RcZ7u_JwtLxQ6LpHCfOELfMOMV8hi7O1SCzwTp1V0oWqC6.t32ctYh1QHEEn5Hjuy9wyNOTR8VcFh4fhmKvjf51taqhlmbXQb2QpWZMdNe99YkjKy1hMFYzc3vVBcrOtYGqr9RL7WAFdKz0aJMjE7syoEEOCR54v_l1nsHN7KgFzx9Lpgk4ZvZbu6jMnvt1pmE"
    )
}