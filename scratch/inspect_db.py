import sqlite3
import os

db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
conn = sqlite3.connect(db_path)
try:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables:", tables)
    for table in tables:
        print(f"\nSchema for {table}:")
        cursor = conn.execute(f"PRAGMA table_info({table})")
        for col in cursor.fetchall():
            print(f"  {col[1]} ({col[2]})")
finally:
    conn.close()
