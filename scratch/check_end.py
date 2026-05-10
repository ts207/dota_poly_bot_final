import sqlite3
db_path = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT datetime(ts_ms/1000, 'unixepoch'), game_time, nw_diff, radiant_score, dire_score FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1")
row = cur.fetchall()
print(row)
conn.close()
