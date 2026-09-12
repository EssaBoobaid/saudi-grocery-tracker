"""Panda KSA Bronze Ingestion Pipeline.

Fast extractor for Panda Next.js PLP pages.

Bronze rules:
- Preserve each Panda parent product object.
- Preserve all varieties inside each parent product.
- No cleaning / normalization.
- Add only _source_* ingestion metadata.
"""

from __future__ import annotations

import html
import json
import time
import urllib.request
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "bronze" / "panda"

MAX_PAGES = 100

# Small polite delay between page requests.
REQUEST_DELAY = 0.25


CATEGORIES = {
    "beverages": {
        "output_filename": "beverages_raw.json",
        "sources": [
            {
                "category_id": 288,
                "parent_category_id": None,
                "locale": "en",
            },
            {
                "category_id": 821,
                "parent_category_id": None,
                "locale": "en",
            },
            {
                "category_id": 822,
                "parent_category_id": None,
                "locale": "en",
            },
            {
                "category_id": 969,
                "parent_category_id": None,
                "locale": "en",
            },
            {
                "category_id": 971,
                "parent_category_id": None,
                "locale": "en",
            },
            {
                "category_id": 972,
                "parent_category_id": None,
                "locale": "en",
            },
        ],
    },

    "dairy_and_eggs": {
        "output_filename": "dairy_and_eggs_raw.json",
        "sources": [
            {
                "category_id": 356,
                "parent_category_id": 311,
                "locale": "en",
            },
            {
                "category_id": 349,
                "parent_category_id": 311,
                "locale": "en",
            },
            {
                "category_id": 469,
                "parent_category_id": 468,
                "locale": "ar",
            },
        ],
    },

    "fruits_and_vegetables": {
        "output_filename": "fruits_and_vegetables_raw.json",
        "sources": [
            {
                "category_id": 352,
                "parent_category_id": 311,
                "locale": "en",
            },
        ],
    },
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
}


def build_url(
    category_id: int,
    parent_category_id: int | None,
    page: int,
    locale: str,
) -> str:

    params = [
        f"category_id={category_id}",
    ]

    if parent_category_id is not None:
        params.append(
            f"parent_category_id={parent_category_id}"
        )

    params.append(f"page={page}")

    return (
        f"https://panda.sa/{locale}/plp?"
        + "&".join(params)
    )


def fetch_page(
    category_id: int,
    parent_category_id: int | None,
    page: int,
    locale: str,
) -> str:

    url = build_url(
        category_id,
        parent_category_id,
        page,
        locale,
    )

    request = urllib.request.Request(
        url,
        headers=HEADERS,
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:

        if response.status != 200:
            raise RuntimeError(
                f"Panda HTTP {response.status}: {url}"
            )

        return response.read().decode(
            "utf-8",
            errors="ignore",
        )


def decode_page(raw_html: str) -> str:
    """
    Decode HTML / Next.js escaping once.
    """

    text = html.unescape(raw_html)

    text = text.replace('\\"', '"')
    text = text.replace("\\u0026", "&")
    text = text.replace("\\u003c", "<")
    text = text.replace("\\u003e", ">")
    text = text.replace("\\u0027", "'")

    return text


def find_matching_brace(
    text: str,
    start: int,
) -> int | None:
    """
    Find closing brace for one JSON object.

    Starts at `{` and scans forward once.
    """

    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):

        char = text[i]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True

        elif char == "{":
            depth += 1

        elif char == "}":
            depth -= 1

            if depth == 0:
                return i

    return None


def looks_like_parent_product(
    obj: dict[str, Any],
) -> bool:
    """
    Panda parent products look like:

    {
        "id": ...,
        "name": ...,
        "brand": {...},
        "category": {...},
        "varieties": [...]
    }
    """

    varieties = obj.get("varieties")

    return (
        obj.get("id") not in (None, "")
        and bool(obj.get("name"))
        and isinstance(varieties, list)
        and len(varieties) > 0
    )


