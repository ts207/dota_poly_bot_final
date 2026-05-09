import sqlite3
import pandas as pd
conn = sqlite3.connect('/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
df = pd.read_sql_query("SELECT mid, count(*) FROM market_ticks WHERE token_id='COMBINED_RADIANT' GROUP BY mid", conn)
print(df)
