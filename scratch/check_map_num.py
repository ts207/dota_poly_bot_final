import asyncio
import os
from feeds.dota_fast import DotaFastFeed
from dotenv import load_dotenv

load_dotenv()

async def main():
    feed = DotaFastFeed(os.getenv('STEAM_API_KEY'))
    feed.target_radiant_team = '_PowerRangers'
    feed.target_dire_team = 'MODUS'
    tick = await feed.fetch_once()
    if tick:
        print(f"Map Number: {int(tick.get('radiant_series_wins', 0)) + int(tick.get('dire_series_wins', 0)) + 1}")
        print(f"Radiant Wins: {tick.get('radiant_series_wins')}")
        print(f"Dire Wins: {tick.get('dire_series_wins')}")
    else:
        print("No live game found for teams.")

if __name__ == '__main__':
    asyncio.run(main())
