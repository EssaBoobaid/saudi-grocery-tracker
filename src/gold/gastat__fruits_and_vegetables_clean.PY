"""Inject Static gastat_id (1-41) directly into GASTAT Open Data JSON.

Modifies: data/open_data/gastat__fruits_and_vegetables_clean.json
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
GASTAT_FILE = BASE_DIR / "data" / "open_data" / "gastat__fruits_and_vegetables_clean.json"

GASTAT_MAP = [
    {"id": 1, "name_ar": "موز الشربتلي الفلبين", "slug": "philippines_banana_alsharbatli"},
    {"id": 2, "name_ar": "تمر (رطب)", "slug": "dates_rotab"},
    {"id": 3, "name_ar": "تين محلي", "slug": "local_fig"},
    {"id": 4, "name_ar": "منجا باكستاني", "slug": "pakistani_mango"},
    {"id": 5, "name_ar": "ليمون وسط أفريقي", "slug": "medium_african_lemon"},
    {"id": 6, "name_ar": "برتقال أبو صرة مصري", "slug": "abu_sorra_egyptian_orange"},
    {"id": 7, "name_ar": "يوسفي باكستاني", "slug": "pakistani_mandarin"},
    {"id": 8, "name_ar": "تفاح أحمر أمريكي", "slug": "american_red_apples"},
    {"id": 9, "name_ar": "تفاح أصفر", "slug": "yellow_apples"},
    {"id": 10, "name_ar": "كمثرى وسط لبناني", "slug": "medium_lebanese_pears"},
    {"id": 11, "name_ar": "برقوق / بخارى تركي", "slug": "turkish_plums"},
    {"id": 12, "name_ar": "خوخ لبناني", "slug": "lebanese_peach"},
    {"id": 13, "name_ar": "رمان هندي", "slug": "indian_pomegranates"},
    {"id": 14, "name_ar": "عنب محلي", "slug": "local_grapes"},
    {"id": 15, "name_ar": "عنب لبناني", "slug": "lebanese_grapes"},
    {"id": 16, "name_ar": "شمام محلي", "slug": "local_melon"},
    {"id": 17, "name_ar": "حبحب (بطيخ) محلي", "slug": "local_watermelon"},
    {"id": 18, "name_ar": "تمر (مكنوز) إخلاص", "slug": "ekhilas_dates_maknoz"},
    {"id": 19, "name_ar": "خس محلي", "slug": "local_lettuce"},
    {"id": 20, "name_ar": "ملوخية محلية", "slug": "local_corchorus"},
    {"id": 21, "name_ar": "جرجير محلي", "slug": "local_watercress"},
    {"id": 22, "name_ar": "ملفوف أبيض", "slug": "white_cabbage"},
    {"id": 23, "name_ar": "سبانخ", "slug": "spinach"},
    {"id": 24, "name_ar": "فلفل أخضر بارد محلي", "slug": "green_local_peppers"},
    {"id": 25, "name_ar": "فلفل أخضر حار محلي", "slug": "green_local_chili"},
    {"id": 26, "name_ar": "خيار محلي", "slug": "local_cucumbers"},
    {"id": 27, "name_ar": "باذنجان أسود محلي", "slug": "local_black_eggplants"},
    {"id": 28, "name_ar": "طماطم محلي", "slug": "local_tomatoes"},
    {"id": 29, "name_ar": "طماطم مستورد", "slug": "imported_tomatoes"},
    {"id": 30, "name_ar": "قرع عسلي", "slug": "pumpkin"},
    {"id": 31, "name_ar": "كوسة محلية", "slug": "local_zucchini"},
    {"id": 32, "name_ar": "بامية محلية", "slug": "local_okra"},
    {"id": 33, "name_ar": "فاصوليا خضراء", "slug": "green_beans"},
    {"id": 34, "name_ar": "جزر محلي", "slug": "local_carrots"},
    {"id": 35, "name_ar": "ثوم صيني", "slug": "chinese_garlic"},
    {"id": 36, "name_ar": "بصل مدور محلي", "slug": "local_onion"},
    {"id": 37, "name_ar": "بصل مدور مستورد", "slug": "imported_onion"},
    {"id": 38, "name_ar": "زيتون أسود أسباني", "slug": "black_spanish_olives"},
    {"id": 39, "name_ar": "بطاطس وسط محلي", "slug": "medium_local_potatoes"},
    {"id": 40, "name_ar": "ذرة حلوة", "slug": "sweet_corn"},
    {"id": 41, "name_ar": "بقدونس", "slug": "parsley"},
]


def main() -> None:
    if not GASTAT_FILE.exists():
        print(f"[!] File not found: {GASTAT_FILE}")
        return

    with open(GASTAT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    is_dict = isinstance(data, dict) and "records" in data
    records = data["records"] if is_dict else data

    tagged_count = 0

    for r in records:
        raw_ar = (r.get("item_name_ar") or "").strip()
        raw_en = (r.get("item_name_en") or "").strip().lower()

        # تصحيح الخطأ المطبعي الموجود في بعض السجلات الرسمية
        if raw_ar == "س" and "lemon" in raw_en:
            raw_ar = "ليمون وسط أفريقي"
            r["item_name_ar"] = raw_ar

        matched = None
        for item in GASTAT_MAP:
            if raw_ar == item["name_ar"]:
                matched = item
                break

        if matched:
            r["gastat_id"] = matched["id"]
            r["gastat_slug"] = matched["slug"]
            tagged_count += 1

    with open(GASTAT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print("✅ GASTAT FILE TAGGING COMPLETE:")
    print(f"   • Records Tagged   : {tagged_count} records")
    print(f"   • Unique IDs Used  : 1 to 41")
    print(f"   • Saved to         : {GASTAT_FILE.name}")
    print("=" * 60)


if __name__ == "__main__":
    main()