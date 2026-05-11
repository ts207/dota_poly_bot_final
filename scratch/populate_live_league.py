import asyncio
import aiohttp
import os
import sqlite3
import time
from dotenv import load_dotenv

load_dotenv()

async def populate_live_league_games():
    key = os.getenv('STEAM_API_KEY')
    db_path = '/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite'
    url = 'https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/'
    
    async with aiohttp.ClientSession() as session:
        params = {'key': key}
        async with session.get(url, params=params) as r:
            if r.status != 200:
                print(f"Error fetching from Steam API: {r.status}")
                return
            
            data = await r.json()
            games = data.get('result', {}).get('games', [])
            
            conn = sqlite3.connect(db_path)
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS live_league_games (
                        match_id INTEGER PRIMARY KEY,
                        lobby_id INTEGER,
                        league_id INTEGER,
                        radiant_team_name TEXT,
                        dire_team_name TEXT,
                        game_time INTEGER,
                        radiant_score INTEGER,
                        dire_score INTEGER,
                        radiant_lead INTEGER,
                        spectators INTEGER,
                        last_update_ts INTEGER
                    )
                ''')
                
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS live_league_players (
                        match_id INTEGER,
                        account_id INTEGER,
                        name TEXT,
                        hero_id INTEGER,
                        team INTEGER,
                        net_worth INTEGER,
                        gold INTEGER,
                        level INTEGER,
                        kills INTEGER,
                        deaths INTEGER,
                        assists INTEGER,
                        PRIMARY KEY (match_id, account_id)
                    )
                ''')
                
                now = int(time.time())
                for g in games:
                    match_id = g.get('match_id')
                    if not match_id: continue
                    
                    scoreboard = g.get('scoreboard', {})
                    r_team_data = g.get('radiant_team') or {}
                    d_team_data = g.get('dire_team') or {}
                    
                    conn.execute('''
                        INSERT OR REPLACE INTO live_league_games (
                            match_id, lobby_id, league_id, radiant_team_name, dire_team_name,
                            game_time, radiant_score, dire_score, radiant_lead, spectators, last_update_ts
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        match_id, g.get('lobby_id'), g.get('league_id'),
                        r_team_data.get('team_name', 'Unknown'), d_team_data.get('team_name', 'Unknown'),
                        scoreboard.get('duration'),
                        scoreboard.get('radiant', {}).get('score'),
                        scoreboard.get('dire', {}).get('score'),
                        scoreboard.get('radiant_lead'),
                        g.get('spectators'), now
                    ))
                    
                    # Players
                    for team_key in ['radiant', 'dire']:
                        team_id = 0 if team_key == 'radiant' else 1
                        for p in scoreboard.get(team_key, {}).get('players', []):
                            conn.execute('''
                                INSERT OR REPLACE INTO live_league_players (
                                    match_id, account_id, name, hero_id, team,
                                    net_worth, gold, level, kills, deaths, assists
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                match_id, p.get('account_id'), p.get('name'), p.get('hero_id'), team_id,
                                p.get('net_worth'), p.get('gold'), p.get('level'),
                                p.get('kills'), p.get('deaths'), p.get('assists')
                            ))
                
                conn.commit()
                print(f"Successfully populated {len(games)} live league games and their player details.")
            finally:
                conn.close()

if __name__ == '__main__':
    asyncio.run(populate_live_league_games())
