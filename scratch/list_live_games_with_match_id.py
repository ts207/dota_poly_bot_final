import asyncio
import os
from dotenv import load_dotenv
from feeds.dota_fast import DotaFastFeed

load_dotenv()

async def list_games():
    key = os.getenv("STEAM_API_KEY")
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

    print(f"{'Match ID':<15} | {'Radiant':<15} | {'Dire':<15} | {'Server ID':<20}")
    seen = set()
    for g in all_games:
        sid = str(g.get("server_steam_id"))
        if sid in seen:
            continue
        seen.add(sid)
        r = g.get("team_name_radiant", "")
        d = g.get("team_name_dire", "")
        m = g.get("match_id", "")
        if m == 8806795642 or m == "8806795642":
            print(f"FOUND MATCH: {m:<15} | {str(r):<15} | {str(d):<15} | {sid:<20}")
        # print(f"{m:<15} | {str(r):<15} | {str(d):<15} | {sid:<20}")

if __name__ == "__main__":
    asyncio.run(list_games())
