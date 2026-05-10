import sqlite3
db_path = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"
conn = sqlite3.connect(db_path)
cur = conn.cursor()
# Market ID for Nigma vs PlayTime Game 1: 0x4ed3d63814f01534e69ff37d5dbf7a16c73587ab60bae545501e4c026c0ba829
# Token ID for Nigma: 32433411131210293155029917800366715741868937315906688077045585600636813369875
# Moment: 19:18:50 UTC (1778440730000 approx)
cur.execute("""
    SELECT datetime(ts_ms/1000, 'unixepoch'), best_bid, best_ask, mid 
    FROM market_ticks 
    WHERE token_id = '32433411131210293155029917800366715741868937315906688077045585600636813369875'
      AND ts_ms BETWEEN 1778440600000 AND 1778440800000
    ORDER BY ts_ms ASC
""")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
