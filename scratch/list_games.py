import asyncio
import os
from feeds.dota_fast import DotaFastFeed
from dotenv import load_dotenv

load_dotenv()

async def main():
    feed = DotaFastFeed(os.getenv('STEAM_API_KEY'))
    games = await feed.fetch_live_games()
    print(f"Found {len(games)} live games.")
    for g in games:
        print(f"  {g.get('team_name_radiant')} vs {g.get('team_name_dire')} | ID: {g.get('server_steam_id')}")

if __name__ == '__main__':
    asyncio.run(main())
