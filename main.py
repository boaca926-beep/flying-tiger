"""Flying Tiger product fetcher — uses Shopify's public /products.json API.

No HTML parsing. No pagination guessing. Just structured JSON.

Usage:
    uv run main.py

Outputs:
    flyingtiger.db      SQLite database
    products.csv        Spreadsheet view
    products.json       LLM-friendly view
"""
import csv
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import requests

# --- config ---
BASE_URL = os.environ.get("FT_BASE_URL", "https://flyingtiger.com")
CURRENCY = os.environ.get("FT_CURRENCY", "EUR")   # adjust per store
DB_PATH = "flyingtiger.db"
CSV_PATH = "products.csv"
JSON_PATH = "products.json"
PAGE_LIMIT = 250
REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProductResearchBot/1.0)",
    "Accept": "application/json",
}


# ---------- fetch ----------
def fetch_page(page: int) -> list[dict]:
    """Fetch one page of products. Returns [] when no more pages."""
    url = f"{BASE_URL}/products.json?limit={PAGE_LIMIT}&page={page}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("products", [])
    except requests.HTTPError as e:
        print(f"  ! HTTP {e.response.status_code} on page {page}")
        return []
    except Exception as e:
        print(f"  ! {type(e).__name__}: {e}")
        return []


def fetch_all() -> list[dict]:
    """Paginate through the entire catalog."""
    all_products = []
    page = 1
    while True:
        products = fetch_page(page)
        if not products:
            break
        all_products.extend(products)
        print(f"  page {page:>3}  +{len(products):>3}  (total {len(all_products)})")
        page += 1
        time.sleep(REQUEST_DELAY)
    return all_products


# ---------- parse ----------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(html: str | None, max_len: int = 400) -> str | None:
    if not html:
        return None
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text[:max_len] if text else None


def parse_category(product: dict) -> str | None:
    """Prefer 'Category: X' tag, fall back to product_type."""
    for tag in product.get("tags", []) or []:
        if tag.lower().startswith("category:"):
            return tag.split(":", 1)[1].strip()
    return product.get("product_type") or None


