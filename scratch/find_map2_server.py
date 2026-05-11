import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('STEAM_API_KEY')
url = 'https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/'
target_lobby = 29833233167766131
found = False

for p in range(10): # Try more partners
    r = requests.get(url, params={'key': key, 'partner': p})
    data = r.json()
    for g in data.get('game_list', []):
        if g.get('lobby_id') == target_lobby:
            print(f"MATCH FOUND! Partner: {p}")
            print(f"Server Steam ID: {g.get('server_steam_id')}")
            print(f"Game Time: {g.get('game_time')}")
            found = True
            break
    if found: break
else:
    print("Match not found in GetTopLiveGame for any partner (0-9).")
