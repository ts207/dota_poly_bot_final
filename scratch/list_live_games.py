
import asyncio
import os
from dotenv import load_dotenv
from feeds.dota_fast import DotaFastFeed

load_dotenv()

async def list_games():
    key = os.getenv("STEAM_API_KEY")
    if not key:
        print("Error: STEAM_API_KEY not found in .env")
        return

    feed = DotaFastFeed(key)
    session = await feed._get_session()
    
    all_games = []
    for partner in feed.partners:
        params = {"key": key, "partner": partner}
        async with session.get(feed.url, params=params) as r:
            if r.status != 200:
                continue
            data = await r.json()
            all_games.extend(data.get("game_list", []))
    
    await feed.close()

    print(f"{'Radiant':<25} | {'Dire':<25} | {'Server ID':<20} | {'Time':<5}")
    print("-" * 80)
    seen = set()
    for g in all_games:
        sid = str(g.get("server_steam_id"))
        if sid in seen:
            continue
        seen.add(sid)
        r = g.get("team_name_radiant", "Unknown")
        d = g.get("team_name_dire", "Unknown")
        t = g.get("game_time", 0) // 60
        print(f"{str(r):<25} | {str(d):<25} | {sid:<20} | {t:<5}m")

if __name__ == "__main__":
    asyncio.run(list_games())
