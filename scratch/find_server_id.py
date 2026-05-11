import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('STEAM_API_KEY')
url = 'https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/'
found = False
for p in [0, 1, 2, 3]:
    r = requests.get(url, params={'key': key, 'partner': p})
    data = r.json()
    for g in data.get('game_list', []):
        if g.get('lobby_id') == 29833233167766131:
            print(f"Match Found! Server Steam ID: {g.get('server_steam_id')} via partner {p}")
            found = True
            break
    if found: break
else:
    print("Match not found in GetTopLiveGame for any common partner.")
