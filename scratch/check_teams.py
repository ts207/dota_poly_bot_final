import sqlite3
import os

db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
conn = sqlite3.connect(db_path)
try:
    cursor = conn.execute("SELECT radiant_team_name, dire_team_name FROM live_league_games WHERE match_id = 8806661972")
    row = cursor.fetchone()
    print("Teams for 8806661972:", row)
finally:
    conn.close()
