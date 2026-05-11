import asyncio
from feeds.dota_fast import DotaFastFeed
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    key = os.getenv("STEAM_API_KEY")
    if not key:
        print("STEAM_API_KEY not found")
        return
    
    feed = DotaFastFeed(key=key)
    games = await feed.fetch_live_games()
    print(f"Found {len(games)} live games")
    for g in games:
        r = g.get('team_name_radiant', '')
        d = g.get('team_name_dire', '')
        if r or d:
            print(f"R: {r} | D: {d} | Server: {g.get('server_steam_id')}")
        
        # Check for our teams
        if any(x in str(r).lower() or x in str(d).lower() for x in ["grind", "carst", "back"]):
            print("MATCH FOUND!")
            print(g)

if __name__ == "__main__":
    asyncio.run(main())
