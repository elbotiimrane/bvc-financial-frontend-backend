import sqlite3

def verify():
    conn = sqlite3.connect('listings.db')
    cursor = conn.cursor()
    
    # Deep Logical Anomaly check
    print("\n--- DEEP LOGICAL ANOMALY LOG ---")
    
    cursor.execute("""
        SELECT title, price, surface, "transaction", source, url 
        FROM listings 
        WHERE ("transaction"='Vente' AND price < 15000)
           OR ("transaction"='Location' AND price > 200000)
           OR length(title) < 5
        LIMIT 100
    """)
    rows = cursor.fetchall()
    if rows:
        for r in rows:
            print(f"ANOMALY: [{r[4]}] {r[3]} | {r[1]} MAD | {r[0]}")
    else:
        print("No deep logical anomalies found.")

    # Source distribution
    cursor.execute('SELECT source, COUNT(*) FROM listings GROUP BY source')
    dist = {row[0]: row[1] for row in cursor.fetchall()}
    print(f"\nSource Counts: {dist}")

    conn.close()

if __name__ == "__main__":
    verify()
