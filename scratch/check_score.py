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
                    for g in data.get("game_list", []):
                        if str(g.get('server_steam_id')) == "90285607589477394":
                            print(f"Partner: {partner}")
                            print(f"Game Time: {g.get('game_time')}")
                            print(f"Radiant Score: {g.get('radiant_score')}")
                            print(f"Dire Score: {g.get('dire_score')}")
                            print(f"Radiant Lead: {g.get('radiant_lead')}")
                            print(f"Radiant: {g.get('team_name_radiant')}")
                            print(f"Dire: {g.get('team_name_dire')}")

if __name__ == "__main__":
    asyncio.run(main())
