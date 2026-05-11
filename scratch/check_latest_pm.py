import sqlite3
db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
m_id = '0x7faa448ee821514bfcf4583fa3c12afef76ec65f006199b86ea6398939326b74'
conn = sqlite3.connect(db_path)
cursor = conn.execute("SELECT mid, spread, liquidity FROM polymarket_books WHERE market_id = ? ORDER BY ts_ms DESC LIMIT 1", (m_id,))
print(cursor.fetchone())
conn.close()
