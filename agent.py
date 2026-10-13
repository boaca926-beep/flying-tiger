"""SQL agent for the Flying Tiger product catalog — Groq."""
import json
import os
import sqlite3
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DB_PATH = "flyingtiger.db"

# --- LLM config ---
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
API_KEY  = os.environ.get("LLM_API_KEY",  os.environ.get("GROQ_API_KEY", "EMPTY"))
MODEL    = os.environ.get("LLM_MODEL",    "openai/gpt-oss-120b")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

SCHEMA = """
SQLite table: products
Columns:
  shopify_id       TEXT    -- unique product ID from Shopify
  title            TEXT    -- product name (English)
  handle           TEXT    -- URL slug; product page is https://flyingtiger.com/products/<handle>
  vendor           TEXT    -- usually "Flying Tiger Copenhagen"
  product_type     TEXT    -- e.g. 'Home', 'Toys', 'Kitchen'
  category         TEXT    -- category from tags, e.g. 'Decoration'
  tags             TEXT    -- comma-separated tags
  description      TEXT    -- short plain-text description
  price            REAL    -- current price
  compare_at_price REAL    -- original price if on sale (NULL otherwise)
  currency         TEXT    -- currency code
  on_sale          INTEGER -- 1 = has discount, 0 = full price
  available        INTEGER -- 1 = in stock, 0 = out of stock
  sku              TEXT    -- article number
  grams            REAL    -- weight in grams (may be NULL)
  price_per_100g   REAL    -- price per 100g (NULL if no weight)
  image_url        TEXT
  image_count      INTEGER
  variant_count    INTEGER
  created_at       TEXT
  updated_at       TEXT
  published_at     TEXT
  scraped_at       TEXT

Notes:
  - Prices are in the store's currency (see `currency` column).
  - Use LOWER(col) LIKE for case-insensitive text search.
  - product_type is a coarse filter ('Home', 'Toys', 'Kitchen', ...).
  - category is finer and comes from tags.
  - For "sale" / "discount" queries: WHERE on_sale = 1
  - For value queries: ORDER BY price_per_100g ASC
  - Default LIMIT is 8 unless the user asks for more.

Examples:
  'christmas decorations under 50 kr' →
    SELECT shopify_id, title, price, available, handle, image_url, grams
    FROM products
    WHERE (LOWER(title) LIKE '%christmas%' OR LOWER(category) LIKE '%christmas%')
      AND price < 50
    ORDER BY price ASC LIMIT 8

  'what's on sale?' →
    SELECT shopify_id, title, price, compare_at_price, available, handle, image_url, grams
    FROM products
    WHERE on_sale = 1
    ORDER BY (compare_at_price - price) DESC LIMIT 8

  'toys for kids' →
    SELECT shopify_id, title, price, available, handle, image_url, grams
    FROM products
    WHERE product_type = 'Toys'
    ORDER BY price ASC LIMIT 8

  'cheapest mugs' →
    SELECT shopify_id, title, price, available, handle, image_url, grams
    FROM products
    WHERE LOWER(title) LIKE '%mug%'
    ORDER BY price ASC LIMIT 8
"""

SYSTEM_PROMPT = (
    "You are a helpful assistant for the Flying Tiger Copenhagen "
    "product catalog. Answer every question by calling run_sql — "
    "never answer from memory.\n\n"
    f"{SCHEMA}\n"
    "REMINDER:\n"
    "- Product queries: select shopify_id, title, price, available, "
    "handle, image_url, grams.\n"
    "- Aggregate queries (COUNT/AVG/SUM): select only the aggregate.\n"
    "- Always ORDER BY something (price, price_per_100g, or discount).\n"
    "- Call run_sql ONCE. Only retry if the query returned an ERROR.\n"
    "- Answer in the user's language.\n\n"
    "When presenting results, list items with prices. Keep it concise."
)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": "Run a read-only SELECT query against the products table.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A single SELECT statement."}
            },
            "required": ["query"],
        },
    },
}]


