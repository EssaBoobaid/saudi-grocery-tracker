"""Panda Markets Silver Cleaning Pipeline.

Reads raw Panda parent products from:
data/bronze/panda/

Expands every Panda variety into an individual Silver product and writes:
data/silver/panda/

Output schema matches the existing unified Silver schema.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
BRONZE_DIR = BASE_DIR / "data" / "bronze" / "panda"
SILVER_DIR = BASE_DIR / "data" / "silver" / "panda"

CATEGORIES = [
    "beverages",
    "dairy_and_eggs",
    "fruits_and_vegetables",
]


UNIT_MULTIPLIERS = {
    "l": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "litre": ("ml", 1000.0),
    "ltr": ("ml", 1000.0),

    "ml": ("ml", 1.0),
    "milliliter": ("ml", 1.0),

    "kg": ("g", 1000.0),
    "kilogram": ("g", 1000.0),
    "kilo": ("g", 1000.0),

    "g": ("g", 1.0),
    "gm": ("g", 1.0),
    "gram": ("g", 1.0),
    "grams": ("g", 1.0),

    "pcs": ("pcs", 1.0),
    "pc": ("pcs", 1.0),
    "piece": ("pcs", 1.0),
    "pieces": ("pcs", 1.0),

    "slice": ("slices", 1.0),
    "slices": ("slices", 1.0),
}


def safe_float(value: Any) -> float | None:
    if value in (None, "", False):
        return None

    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def clean_barcode(value: Any) -> list[str]:
    """Return barcode forms compatible with existing matching."""

    if value in (None, ""):
        return []

    code = str(value).strip()

    if not code:
        return []

    barcodes = {code}

    clean = code.lstrip("0")

    if len(clean) >= 7:
        barcodes.add(clean)

    return sorted(barcodes)


def normalize_unit(
    unit: Any,
) -> tuple[str | None, float]:

    if unit in (None, ""):
        return None, 1.0

    raw = str(unit).strip().lower()

    return UNIT_MULTIPLIERS.get(
        raw,
        (raw, 1.0),
    )



def get_weighted_1kg_option(
    variety: dict[str, Any],
) -> dict[str, Any] | None:
    """
    For Panda weighted produce, return the explicit 1 KG option when present.

    Panda may expose size=0.5 KG while the top-level price is actually
    the 1 KG price. When an explicit 1 KG weighted option exists, use it
    as the canonical Silver representation.
    """

    if not variety.get("wighted"):
        return None

    options = variety.get("weighted_options") or []

    if not isinstance(options, list):
        return None

    for option in options:
        if not isinstance(option, dict):
            continue

        quantity_value = safe_float(
            option.get("quantity_value")
        )
        quantity_name = str(
            option.get("quantity_name") or ""
        ).strip().lower()

        if (
            quantity_value == 1.0
            and re.search(
                r"\b1(?:\.0+)?\s*kg\b",
                quantity_name,
                flags=re.IGNORECASE,
            )
        ):
            return option

    return None


def parse_size_from_variety(
    variety: dict[str, Any],
    product_name: str,
) -> dict[str, Any]:
    """
    Standardize Panda pack/size.

    Priority:
    1. Multipack information from product name: 3x100g, 6 x 330ml, etc.
    2. Panda's structured size + unit fields.
    3. Single-size fallback from product name.
    """

    text = product_name.lower().replace("×", "x")

    # ---------------------------------------------------------
    # 0. WEIGHTED PRODUCE
    # If Panda exposes an explicit 1 KG weighted option, normalize
    # the product to 1 KG for comparable Silver/Gold pricing.
    # ---------------------------------------------------------

    weighted_1kg = get_weighted_1kg_option(
        variety
    )

    if weighted_1kg is not None:
        return {
            "pack_qty": 1,
            "unit_size_value": 1000.0,
            "total_size_value": 1000.0,
            "size_unit": "g",
        }

    # ---------------------------------------------------------
    # 1. MULTIPACK
    # Examples:
    #   3x100g
    #   6 x 330ml
    #   100x10g
    #   4 x 1L
    # ---------------------------------------------------------

    multi_match = re.search(
        r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*"
        r"(ml|l|ltr|litre|liter|g|gm|gram|grams|kg|kilogram|pcs|pc)\b",
        text,
        flags=re.IGNORECASE,
    )

    if multi_match:
        pack_qty = int(multi_match.group(1))
        raw_value = float(multi_match.group(2))
        raw_unit = multi_match.group(3)

        std_unit, multiplier = normalize_unit(
            raw_unit
        )

        unit_value = round(
            raw_value * multiplier,
            2,
        )

        total_value = round(
            unit_value * pack_qty,
            2,
        )

        return {
            "pack_qty": pack_qty,
            "unit_size_value": unit_value,
            "total_size_value": total_value,
            "size_unit": std_unit,
        }

    # ---------------------------------------------------------
    # 2. PANDA STRUCTURED SIZE
    # Examples:
    # size=400 unit=gm
    # size=1 unit=kg
    # size=330 unit=mL
    # ---------------------------------------------------------

    raw_size = variety.get("size")
    raw_unit = variety.get("unit")

    value = safe_float(raw_size)

    std_unit, multiplier = normalize_unit(
        raw_unit
    )

    if value is not None and std_unit:
        normalized_value = round(
            value * multiplier,
            2,
        )

        return {
            "pack_qty": 1,
            "unit_size_value": normalized_value,
            "total_size_value": normalized_value,
            "size_unit": std_unit,
        }

    # ---------------------------------------------------------
    # 3. FALLBACK FROM PRODUCT NAME
    # ---------------------------------------------------------

    single_match = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(ml|l|ltr|litre|liter|g|gm|gram|grams|kg|kilogram|pcs|pc)\b",
        text,
        flags=re.IGNORECASE,
    )

    if single_match:
        raw_value = float(
            single_match.group(1)
        )

        raw_unit = single_match.group(2)

        std_unit, multiplier = normalize_unit(
            raw_unit
        )

        normalized_value = round(
            raw_value * multiplier,
            2,
        )

        return {
            "pack_qty": 1,
            "unit_size_value": normalized_value,
            "total_size_value": normalized_value,
            "size_unit": std_unit,
        }

    return {
        "pack_qty": 1,
        "unit_size_value": None,
        "total_size_value": None,
        "size_unit": None,
    }


def extract_image(
    variety: dict[str, Any],
) -> str | None:

    image_url = variety.get("imageURL")

    if image_url:
        return str(image_url)

    images = variety.get("images") or []

    if (
        images
        and isinstance(images, list)
    ):
        first = images[0]

        if isinstance(first, str):
            return first

        if (
            isinstance(first, list)
            and first
        ):
            return str(first[0])

    return None



def clean_weighted_options(
    variety: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Preserve all Panda weighted price choices in Silver.

    Example:
      0.5 KG -> 6.00
      1 KG   -> 11.99
      1.5 KG -> 17.98

    We keep these as a normalized list while the main Silver
    price/size fields continue to use the 1 KG option when available.
    """

    if not variety.get("wighted"):
        return []

    raw_options = variety.get("weighted_options") or []

    if not isinstance(raw_options, list):
        return []

    cleaned: list[dict[str, Any]] = []

    for option in raw_options:
        if not isinstance(option, dict):
            continue

        quantity_value = safe_float(
            option.get("quantity_value")
        )
        quantity_name = str(
            option.get("quantity_name") or ""
        ).strip() or None
        option_price = safe_float(
            option.get("price")
        )
        option_original_price = safe_float(
            option.get("undiscounted_price")
        )

        if (
            quantity_value is None
            and quantity_name is None
            and option_price is None
        ):
            continue

        cleaned.append({
            "quantity_value": quantity_value,
            "quantity_name": quantity_name,
            "price": option_price,
            "original_price": option_original_price,
        })

    return cleaned


