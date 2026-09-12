import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from difflib import SequenceMatcher


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GASTAT_FILE = (
    PROJECT_ROOT
    / "data"
    / "open_data"
    / "gastat__fruits_and_vegetables_clean.json"
)

PRODUCTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "gold"
    / "matched_fruits_and_vegetables.json"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "gold"
    / "gastat_fruits_and_vegetables_matched.json"
)


# ============================================================
# SETTINGS
# ============================================================

# Fuzzy matching is retained only as an opt-in diagnostic fallback.  The
# validated first-stage file is the source of truth for production matching.
ENABLE_FUZZY_FALLBACK = False

# Minimum score for fuzzy matching when explicitly enabled.
FUZZY_THRESHOLD = 0.70

# Weights used by fuzzy matching.
NAME_WEIGHT = 0.70
ROOT_WEIGHT = 0.30


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(value):
    """
    Normalize Arabic and English text.

    This removes differences caused by:
    - uppercase/lowercase
    - Arabic diacritics
    - common Arabic character variations
    - punctuation
    - extra spaces
    """

    if value is None:
        return ""

    value = str(value).strip().lower()

    # Remove Arabic diacritics
    value = re.sub(
        r"[\u064B-\u065F\u0670]",
        "",
        value
    )

    # Normalize common Arabic characters
    arabic_replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
    }

    for old, new in arabic_replacements.items():
        value = value.replace(old, new)

    # Unicode normalization
    value = unicodedata.normalize(
        "NFKC",
        value
    )

    # Remove punctuation
    value = re.sub(
        r"[^\w\s]",
        " ",
        value,
        flags=re.UNICODE
    )

    # Normalize spaces
    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def tokenize(value):
    """
    Convert text into normalized tokens.
    """

    normalized = normalize_text(value)

    if not normalized:
        return set()

    return set(normalized.split())


# ============================================================
# SIMILARITY
# ============================================================

def text_similarity(text1, text2):
    """
    Calculate similarity between two text values.

    Uses:
    1. Exact match
    2. Substring match
    3. Sequence similarity
    4. Token similarity
    """

    a = normalize_text(text1)
    b = normalize_text(text2)

    if not a or not b:
        return 0.0

    # Exact match
    if a == b:
        return 1.0

    # One string contains the other
    if a in b or b in a:
        return 0.90

    # Character-level similarity
    sequence_score = SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    # Token-level similarity
    tokens_a = tokenize(a)
    tokens_b = tokenize(b)

    if tokens_a and tokens_b:

        intersection = len(
            tokens_a & tokens_b
        )

        union = len(
            tokens_a | tokens_b
        )

        token_score = (
            intersection / union
            if union
            else 0.0
        )

    else:
        token_score = 0.0

    return max(
        sequence_score,
        token_score
    )


# ============================================================
# ID HELPERS
# ============================================================

def normalize_id(value):
    """
    Normalize an ID so that:
        1
        "1"
        1.0

    can be compared safely.
    """

    if value is None:
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ============================================================
# PRODUCT ROOT
# ============================================================

def get_product_root(product):
    """
    Get commodity_root from the product source.

    If commodity_root is missing,
    derive a fallback root from the product name.
    """

    root = product.get("commodity_root")

    if root:
        return normalize_text(root)

    product_name_en = product.get(
        "product_name_en",
        ""
    )

    product_name_ar = product.get(
        "product_name_ar",
        ""
    )

    if product_name_en:

        words = tokenize(product_name_en)

        if words:
            return max(
                words,
                key=len
            )

    if product_name_ar:

        words = tokenize(product_name_ar)

        if words:
            return max(
                words,
                key=len
            )

    return ""


# ============================================================
# GASTAT ROOT
# ============================================================

def get_gastat_root(record):
    """
    Derive a searchable root from the GASTAT
    English and Arabic names.
    """

    english_name = record.get(
        "item_name_en",
        ""
    )

    arabic_name = record.get(
        "item_name_ar",
        ""
    )

    # Try English first
    english_words = tokenize(
        english_name
    )

    if english_words:
        return max(
            english_words,
            key=len
        )

    # Then Arabic
    arabic_words = tokenize(
        arabic_name
    )

    if arabic_words:
        return max(
            arabic_words,
            key=len
        )

    return ""


