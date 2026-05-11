import requests
import sqlite3
import os
import argparse
from dotenv import load_dotenv

load_dotenv(override=True)

STRATZ_API_URL = "https://api.stratz.com/graphql"

def get_stratz_token():
    token = os.getenv("STRATZ_API_KEY")
    if not token:
        raise ValueError("STRATZ_API_KEY not found in .env")
    return token

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stratz_history (
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

def fetch_stratz_matches(take=10, skip=0):
    query = """
    query GetProMatches($take: Int!, $skip: Int!) {
      leagues(request: { take: $take, skip: $skip }) {
        matches(request: { take: 10, skip: 0, isParsed: true }) {
          id
          didRadiantWin
          players {
            isRadiant
            stats {
              networthPerMinute
            }
            playbackData {
              killEvents {
                time
              }
            }
          }
        }
      }
    }
    """
    
    variables = {
        "take": take,
        "skip": skip
    }
    
    headers = {
        "Authorization": f"Bearer {get_stratz_token()}",
        "User-Agent": "STRATZ_API",
        "Content-Type": "application/json"
    }
    
    print(f"Fetching {take} leagues from Stratz (skip={skip})...")
    response = requests.post(STRATZ_API_URL, json={"query": query, "variables": variables}, headers=headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch matches: {response.text}")
        return []
        
    data = response.json()
    if 'errors' in data:
        print(f"GraphQL Errors: {data['errors']}")
        return []
        
    # Flatten matches from all returned leagues
    leagues = data.get('data', {}).get('leagues', [])
    all_matches = []
    for league in leagues:
        if 'matches' in league and league['matches']:
            all_matches.extend(league['matches'])
            
    return all_matches

def process_match(match, conn):
    match_id = match.get('id')
    radiant_win = 1 if match.get('didRadiantWin') else 0
    players = match.get('players', [])
    
    if not players:
        return False
        
    # Determine match duration in minutes based on networth arrays length
    max_minutes = 0
    for p in players:
        nw = p.get('stats', {}).get('networthPerMinute')
        if nw and len(nw) > max_minutes:
            max_minutes = len(nw)
            
    if max_minutes == 0:
        print(f"Match {match_id} has no networth data. Skipping.")
        return False
        
    radiant_kills_timeline = []
    dire_kills_timeline = []
    
    for p in players:
        is_radiant = p.get('isRadiant')
        pb_data = p.get('playbackData') or {}
        kills = pb_data.get('killEvents') or []
        for k in kills:
            if k and 'time' in k:
                if is_radiant:
                    radiant_kills_timeline.append(k['time'])
                else:
                    dire_kills_timeline.append(k['time'])
                    
    radiant_kills_timeline.sort()
    dire_kills_timeline.sort()
    
    snapshots = []
    for minute in range(max_minutes):
        game_time = minute * 60
        
        # Calculate Team Networths
        radiant_nw = 0
        dire_nw = 0
        for p in players:
            nw_array = p.get('stats', {}).get('networthPerMinute') or []
            val = nw_array[minute] if minute < len(nw_array) else (nw_array[-1] if nw_array else 0)
            if p.get('isRadiant'):
                radiant_nw += val
            else:
                dire_nw += val
                
        nw_diff = radiant_nw - dire_nw
        
        # Calculate Scores
        r_score = sum(1 for t in radiant_kills_timeline if t <= game_time)
        d_score = sum(1 for t in dire_kills_timeline if t <= game_time)
        score_diff = r_score - d_score
        
        snapshots.append((match_id, game_time, nw_diff, r_score, d_score, score_diff, radiant_win))
        
    cursor = conn.cursor()
    try:
        cursor.executemany("""
            INSERT OR IGNORE INTO stratz_history 
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
    parser = argparse.ArgumentParser(description="Gather historical Dota 2 data from Stratz")
    parser.add_argument("--db", type=str, default="./data/dota_poly_collection.sqlite", help="Path to SQLite DB")
    parser.add_argument("--limit", type=int, default=100, help="Number of matches to process")
    args = parser.parse_args()
    
    db_path = args.db
    if not os.path.exists(os.path.dirname(db_path)):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
    conn = init_db(db_path)
    
    processed = 0
    skip = 0
    
    while processed < args.limit:
        # We need to fetch leagues. We will just fetch 1 league at a time.
        # Each league has up to 10 matches, so we might fetch up to 10 matches per batch.
        matches = fetch_stratz_matches(take=1, skip=skip)
        
        if not matches:
            print("No more matches to process or API failed.")
            break
            
        print(f"Fetched {len(matches)} matches in this batch.")
        
        for m in matches:
            if processed >= args.limit:
                break
            match_id = m.get('id')
            
            # Check if already processed
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM stratz_history WHERE match_id = ?", (match_id,))
            if cursor.fetchone()[0] > 0:
                print(f"Match {match_id} already in DB. Skipping.")
                continue
                
            if process_match(m, conn):
                processed += 1
                
        skip += 1 # skip 1 league next time
            
    conn.close()
    print(f"Finished processing {processed} new matches.")

if __name__ == "__main__":
    main()
