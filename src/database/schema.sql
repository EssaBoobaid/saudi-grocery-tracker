-- ============================================================
-- SAUDI GROCERY TRACKER — DATABASE SCHEMA
-- ============================================================

-- 1. جدول سلع الهيئة العامة للإحصاء (GASTAT)
CREATE TABLE IF NOT EXISTS gastat_commodities (
    gastat_id INTEGER PRIMARY KEY,
    gastat_slug TEXT,
    item_name_ar TEXT NOT NULL,
    item_name_en TEXT NOT NULL,
    unit_ar TEXT,
    unit_en TEXT,
    matched_barcodes TEXT[]
);

-- 2. السلسلة الزمنية لأسعار GASTAT التاريخية
CREATE TABLE IF NOT EXISTS gastat_price_history (
    id SERIAL PRIMARY KEY,
    gastat_id INTEGER NOT NULL REFERENCES gastat_commodities(gastat_id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month TEXT NOT NULL,
    price NUMERIC(10, 2),
    annual_average NUMERIC(10, 2),
    UNIQUE(gastat_id, year, month)
);

-- 3. المنتجات الموحدة والمطابقة (Master Entities)
CREATE TABLE IF NOT EXISTS matched_products (
    product_id SERIAL PRIMARY KEY,
    gastat_id INTEGER REFERENCES gastat_commodities(gastat_id) ON DELETE SET NULL,
    category TEXT NOT NULL,
    product_name_ar TEXT,
    product_name_en TEXT,
    brand TEXT,
    barcode TEXT,
    size NUMERIC(10, 2),
    unit TEXT,
    quantity INTEGER DEFAULT 1,
    total_size NUMERIC(10, 2),
    image_url TEXT,
    canonical_source TEXT,
    match_tier TEXT,
    confidence_score NUMERIC(5, 2),
    matched_stores TEXT[]
);

-- 4. لقطات الأسعار الدورية (Daily Snapshots)
CREATE TABLE IF NOT EXISTS product_price_snapshots (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES matched_products(product_id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    avg_price NUMERIC(10, 2),
    min_price NUMERIC(10, 2),
    max_price NUMERIC(10, 2),
    price_diff NUMERIC(10, 2),
    gastat_benchmark_price NUMERIC(10, 2),
    variance_from_benchmark NUMERIC(10, 2),
    UNIQUE(product_id, snapshot_date)
);

-- 5. أسعار المتاجر التفصيلية
CREATE TABLE IF NOT EXISTS store_item_prices (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES matched_products(product_id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,
    store_name TEXT NOT NULL,
    store_product_id TEXT,
    price NUMERIC(10, 2),
    original_price NUMERIC(10, 2),
    discount_amount NUMERIC(10, 2),
    discount_percentage NUMERIC(5, 2),
    has_discount BOOLEAN DEFAULT FALSE,
    image_url TEXT
);

-- 6. فروع المتاجر ومواقعها الجغرافية
CREATE TABLE IF NOT EXISTS store_branches (
    id SERIAL PRIMARY KEY,
    brand TEXT NOT NULL,
    city_ar TEXT,
    city_en TEXT,
    name_ar TEXT,
    name_en TEXT,
    map_url TEXT
);

-- الفهارس لتحسين سرعة الاستعلامات
CREATE INDEX IF NOT EXISTS idx_matched_category ON matched_products(category);
CREATE INDEX IF NOT EXISTS idx_matched_barcode ON matched_products(barcode);
CREATE INDEX IF NOT EXISTS idx_matched_gastat ON matched_products(gastat_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_date ON product_price_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_store_snapshot ON store_item_prices(snapshot_date, store_name);
CREATE INDEX IF NOT EXISTS idx_branch_brand ON store_branches(brand);
CREATE INDEX IF NOT EXISTS idx_branch_city ON store_branches(city_en);