# ---------- SQL runner ----------
def run_sql(query: str) -> dict:
    q = query.strip().rstrip(";").strip()
    low = q.lower()
    if not low.startswith(("select", "with")):
        return {"error": "only SELECT / WITH queries are allowed"}
    if any(k in low for k in ("insert", "update", "delete", "drop", "alter",
                              "attach", "pragma", "vacuum")):
        return {"error": "write/admin SQL is not allowed"}
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(q).fetchall()]
        conn.close()
        return {"rows": rows[:200], "row_count": len(rows)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------- structured output ----------
_ROW_ALIASES = {
    "shopify_id": "shopify_id", "id": "shopify_id", "sku": "shopify_id",
    "title": "title", "name": "title",
    "price": "price",
    "available": "available", "in_stock": "available",
    "handle": "handle", "url": "handle",
    "image_url": "image_url", "image": "image_url",
    "grams": "grams", "weight_g": "grams",
    "compare_at_price": "compare_at_price",
    "on_sale": "on_sale",
}


def _normalize_row(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        key = _ROW_ALIASES.get(str(k).lower(), str(k).lower())
        out.setdefault(key, v)
    return out


def _row_to_product(row: dict) -> dict | None:
    n = _normalize_row(row)
    if "title" not in n or "price" not in n:
        return None
    if n.get("price") is None:
        return None
    avail = n.get("available")
    return {
        "id": n.get("shopify_id"),
        "name": n["title"],
        "price": float(n["price"]),
        "compare_at_price": (
            float(n["compare_at_price"]) if n.get("compare_at_price") else None
        ),
        "on_sale": bool(n.get("on_sale")) if n.get("on_sale") is not None else False,
        "available": None if avail is None else bool(avail),
        "handle": n.get("handle"),
        "image_url": n.get("image_url"),
        "grams": n.get("grams"),
    }


def _dedupe(products: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for p in products:
        key = p.get("id") or p["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------- agent ----------
def run_agent(question, verbose=False):
    """Run one question. Returns (answer_text, meta).

    meta = {
        "sql":      [str, ...],
        "products": [{id, name, price, available, handle, image_url, grams, ...}, ...],
        "kind":     "products" | "aggregate" | "empty" | "error",
        "error":    str | None,
    }
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    sqls = []
    products = []
    last_error = None

    for i in range(4):
        tools = TOOLS if i < 3 else None

        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=0,
            max_tokens=512,
        )
        msg = resp.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            answer = msg.content or "(no answer)"
            if products:
                kind = "products"
            elif any("products" in s.lower() for s in sqls):
                kind = "aggregate"
            else:
                kind = "empty"
            return answer, {
                "sql": sqls,
                "products": _dedupe(products),
                "kind": kind,
                "error": last_error,
            }

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            sql = args.get("query", "")
            sqls.append(sql)
            if verbose:
                print(f"  [SQL] {sql}")
            result = run_sql(sql)
            if "error" in result:
                last_error = result["error"]
                if verbose:
                    print(f"  [err] {last_error}")
            else:
                if verbose:
                    print(f"  [ok ] {result['row_count']} rows")
                for r in result.get("rows", []):
                    p = _row_to_product(r)
                    if p is not None:
                        products.append(p)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False)[:8000],
            })

    return "(too many tool iterations)", {
        "sql": sqls,
        "products": _dedupe(products),
        "kind": "error",
        "error": "too many tool iterations",
    }


def main():
    if len(sys.argv) > 1:
        answer, meta = run_agent(" ".join(sys.argv[1:]), verbose=False)
        print(answer)
        if meta.get("products"):
            print()
            print(json.dumps(meta["products"], ensure_ascii=False, indent=2))
        return

    print(f"Model: {MODEL}  via {BASE_URL}")
    print("Type 'quit' to exit.\n")
    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user or user.lower() in ("quit", "exit", "q"):
            break
        answer, meta = run_agent(user, verbose=True)
        print("\n" + answer + "\n")
        if meta.get("products"):
            print(json.dumps(meta["products"], ensure_ascii=False, indent=2))
            print()


if __name__ == "__main__":
    main()