
import asyncio
import os
import json
import aiohttp
from dotenv import load_dotenv

load_dotenv()

async def dump_one_game():
    key = os.getenv("STEAM_API_KEY")
    url = "https://api.steampowered.com/IDOTA2Match_570/GetTopLiveGame/v1/"
    async with aiohttp.ClientSession() as session:
        params = {"key": key, "partner": 0}
        async with session.get(url, params=params) as r:
            if r.status == 200:
                data = await r.json()
                games = data.get("game_list", [])
                if games:
                    print(json.dumps(games[0], indent=2))
                else:
                    print("No games found for partner 0")

if __name__ == "__main__":
    asyncio.run(dump_one_game())
