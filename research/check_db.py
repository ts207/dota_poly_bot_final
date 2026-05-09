import sqlite3
import pandas as pd

conn = sqlite3.connect('/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
cursor = conn.cursor()
cursor.execute("SELECT count(DISTINCT match_key), count(*) FROM dota_ticks")
matches, ticks = cursor.fetchone()
print(f"Local DB contains {ticks} ticks across {matches} matches.")

cursor.execute("SELECT count(*) FROM market_ticks")
print(f"Market ticks: {cursor.fetchone()[0]}")

cursor.execute("SELECT count(*) FROM signals")
print(f"Signals: {cursor.fetchone()[0]}")

cursor.execute("SELECT count(*) FROM orders")
print(f"Orders: {cursor.fetchone()[0]}")
conn.close()
