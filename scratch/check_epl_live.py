import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    key = os.getenv("STEAM_API_KEY")
    url = "https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/"
    async with aiohttp.ClientSession() as session:
        for partner in [0, 1, 2, 3]:
            params = {"key": key, "partner": partner}
            async with session.get(url, params=params) as r:
                if r.status == 200:
                    data = await r.json()
                    games = data.get("game_list", [])
                    for g in games:
                        if g.get('league_id') == 18144:
                            print(f"EPL GAME FOUND!")
                            print(f"  {g.get('team_name_radiant')} vs {g.get('team_name_dire')}")
                            print(f"  Server: {g.get('server_steam_id')}")
                            print(f"  Game Time: {g.get('game_time')}")
                            print(f"  Radiant Lead: {g.get('radiant_lead')}")
                            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(main())
