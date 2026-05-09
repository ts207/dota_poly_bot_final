import sqlite3
import pandas as pd
conn = sqlite3.connect('/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
df = pd.read_sql_query('SELECT match_key, MIN(ts_ms), MAX(ts_ms), MAX(ts_ms)-MIN(ts_ms) as span FROM dota_ticks GROUP BY match_key;', conn)
print(df)
