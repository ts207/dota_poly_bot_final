import sqlite3

db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
try:
    print("--- Clean Signals ---")
    for row in conn.execute('SELECT * FROM clean_signals'):
        print(list(row))
    
    print("\n--- Clean Orders ---")
    for row in conn.execute('SELECT * FROM clean_orders'):
        print(list(row))
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
