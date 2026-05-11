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
                    print(f"Partner {partner}: {len(games)} games")
                    for g in games:
                        # Print any game that has a league_id or team names
                        lid = g.get('league_id')
                        r_name = g.get('team_name_radiant')
                        d_name = g.get('team_name_dire')
                        if lid or r_name or d_name:
                            print(f"  {r_name} vs {d_name} | League: {lid} | Server: {g.get('server_steam_id')}")

if __name__ == "__main__":
    asyncio.run(main())
