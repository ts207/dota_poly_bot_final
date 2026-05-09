import sqlite3
conn=sqlite3.connect('/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
conn.execute('DROP TABLE IF EXISTS stratz_history')
conn.commit()
conn.close()
