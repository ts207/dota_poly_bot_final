import sqlite3
db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
conn = sqlite3.connect(db_path)
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print(f"Tables: {tables}")
conn.close()
