from pathlib import Path
import sqlite3

import pandas as pd


class DatabaseLoader:
    def __init__(self, database_path: Path, schema_path: Path) -> None:
        self.database_path = database_path
        self.schema_path = schema_path

    def load(self, products: pd.DataFrame) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            connection.executescript(self.schema_path.read_text(encoding="utf-8"))
            connection.execute("DELETE FROM store_products")
            connection.execute("DELETE FROM product_groups")
            groups = products.drop_duplicates("product_group")
            connection.executemany(
                "INSERT INTO product_groups VALUES (?, ?, ?, ?, ?)",
                groups[["product_group", "name", "category", "size_value", "size_unit"]].itertuples(index=False, name=None),
            )
            connection.executemany(
                "INSERT INTO store_products (product_group, store, source_id, name, price, currency, url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                products[["product_group", "store", "source_id", "name", "price", "currency", "url"]].itertuples(index=False, name=None),
            )

    def comparison(self) -> pd.DataFrame:
        query = """
            SELECT product_group, name, store, price, currency, url
            FROM store_products
            ORDER BY product_group, price
        """
        with sqlite3.connect(self.database_path) as connection:
            return pd.read_sql_query(query, connection)
