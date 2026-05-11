import sqlite3
db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
conn = sqlite3.connect(db_path)
cursor = conn.execute("SELECT match_key, radiant_team, dire_team FROM dota_ticks ORDER BY ts_ms DESC LIMIT 1")
print(cursor.fetchone())
conn.close()
