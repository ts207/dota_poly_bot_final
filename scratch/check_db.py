import sqlite3
db_path = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT datetime(ts_ms/1000, 'unixepoch'), side, signal_type, edge, fair_price, game_time FROM signals WHERE ts_ms > 1715342400000 ORDER BY ts_ms DESC")
rows = cur.fetchall()
print(f"Total signals today: {len(rows)}")
for r in rows:
    print(r)
conn.close()
