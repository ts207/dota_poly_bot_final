import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('STEAM_API_KEY')
url = 'https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/'
r = requests.get(url, params={'key': key})
data = r.json()
for g in data.get('result', {}).get('games', []):
    if g.get('match_id') == 8806661972:
        import json
        print(json.dumps(g, indent=2))