# ============================================================
# PRODUCT NAMES
# ============================================================

def get_product_names(product):
    """
    Return all useful names from the product source.
    """

    return {
        "product_en": normalize_text(
            product.get(
                "product_name_en",
                ""
            )
        ),

        "product_ar": normalize_text(
            product.get(
                "product_name_ar",
                ""
            )
        ),

        "official_en": normalize_text(
            product.get(
                "official_gastat_name_en",
                ""
            )
        ),

        "official_ar": normalize_text(
            product.get(
                "official_gastat_name_ar",
                ""
            )
        ),
    }


# ============================================================
# CALCULATE FUZZY SCORE
# ============================================================

def calculate_fuzzy_score(
    gastat_record,
    product
):
    """
    Dynamically calculate how strongly a product
    matches a GASTAT record.

    No product-specific manual mapping is used.
    """

    gastat_en = normalize_text(
        gastat_record.get(
            "item_name_en",
            ""
        )
    )

    gastat_ar = normalize_text(
        gastat_record.get(
            "item_name_ar",
            ""
        )
    )

    gastat_root = get_gastat_root(
        gastat_record
    )

    product_names = get_product_names(
        product
    )

    # --------------------------------------------------------
    # Compare GASTAT name with product name
    # --------------------------------------------------------

    english_score = text_similarity(
        gastat_en,
        product_names["product_en"]
    )

    arabic_score = text_similarity(
        gastat_ar,
        product_names["product_ar"]
    )

    # Also compare against official GASTAT names
    # supplied by the product source.
    official_english_score = text_similarity(
        gastat_en,
        product_names["official_en"]
    )

    official_arabic_score = text_similarity(
        gastat_ar,
        product_names["official_ar"]
    )

    name_score = max(
        english_score,
        arabic_score,
        official_english_score,
        official_arabic_score
    )

    # --------------------------------------------------------
    # Root similarity
    # --------------------------------------------------------

    product_root = get_product_root(
        product
    )

    root_score = text_similarity(
        gastat_root,
        product_root
    )

    # --------------------------------------------------------
    # Final score
    # --------------------------------------------------------

    final_score = (
        NAME_WEIGHT * name_score
        + ROOT_WEIGHT * root_score
    )

    return final_score


# ============================================================
# FIND MATCHES
# ============================================================

def _add_unique_index_entry(index, key, product):
    """Add a normalized key only when it identifies one cluster uniquely."""

    if not key:
        return

    if key not in index:
        index[key] = product
    elif index[key] is not product:
        # An ambiguous name must never produce a deterministic match.
        index[key] = None


def build_exact_match_index(products):
    """Index validated clusters by their official GASTAT names and key."""

    index = {
        "official_ar": {},
        "official_en": {},
        "gastat_key": {},
    }

    for product in products:
        _add_unique_index_entry(
            index["official_ar"],
            normalize_text(product.get("official_gastat_name_ar")),
            product,
        )
        _add_unique_index_entry(
            index["official_en"],
            normalize_text(product.get("official_gastat_name_en")),
            product,
        )
        _add_unique_index_entry(
            index["gastat_key"],
            normalize_text(product.get("gastat_key")),
            product,
        )

    return index


def find_matches(gastat_record, exact_index, products=None):
    """
    Find ALL products matching one GASTAT product.

    Matching priority:

    1. exact official Arabic name
    2. exact official English name
    3. exact gastat_key against a source GASTAT name
    4. optional fuzzy fallback (disabled by default)
    """

    official_ar = normalize_text(gastat_record.get("item_name_ar"))
    official_en = normalize_text(gastat_record.get("item_name_en"))

    for index_name, key in (
        ("official_ar", official_ar),
        ("official_en", official_en),
        ("gastat_key", official_ar),
        ("gastat_key", official_en),
    ):
        product = exact_index[index_name].get(key)
        if product is not None:
            return [{"product": product, "score": 1.0}]

    # The first-stage clusters are validated; unmatched commodities are
    # deliberately left unmatched unless this safety switch is enabled.
    if not ENABLE_FUZZY_FALLBACK or not products:
        return []

    fuzzy_matches = []

    for product in products:

        score = calculate_fuzzy_score(
            gastat_record,
            product
        )

        if score >= FUZZY_THRESHOLD:

            fuzzy_matches.append(
                {
                    "product": product,
                    "score": score
                }
            )

    # Highest confidence first
    fuzzy_matches.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return fuzzy_matches


