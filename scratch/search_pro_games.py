
import asyncio
import os
from dotenv import load_dotenv
from feeds.dota_fast import DotaFastFeed

load_dotenv()

async def list_games():
    key = os.getenv("STEAM_API_KEY")
    if not key: return

    feed = DotaFastFeed(key)
    session = await feed._get_session()
    
    # Track the ones we found earlier
    targets = ["carstensz", "grind", "playtime", "nigma", "yellow", "rekonix"]
    print(f"Searching for targets: {targets}")
    print(f"{'Radiant':<25} | {'Dire':<25} | {'Server ID':<20} | {'Time':<5}")
    print("-" * 80)

    seen = set()
    for partner in feed.partners:
        params = {"key": key, "partner": partner}
        async with session.get(feed.url, params=params) as r:
            if r.status != 200: continue
            data = await r.json()
            for g in data.get("game_list", []):
                sid = g.get("server_steam_id")
                if sid in seen: continue
                seen.add(sid)
                
                r_team = str(g.get("team_name_radiant", "")).lower()
                d_team = str(g.get("team_name_dire", "")).lower()
                
                found = any(t in r_team or t in d_team for t in targets)
                
                # Also print anything that has a team name
                if found or g.get("team_name_radiant") or g.get("team_name_dire"):
                    t = g.get("game_time", 0) // 60
                    print(f"{str(g.get('team_name_radiant')):<25} | {str(g.get('team_name_dire')):<25} | {sid:<20} | {t:<5}m")

    await feed.close()

if __name__ == "__main__":
    asyncio.run(list_games())
