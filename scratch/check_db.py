import sqlite3
import os

db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
else:
    conn = sqlite3.connect(db_path)
    try:
        print('Dota ticks:', conn.execute('SELECT COUNT(*) FROM dota_ticks').fetchone()[0])
        print('Market ticks:', conn.execute('SELECT COUNT(*) FROM market_ticks').fetchone()[0])
        print('Signals:', conn.execute('SELECT COUNT(*) FROM signals').fetchone()[0])
        print('Rejections:', conn.execute('SELECT COUNT(*) FROM signal_rejections').fetchone()[0])
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
