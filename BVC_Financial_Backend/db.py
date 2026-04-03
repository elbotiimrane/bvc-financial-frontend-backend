import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "listings.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id               TEXT PRIMARY KEY,
            title            TEXT,
            type             TEXT,
            "transaction"    TEXT,
            city             TEXT,
            neighborhood     TEXT,
            surface          REAL,
            rooms            INTEGER,
            price            INTEGER,
            price_per_sqm    INTEGER,
            status           TEXT DEFAULT 'Actif',
            date_listing     TEXT,
            date_transaction TEXT,
            date_sold        TEXT,
            source           TEXT,
            seller           TEXT,
            url              TEXT,
            scraped_at       TEXT
        )
    """)
    conn.commit()
    conn.close()


def upsert_listing(listing: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO listings
            (id, title, type, "transaction", city, neighborhood,
             surface, rooms, price, price_per_sqm, status, 
             date_listing, date_transaction, date_sold,
             source, seller, url, scraped_at)
        VALUES
            (:id, :title, :type, :transaction, :city, :neighborhood,
             :surface, :rooms, :price, :price_per_sqm, :status,
             :date_listing, :date_transaction, :date_sold,
             :source, :seller, :url, :scraped_at)
    """, listing)
    conn.commit()
    conn.close()


def upsert_many(listings: list[dict]):
    if not listings:
        return
    conn = get_conn()
    conn.executemany("""
        INSERT OR REPLACE INTO listings
            (id, title, type, "transaction", city, neighborhood,
             surface, rooms, price, price_per_sqm, status,
             date_listing, date_transaction, date_sold,
             source, seller, url, scraped_at)
        VALUES
            (:id, :title, :type, :transaction, :city, :neighborhood,
             :surface, :rooms, :price, :price_per_sqm, :status,
             :date_listing, :date_transaction, :date_sold,
             :source, :seller, :url, :scraped_at)
    """, listings)
    conn.commit()
    conn.close()


def get_all_listings(city=None, txn=None, prop_type=None, q=None):
    conn = get_conn()
    clauses = []
    params = []
    if city:
        clauses.append("city = ?")
        params.append(city)
    if txn:
        clauses.append('"transaction" = ?')
        params.append(txn)
    if prop_type:
        clauses.append("type = ?")
        params.append(prop_type)
    if q:
        clauses.append("(title LIKE ? OR city LIKE ? OR neighborhood LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(f"SELECT * FROM listings {where} ORDER BY scraped_at DESC", params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_conn()
    
    # 1. Base Counts
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    sales = conn.execute('SELECT COUNT(*) FROM listings WHERE "transaction"=\'Vente\'').fetchone()[0]
    rents = conn.execute('SELECT COUNT(*) FROM listings WHERE "transaction"=\'Location\'').fetchone()[0]
    
    # 2. Robust Average (Trim top/bottom 5% outliers)
    # We fetch all Sale prices and trim manually for precision
    conn.row_factory = None # Simple fetch
    prices = [r[0] for r in conn.execute('SELECT price_per_sqm FROM listings WHERE "transaction"=\'Vente\' AND price_per_sqm > 0 ORDER BY price_per_sqm').fetchall()]
    conn.row_factory = sqlite3.Row
    
    avg_ppsm = 0
    if prices:
        trim = max(1, int(len(prices) * 0.05))
        trimmed = prices[trim:-trim] if len(prices) > (trim * 2) else prices
        avg_ppsm = sum(trimmed) / len(trimmed) if trimmed else 0

    # 3. City distribution with trimmed averages
    city_stats = []
    unique_cities = [r[0] for r in conn.execute('SELECT DISTINCT city FROM listings WHERE "transaction"=\'Vente\'').fetchall()]
    for city in unique_cities:
        city_prices = [r[0] for r in conn.execute('SELECT price_per_sqm FROM listings WHERE city=? AND "transaction"=\'Vente\' AND price_per_sqm > 0 ORDER BY price_per_sqm', (city,)).fetchall()]
        if city_prices:
            trim = int(len(city_prices) * 0.05)
            trimmed = city_prices[trim:-trim] if len(city_prices) > (trim * 2) else city_prices
            city_avg = sum(trimmed) / len(trimmed) if trimmed else 0
            city_stats.append({
                "city": city,
                "count": len(city_prices),
                "avg_ppsm": round(city_avg)
            })
    
    # Sort cities by price desc
    city_stats.sort(key=lambda x: x["avg_ppsm"], reverse=True)

    types = conn.execute(
        "SELECT type, COUNT(*) as count FROM listings GROUP BY type ORDER BY count DESC"
    ).fetchall()
    conn.close()
    
    return {
        "total": total,
        "sales": sales,
        "rents": rents,
        "avg_price_per_sqm": round(avg_ppsm),
        "cities": city_stats,
        "types": [dict(r) for r in types],
    }


def clear_listings():
    conn = get_conn()
    conn.execute("DELETE FROM listings")
    conn.commit()
    conn.close()


def count_listings():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    conn.close()
    return n
