import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    key = os.getenv('STEAM_API_KEY')
    url = 'https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/'
    async with aiohttp.ClientSession() as session:
        params = {'key': key}
        async with session.get(url, params=params) as r:
            if r.status == 200:
                data = await r.json()
                games = data.get('result', {}).get('games', [])
                found = False
                for g in games:
                    r_team = g.get('radiant_team', {}).get('team_name', 'Unknown')
                    d_team = g.get('dire_team', {}).get('team_name', 'Unknown')
                    if 'power' in r_team.lower() or 'modus' in r_team.lower() or 'power' in d_team.lower() or 'modus' in d_team.lower():
                        found = True
                        print(f"MATCH FOUND: {r_team} vs {d_team}")
                        print(f"  Match ID: {g.get('match_id')}")
                        print(f"  Lobby ID: {g.get('lobby_id')}")
                        print(f"  Spectators: {g.get('spectators')}")
                        print(f"  League ID: {g.get('league_id')}")
                        print(f"  Stream ID: {g.get('stream_id')}")
                        print('-' * 20)
                if not found:
                    print("No Power Rangers vs MODUS matches found in GetLiveLeagueGames.")
            else:
                print(f"Error: {r.status}")

if __name__ == '__main__':
    asyncio.run(main())
