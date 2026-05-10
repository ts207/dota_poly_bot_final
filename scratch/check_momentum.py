import sqlite3
db_path = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
# Find rows where radiant score increased from the previous row
cur.execute("""
    SELECT 
        datetime(t1.ts_ms/1000, 'unixepoch'), 
        t1.game_time, 
        t1.nw_diff, 
        t1.radiant_score - t2.radiant_score as kills
    FROM dota_ticks t1
    JOIN dota_ticks t2 ON t1.id = t2.id + 1
    WHERE t1.ts_ms > 1778400000000 
      AND t1.radiant_score > t2.radiant_score
    ORDER BY t1.ts_ms ASC
""")
rows = cur.fetchall()
print(f"Moments where Nigma got kills: {len(rows)}")
for r in rows:
    print(r)
conn.close()
