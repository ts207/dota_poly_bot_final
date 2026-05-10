import sqlite3
db_path = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT ts_ms, mid, spread FROM market_ticks ORDER BY ts_ms DESC LIMIT 20")
for r in cur.fetchall():
    print(r)
conn.close()