def parse_product(p: dict) -> dict | None:
    pid = p.get("id")
    title = (p.get("title") or "").strip()
    if not pid or not title:
        return None

    variants = p.get("variants") or []
    if not variants:
        return None

    # price: cheapest variant
    prices = []
    compare_prices = []
    for v in variants:
        try:
            prices.append(float(v.get("price") or 0))
        except (TypeError, ValueError):
            pass
        cp = v.get("compare_at_price")
        if cp:
            try:
                compare_prices.append(float(cp))
            except (TypeError, ValueError):
                pass

    price = min(prices) if prices else None
    compare_at = max(compare_prices) if compare_prices else None
    on_sale = 1 if (compare_at and price and compare_at > price) else 0

    # availability: any variant available
    available = 1 if any(v.get("available") for v in variants) else 0

    # first variant for sku, grams
    v0 = variants[0]
    sku = v0.get("sku") or None
    try:
        grams = float(v0.get("grams") or 0) or None
    except (TypeError, ValueError):
        grams = None

    # price per 100g
    price_per_100g = None
    if price and grams and grams > 0:
        price_per_100g = round(price * 100 / grams, 2)

    # images
    images = p.get("images") or []
    image_url = images[0].get("src") if images else None

    return {
        "shopify_id": str(pid),
        "title": title,
        "handle": p.get("handle"),
        "vendor": p.get("vendor"),
        "product_type": p.get("product_type"),
        "category": parse_category(p),
        "tags": ", ".join(p.get("tags") or [])[:500] or None,
        "description": strip_html(p.get("body_html")),
        "price": price,
        "compare_at_price": compare_at,
        "currency": CURRENCY,
        "on_sale": on_sale,
        "available": available,
        "sku": sku,
        "grams": grams,
        "price_per_100g": price_per_100g,
        "image_url": image_url,
        "image_count": len(images),
        "variant_count": len(variants),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "published_at": p.get("published_at"),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------- DB ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shopify_id TEXT UNIQUE,
            title TEXT,
            handle TEXT,
            vendor TEXT,
            product_type TEXT,
            category TEXT,
            tags TEXT,
            description TEXT,
            price REAL,
            compare_at_price REAL,
            currency TEXT,
            on_sale INTEGER,
            available INTEGER,
            sku TEXT,
            grams REAL,
            price_per_100g REAL,
            image_url TEXT,
            image_count INTEGER,
            variant_count INTEGER,
            created_at TEXT,
            updated_at TEXT,
            published_at TEXT,
            scraped_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn


def upsert(conn, p: dict):
    conn.execute("""
        INSERT INTO products
          (shopify_id, title, handle, vendor, product_type, category, tags,
           description, price, compare_at_price, currency, on_sale, available,
           sku, grams, price_per_100g, image_url, image_count, variant_count,
           created_at, updated_at, published_at, scraped_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(shopify_id) DO UPDATE SET
            title=excluded.title,
            handle=excluded.handle,
            vendor=excluded.vendor,
            product_type=excluded.product_type,
            category=excluded.category,
            tags=excluded.tags,
            description=excluded.description,
            price=excluded.price,
            compare_at_price=excluded.compare_at_price,
            currency=excluded.currency,
            on_sale=excluded.on_sale,
            available=excluded.available,
            sku=excluded.sku,
            grams=excluded.grams,
            price_per_100g=excluded.price_per_100g,
            image_url=excluded.image_url,
            image_count=excluded.image_count,
            variant_count=excluded.variant_count,
            updated_at=excluded.updated_at,
            scraped_at=excluded.scraped_at
    """, (
        p["shopify_id"], p["title"], p["handle"], p["vendor"], p["product_type"],
        p["category"], p["tags"], p["description"], p["price"], p["compare_at_price"],
        p["currency"], p["on_sale"], p["available"], p["sku"], p["grams"],
        p["price_per_100g"], p["image_url"], p["image_count"], p["variant_count"],
        p["created_at"], p["updated_at"], p["published_at"], p["scraped_at"],
    ))


# ---------- exports ----------
def export_csv(cur):
    cols = ["shopify_id", "title", "vendor", "product_type", "category",
            "price", "compare_at_price", "currency", "on_sale", "available",
            "sku", "grams", "price_per_100g", "handle", "image_url"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in cur.execute(f"SELECT {','.join(cols)} FROM products ORDER BY title"):
            w.writerow(row)
    print(f"CSV   → {CSV_PATH}")


def export_json(cur):
    cols = ["shopify_id", "title", "handle", "vendor", "product_type", "category",
            "tags", "description", "price", "compare_at_price", "currency",
            "on_sale", "available", "sku", "grams", "price_per_100g",
            "image_url", "image_count", "variant_count",
            "created_at", "updated_at", "published_at", "scraped_at"]
    rows = [dict(zip(cols, r)) for r in cur.execute(
        f"SELECT {','.join(cols)} FROM products ORDER BY title"
    )]
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"JSON  → {JSON_PATH} ({len(rows)} records)")


# ---------- main ----------
def main():
    print(f"Flying Tiger scraper")
    print(f"Source: {BASE_URL}/products.json")
    print(f"Currency: {CURRENCY}\n")

    print("Fetching products...")
    raw = fetch_all()
    print(f"\nFetched {len(raw)} raw products\n")

    print("Parsing...")
    parsed = [p for p in (parse_product(r) for r in raw) if p]
    print(f"Parsed {len(parsed)} products")

    print("\nWriting to database...")
    conn = init_db()
    cur = conn.cursor()
    for p in parsed:
        upsert(conn, p)
    conn.commit()

    total, avail, sale, with_grams = cur.execute("""
        SELECT COUNT(*), SUM(available), SUM(on_sale),
               SUM(CASE WHEN grams IS NOT NULL THEN 1 ELSE 0 END)
        FROM products
    """).fetchone()

    print(f"\nDB    → {DB_PATH}")
    print(f"        {total} products")
    print(f"        {avail} in stock")
    print(f"        {sale} on sale")
    print(f"        {with_grams} with weight data")

    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO meta (key, value) VALUES ('last_updated', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (now,),
    )
    conn.commit()
    print(f"        last_updated = {now}")

    export_csv(cur)
    export_json(cur)
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()