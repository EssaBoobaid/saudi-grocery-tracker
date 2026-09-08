PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS product_groups (
    product_group INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    category TEXT,
    size_value REAL,
    size_unit TEXT
);

CREATE TABLE IF NOT EXISTS store_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_group INTEGER NOT NULL,
    store TEXT NOT NULL,
    source_id TEXT,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'SAR',
    url TEXT,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_group) REFERENCES product_groups(product_group)
);

CREATE INDEX IF NOT EXISTS idx_store_products_group ON store_products(product_group);
CREATE INDEX IF NOT EXISTS idx_store_products_store ON store_products(store);