# ============================================================
# BARCODE
# ============================================================

def get_barcode(product):
    """
    Extract barcode safely.

    Null or empty barcodes are ignored.
    """

    barcode = product.get(
        "barcode"
    )

    if barcode is None:
        return None

    barcode = str(
        barcode
    ).strip()

    if not barcode:
        return None

    return barcode


def _append_valid_barcodes(value, barcodes):
    """Append one barcode or a barcode list, preserving first-seen order."""

    values = value if isinstance(value, list) else [value]

    for candidate in values:
        if candidate is None:
            continue

        barcode = str(candidate).strip()
        if barcode and barcode not in barcodes:
            barcodes.append(barcode)


def get_matched_barcodes(product):
    """Collect actual store barcodes; never use raw_product_id as a barcode."""

    barcodes = []
    stores_data = product.get("stores_data")

    if isinstance(stores_data, dict):
        for store_data in stores_data.values():
            if not isinstance(store_data, dict):
                continue
            _append_valid_barcodes(store_data.get("barcode"), barcodes)
            _append_valid_barcodes(store_data.get("barcodes"), barcodes)

    # Current source data has no store-level barcode fields for some clusters.
    if not barcodes:
        _append_valid_barcodes(product.get("barcode"), barcodes)

    return barcodes


def get_store_coverage(product):
    """Return validated store coverage for a first-stage Gold cluster."""

    matched_stores_count = product.get("matched_stores_count")
    try:
        if matched_stores_count is not None:
            return int(matched_stores_count)
    except (TypeError, ValueError):
        pass

    stores_data = product.get("stores_data")
    return len(stores_data) if isinstance(stores_data, dict) else 0


# ============================================================
# LOAD JSON
# ============================================================

def load_json(file_path):
    """
    Load JSON using UTF-8.
    """

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


# ============================================================
# EXTRACT RECORDS
# ============================================================

def extract_gastat_records(data):
    """
    Support both:

        {
            "records": [...]
        }

    and:

        [...]
    """

    if isinstance(data, dict):

        records = data.get(
            "records"
        )

        if not isinstance(
            records,
            list
        ):
            raise ValueError(
                "GASTAT JSON does not contain a valid 'records' list."
            )

        return records

    if isinstance(data, list):
        return data

    raise ValueError(
        "Unsupported GASTAT JSON structure."
    )