def extract_products(
    raw_html: str,
) -> list[dict[str, Any]]:
    """
    Extract every Panda parent product.

    Fast strategy:
    - Decode page once.
    - Locate every "varieties" marker.
    - Walk backwards only a limited distance to candidate `{`.
    - Parse the smallest valid parent product.
    """

    text = decode_page(raw_html)

    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    marker = '"varieties":'
    position = 0

    while True:

        marker_pos = text.find(
            marker,
            position,
        )

        if marker_pos == -1:
            break

        #
        # Panda product objects are small enough that
        # we only need to search a limited area backwards.
        #
        search_start = max(
            0,
            marker_pos - 20_000,
        )

        candidate_start = marker_pos

        found_product = None

        while True:

            candidate_start = text.rfind(
                "{",
                search_start,
                candidate_start,
            )

            if candidate_start == -1:
                break

            end = find_matching_brace(
                text,
                candidate_start,
            )

            if end is None:
                break

            #
            # The object must actually contain the varieties
            # marker we started from.
            #
            if not (
                candidate_start
                <= marker_pos
                <= end
            ):
                continue

            candidate = text[
                candidate_start:end + 1
            ]

            try:
                obj = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict):
                continue

            if looks_like_parent_product(obj):

                found_product = obj

                #
                # First valid enclosing object is the
                # smallest parent product object.
                #
                break

        if found_product:

            product_id = str(
                found_product["id"]
            )

            if product_id not in seen_ids:

                seen_ids.add(product_id)

                products.append(
                    found_product
                )

        position = (
            marker_pos
            + len(marker)
        )

    return products


def fetch_source(
    logical_category: str,
    source: dict[str, Any],
) -> list[dict[str, Any]]:

    category_id = source["category_id"]

    parent_category_id = source.get(
        "parent_category_id"
    )

    locale = source.get(
        "locale",
        "en",
    )

    print(
        f"\n[{logical_category}] "
        f"category={category_id} "
        f"parent={parent_category_id}"
    )

    all_products: list[dict[str, Any]] = []

    seen_ids: set[str] = set()

    for page in range(
        1,
        MAX_PAGES + 1,
    ):

        started = time.perf_counter()

        raw_html = fetch_page(
            category_id,
            parent_category_id,
            page,
            locale,
        )

        page_products = extract_products(
            raw_html
        )

        added = 0

        for raw_product in page_products:

            product_id = str(
                raw_product.get("id")
            )

            if product_id in seen_ids:
                continue

            seen_ids.add(product_id)

            #
            # Preserve Panda raw object.
            #
            record = dict(raw_product)

            #
            # Only ingestion metadata.
            #
            record[
                "_source_category_id"
            ] = category_id

            record[
                "_source_parent_category_id"
            ] = parent_category_id

            record[
                "_source_page"
            ] = page

            record[
                "_source_locale"
            ] = locale

            record[
                "_source_url"
            ] = build_url(
                category_id,
                parent_category_id,
                page,
                locale,
            )

            all_products.append(
                record
            )

            added += 1

        elapsed = (
            time.perf_counter()
            - started
        )

        print(
            f"  page {page}"
            f" | found {len(page_products)}"
            f" | new {added}"
            f" | total {len(all_products)}"
            f" | {elapsed:.2f}s"
        )

        #
        # No products = actual end.
        #
        if not page_products:

            print(
                "  -> End of category."
            )

            break

        #
        # If Panda repeats the final page,
        # stop instead of looping to 100.
        #
        if added == 0:

            print(
                "  -> Page repeated. "
                "Pagination complete."
            )

            break

        time.sleep(
            REQUEST_DELAY
        )

    return all_products


def fetch_category(
    category_name: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:

    combined: list[dict[str, Any]] = []

    seen_ids: set[str] = set()

    for source in config["sources"]:

        source_products = fetch_source(
            category_name,
            source,
        )

        for product in source_products:

            #
            # category + product ID avoids accidental
            # collisions across Panda source categories.
            #
            # Product IDs are global at Panda; dedupe across all sources.
            key = str(product.get("id"))

            if key in seen_ids:
                continue

            seen_ids.add(key)

            combined.append(
                product
            )

    return combined


def main() -> None:

    print(
        "=== Starting Panda Bronze Extraction ==="
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    grand_total = 0

    for category_name, config in CATEGORIES.items():

        products = fetch_category(
            category_name,
            config,
        )

        if not products:
            raise RuntimeError(
                f"Panda returned 0 products "
                f"for {category_name}"
            )

        output_file = (
            OUTPUT_DIR
            / config["output_filename"]
        )

        with output_file.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                products,
                file,
                ensure_ascii=False,
                indent=2,
            )

        grand_total += len(products)

        #
        # Count varieties too.
        #
        variety_total = sum(
            len(
                p.get("varieties") or []
            )
            for p in products
        )

        print(
            f"\n  ✓ {category_name}: "
            f"{len(products)} parents "
            f"| {variety_total} varieties "
            f"-> {output_file.name}"
        )

    print(
        "\n=== Panda Bronze Completed "
        f"| parents={grand_total} ==="
    )


if __name__ == "__main__":
    main()