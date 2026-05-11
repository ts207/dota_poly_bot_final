import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('STEAM_API_KEY')
url = 'https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/'

for p in [0, 1, 2, 3]:
    r = requests.get(url, params={'key': key, 'partner': p})
    data = r.json()
    for g in data.get('game_list', []):
        # Print anything that looks like a pro game or has teams
        if g.get('team_name_radiant') or g.get('team_name_dire'):
            print(f"Game: {g.get('team_name_radiant')} vs {g.get('team_name_dire')} | ID: {g.get('server_steam_id')}")
        elif g.get('league_id'):
             print(f"League Game? ID: {g.get('server_steam_id')} | League: {g.get('league_id')}")