def extract_products(data):
    """
    Support different product JSON structures:

        [...]
        {"records": [...]}
        {"products": [...]}
    """

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        if isinstance(
            data.get("records"),
            list
        ):
            return data["records"]

        if isinstance(
            data.get("products"),
            list
        ):
            return data["products"]

    raise ValueError(
        "Could not find product records in product JSON."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("GASTAT ↔ FRUITS & VEGETABLES MATCHING PIPELINE")
    print("=" * 70)

    # ========================================================
    # CHECK FILES
    # ========================================================

    print("\nChecking files...")

    if not GASTAT_FILE.exists():

        raise FileNotFoundError(
            f"GASTAT file not found:\n{GASTAT_FILE}"
        )

    if not PRODUCTS_FILE.exists():

        raise FileNotFoundError(
            f"Products file not found:\n{PRODUCTS_FILE}"
        )

    print(f"GASTAT file   : {GASTAT_FILE}")
    print(f"Products file : {PRODUCTS_FILE}")

    # ========================================================
    # LOAD FILES
    # ========================================================

    print("\nLoading GASTAT data...")

    gastat_data = load_json(
        GASTAT_FILE
    )

    print("Loading fruits & vegetables data...")

    products_data = load_json(
        PRODUCTS_FILE
    )

    # ========================================================
    # EXTRACT RECORDS
    # ========================================================

    gastat_records = extract_gastat_records(
        gastat_data
    )

    products = extract_products(
        products_data
    )

    print(
        f"\nGASTAT records   : {len(gastat_records)}"
    )

    print(
        f"Product records  : {len(products)}"
    )

    # ========================================================
    # DETERMINISTIC FIRST-STAGE INDEX
    # ========================================================

    exact_index = build_exact_match_index(products)

    # ========================================================
    # MATCH CACHE
    #
    # Same GASTAT product appears in multiple years.
    # We calculate its matches only once.
    # ========================================================

    match_cache = {}

    # ========================================================
    # OUTPUT RECORDS
    # ========================================================

    output_records = []

    for index, record in enumerate(
        gastat_records,
        start=1
    ):

        # ----------------------------------------------------
        # Cache by GASTAT ID when available.
        # Otherwise use the normalized names.
        # ----------------------------------------------------

        gastat_id = normalize_id(
            record.get(
                "gastat_id"
            )
        )

        if gastat_id is not None:

            cache_key = (
                "gastat_id",
                gastat_id
            )

        else:

            cache_key = (
                "names",
                normalize_text(
                    record.get(
                        "item_name_en",
                        ""
                    )
                ),
                normalize_text(
                    record.get(
                        "item_name_ar",
                        ""
                    )
                )
            )

        # ----------------------------------------------------
        # Calculate only once per unique GASTAT product.
        # ----------------------------------------------------

        if cache_key not in match_cache:

            matches = find_matches(
                record,
                exact_index,
                products,
            )

            if matches:
                product = matches[0]["product"]
                match_cache[cache_key] = {
                    "match_count": get_store_coverage(product),
                    "matched_barcodes": get_matched_barcodes(product),
                }
            else:
                match_cache[cache_key] = {
                    "match_count": 0,
                    "matched_barcodes": [],
                }

        # ----------------------------------------------------
        # Get cached match information.
        # ----------------------------------------------------

        match_info = match_cache[
            cache_key
        ]

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Copy the original GASTAT record.
        #
        # Existing fields are NOT changed.
        # Only the two requested fields are added.
        # ----------------------------------------------------

        new_record = dict(
            record
        )

        new_record[
            "match_count"
        ] = match_info[
            "match_count"
        ]

        new_record[
            "matched_barcodes"
        ] = match_info[
            "matched_barcodes"
        ]

        output_records.append(
            new_record
        )

        # ----------------------------------------------------
        # Progress
        # ----------------------------------------------------

        if index % 100 == 0:

            print(
                f"Processed {index}/{len(gastat_records)} records..."
            )

    # ========================================================
    # PRESERVE TOP-LEVEL STRUCTURE
    # ========================================================

    if isinstance(
        gastat_data,
        dict
    ):

        # Copy the original top-level object
        output_data = dict(
            gastat_data
        )

        # Replace ONLY records
        output_data[
            "records"
        ] = output_records

    else:

        output_data = output_records

    # ========================================================
    # CREATE OUTPUT FOLDER
    # ========================================================

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # SAVE OUTPUT
    # ========================================================

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output_data,
            file,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # STATISTICS
    # ========================================================

    distinct_commodities = len(match_cache)
    matched_commodities = sum(
        1 for value in match_cache.values() if value["match_count"] > 0
    )
    unmatched_commodities = distinct_commodities - matched_commodities
    matched_historical_records = sum(
        1 for record in output_records if record["match_count"] > 0
    )
    coverage_distribution = Counter(
        record["match_count"] for record in output_records
    )

    # ========================================================
    # FINAL REPORT
    # ========================================================

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETED")
    print("=" * 70)

    print(
        f"Total historical records      : {len(gastat_records)}"
    )

    print(
        f"Distinct GASTAT commodities  : {distinct_commodities}"
    )

    print(
        f"Matched distinct commodities : {matched_commodities}"
    )

    print(
        f"Unmatched distinct commodities: {unmatched_commodities}"
    )

    print(
        f"Records with match_count > 0 : {matched_historical_records}"
    )

    print(
        "match_count distribution     : "
        + ", ".join(
            f"{count}={coverage_distribution[count]}"
            for count in sorted(coverage_distribution)
        )
    )

    print(
        f"\nOutput file:"
    )

    print(
        OUTPUT_FILE
    )

    # ========================================================
    # SHOW MATCH SUMMARY
    # ========================================================

    print("\nMatch summary:")

    for key, value in match_cache.items():

        if key[0] == "gastat_id":

            display_key = f"GASTAT ID {key[1]}"

        else:

            display_key = key[1]

        print(
            f"  {display_key}: "
            f"{value['match_count']} match(es)"
        )

    print("\nDone.")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