def parse_variety(
    product: dict[str, Any],
    variety: dict[str, Any],
    category: str,
) -> dict[str, Any] | None:

    product_name = (
        product.get("name")
        or variety.get("description")
    )

    if not product_name:
        return None

    # Panda variety SKU is ideal as Silver ID.
    variety_id = (
        variety.get("sku")
        or variety.get("id")
    )

    if variety_id in (None, ""):
        return None

    brand_obj = product.get("brand") or {}

    if isinstance(brand_obj, dict):
        brand = brand_obj.get("name")
    else:
        brand = str(brand_obj) if brand_obj else None

    weighted_1kg = get_weighted_1kg_option(
        variety
    )

    if weighted_1kg is not None:
        price = safe_float(
            weighted_1kg.get("price")
        )

        original_price = safe_float(
            weighted_1kg.get("undiscounted_price")
        )
    else:
        price = safe_float(
            variety.get("price")
        )

        original_price = safe_float(
            variety.get("undiscounted_price")
        )

    discount_amount = None
    discount_percentage = None

    if (
        price is not None
        and original_price is not None
        and original_price > price
        and original_price > 0
    ):
        discount_amount = round(
            original_price - price,
            2,
        )

        discount_percentage = round(
            (
                discount_amount
                / original_price
            ) * 100,
            2,
        )

    size_data = parse_size_from_variety(
        variety,
        str(product_name),
    )

    barcodes = clean_barcode(
        variety.get("barcode")
    )

    image_url = extract_image(
        variety
    )

    return {
        "id": str(variety_id),
        "store": "panda",
        "category": category,

        "name_en": (
            str(product_name).strip()
            if product.get("_source_locale") != "ar"
            else None
        ),

        "name_ar": (
            str(product_name).strip()
            if product.get("_source_locale") == "ar"
            else None
        ),

        "brand": brand,
        "barcodes": barcodes,

        "price": price,
        "original_price": original_price,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,

        # Panda weighted produce:
        # keep every selectable weight/price from Bronze in Silver.
        "is_weighted": bool(variety.get("wighted")),
        "weighted_interval": safe_float(
            variety.get("weighted_interval")
        ),
        "weighted_options": clean_weighted_options(
            variety
        ),

        "pack_qty": size_data["pack_qty"],
        "unit_size_value": size_data["unit_size_value"],
        "total_size_value": size_data["total_size_value"],
        "size_unit": size_data["size_unit"],

        "image_url": image_url,
    }


