import requests
import sqlite3
import time
import os
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)

OPENDOTA_BASE_URL = "https://api.opendota.com/api"

def get_api_key_param():
    api_key = os.getenv("OPENDOTA_API_KEY")
    return f"?api_key={api_key}" if api_key else ""

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS opendota_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            game_time INTEGER NOT NULL,
            nw_diff REAL,
            radiant_score INTEGER,
            dire_score INTEGER,
            score_diff INTEGER,
            radiant_win INTEGER,
            UNIQUE(match_id, game_time)
        )
    """)
    conn.commit()
    return conn

def fetch_public_matches():
    url = f"{OPENDOTA_BASE_URL}/parsedMatches{get_api_key_param()}"
    print(f"Fetching parsed matches from: {url}")
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"Failed to fetch matches: {response.text}")
        return []
    
    return response.json()

def fetch_match_details(match_id):
    api_param = get_api_key_param()
    sep = "&" if "?" in api_param else "?"
    url = f"{OPENDOTA_BASE_URL}/matches/{match_id}{api_param}"
    response = requests.get(url)
    
    if response.status_code == 429:
        print("Rate limit exceeded. Waiting 60 seconds...")
        time.sleep(60)
        return fetch_match_details(match_id)
        
    if response.status_code != 200:
        print(f"Failed to fetch match {match_id}: {response.text}")
        return None
        
    return response.json()

def process_match(match, conn):
    match_id = match.get('match_id')
    radiant_win = 1 if match.get('radiant_win') else 0
    radiant_gold_adv = match.get('radiant_gold_adv', [])
    
    if not radiant_gold_adv:
        print(f"Match {match_id} has no radiant_gold_adv data. Skipping.")
        return False

    # Compute kills per minute for score_diff
    kills_log = match.get('objectives', []) # Sometimes kills are in objectives or players array
    # To be precise, we need to iterate over players' kills.
    # OpenDota provides 'players'[i]['kills_log'] which is an array of {time: x, key: y}
    radiant_kills_timeline = []
    dire_kills_timeline = []
    
    for player in match.get('players', []):
        is_radiant = player.get('isRadiant')
        for kill in player.get('kills_log', []):
            time_sec = kill.get('time', 0)
            if is_radiant:
                radiant_kills_timeline.append(time_sec)
            else:
                dire_kills_timeline.append(time_sec)
                
    radiant_kills_timeline.sort()
    dire_kills_timeline.sort()
    
    cursor = conn.cursor()
    snapshots = []
    
    for minute, gold_adv in enumerate(radiant_gold_adv):
        game_time = minute * 60
        
        # Calculate score at this minute
        r_score = sum(1 for t in radiant_kills_timeline if t <= game_time)
        d_score = sum(1 for t in dire_kills_timeline if t <= game_time)
        score_diff = r_score - d_score
        
        snapshots.append((match_id, game_time, gold_adv, r_score, d_score, score_diff, radiant_win))
        
    try:
        cursor.executemany("""
            INSERT OR IGNORE INTO opendota_history 
            (match_id, game_time, nw_diff, radiant_score, dire_score, score_diff, radiant_win)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, snapshots)
        conn.commit()
        print(f"Inserted {len(snapshots)} snapshots for match {match_id}")
        return True
    except Exception as e:
        print(f"Error inserting match {match_id}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Gather historical Dota 2 data from OpenDota")
    parser.add_argument("--db", type=str, default="./data/dota_poly_collection.sqlite", help="Path to SQLite DB")
    parser.add_argument("--limit", type=int, default=50, help="Number of matches to process")
    args = parser.parse_args()
    
    db_path = args.db
    if not os.path.exists(os.path.dirname(db_path)):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
    conn = init_db(db_path)
    
    matches = fetch_public_matches()
    if not matches:
        print("No matches to process. Check API limits or network.")
        return
        
    print(f"Found {len(matches)} parsed matches.")
    
    processed = 0
    for m in matches:
        if processed >= args.limit:
            break
            
        match_id = m.get('match_id')
        print(f"Processing match {match_id}...")
        
        # Check if already processed
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM opendota_history WHERE match_id = ?", (match_id,))
        if cursor.fetchone()[0] > 0:
            print(f"Match {match_id} already in DB. Skipping.")
            continue
            
        details = fetch_match_details(match_id)
        if details:
            if process_match(details, conn):
                processed += 1
            # Rate limit respect (free tier is 60 calls per minute)
            time.sleep(1.5)
            
    conn.close()
    print(f"Finished processing {processed} matches.")

if __name__ == "__main__":
    main()
