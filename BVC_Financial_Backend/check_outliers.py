import sqlite3

def check():
    conn = sqlite3.connect('listings.db')
    cursor = conn.cursor()
    
    print("--- TOP 10 PRICE PER SQM (ALL CITIES) ---")
    cursor.execute('SELECT city, price, surface, price_per_sqm, title, source, url FROM listings ORDER BY price_per_sqm DESC LIMIT 10')
    for r in cursor.fetchall():
        print(f"[{r[0]}] {r[1]} MAD | {r[2]}m2 | {r[3]} MAD/m2 | {r[4][:40]}... | {r[5]} | {r[6]}")

    print("\n--- TETOUAN STATS ---")
    cursor.execute('SELECT AVG(price_per_sqm), COUNT(*) FROM listings WHERE city=\'Tétouan\' AND "transaction"=\'Vente\'')
    avg, count = cursor.fetchone()
    print(f"Average: {avg}, Count: {count}")

    conn.close()

if __name__ == "__main__":
    check()