def main() -> None:

    print(
        "=== [Panda] Starting Silver Clean Pipeline ==="
    )

    SILVER_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    for category in CATEGORIES:

        bronze_file = (
            BRONZE_DIR
            / f"{category}_raw.json"
        )

        if not bronze_file.exists():
            print(
                f"  ! Missing {bronze_file.name}"
            )
            continue

        with bronze_file.open(
            "r",
            encoding="utf-8",
        ) as file:
            raw_data = json.load(file)

        cleaned = []
        seen_ids = set()

        parent_count = 0
        variety_count = 0
        barcode_hits = 0
        discount_hits = 0
        size_hits = 0
        weighted_1kg_hits = 0

        for product in raw_data:

            parent_count += 1

            varieties = (
                product.get("varieties")
                or []
            )

            if not isinstance(
                varieties,
                list,
            ):
                continue

            for variety in varieties:

                if not isinstance(
                    variety,
                    dict,
                ):
                    continue

                variety_count += 1

                if get_weighted_1kg_option(variety) is not None:
                    weighted_1kg_hits += 1

                parsed = parse_variety(
                    product,
                    variety,
                    category,
                )

                if not parsed:
                    continue

                if parsed["id"] in seen_ids:
                    continue

                seen_ids.add(
                    parsed["id"]
                )

                if parsed["barcodes"]:
                    barcode_hits += 1

                if parsed["discount_amount"]:
                    discount_hits += 1

                if parsed["total_size_value"]:
                    size_hits += 1

                cleaned.append(
                    parsed
                )

        output_file = (
            SILVER_DIR
            / f"{category}_clean.json"
        )

        with output_file.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                cleaned,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            f"  ✓ {category}: "
            f"{parent_count} parents -> "
            f"{variety_count} varieties -> "
            f"{len(cleaned)} clean products "
            f"(Sizes: {size_hits} | "
            f"Barcodes: {barcode_hits} | "
            f"Deals: {discount_hits} | "
            f"Weighted 1KG: {weighted_1kg_hits})"
        )

        print(
            f"    -> {output_file.name}"
        )

    print(
        "\n=== [Panda] Silver Cleaning Completed ==="
    )


if __name__ == "__main__":
    main()