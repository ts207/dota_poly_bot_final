import requests
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

def fetch_and_populate(match_id):
    key = os.getenv('STEAM_API_KEY')
    db_path = os.getenv('DATABASE_PATH', '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite')
    
    url = f'https://api.steampowered.com/IDOTA2Match_570/GetMatchDetails/V001/?match_id={match_id}&key={key}'
    r = requests.get(url)
    if r.status_code == 200:
        res = r.json().get('result', {})
        print(f"Match Details for {match_id}:")
        print(f"  Radiant Win: {res.get('radiant_win')}")
        print(f"  Score: {res.get('radiant_score')} - {res.get('dire_score')}")
        print(f"  Duration: {res.get('duration')}s")
        
        # Populate a new table if it doesn't exist
        conn = sqlite3.connect(db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS match_summary (
                    match_id TEXT PRIMARY KEY,
                    radiant_win INTEGER,
                    radiant_score INTEGER,
                    dire_score INTEGER,
                    duration INTEGER,
                    raw_json TEXT
                )
            ''')
            import json
            conn.execute('''
                INSERT OR REPLACE INTO match_summary (match_id, radiant_win, radiant_score, dire_score, duration, raw_json)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                str(match_id),
                1 if res.get('radiant_win') else 0,
                res.get('radiant_score'),
                res.get('dire_score'),
                res.get('duration'),
                json.dumps(res)
            ))
            conn.commit()
            print(f"Successfully populated match_summary for {match_id}")
        finally:
            conn.close()
    else:
        print(f"Error fetching match details: {r.status_code}")

if __name__ == '__main__':
    fetch_and_populate('8806613303')
