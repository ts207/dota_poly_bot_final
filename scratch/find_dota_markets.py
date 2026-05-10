import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    disc = PolymarketGammaDiscovery()
    try:
        markets = await disc.search_dota_markets(active=True, strict_match_winner_only=False)
        print(f"Total candidate markets found: {len(markets)}")
        for m in markets:
            print(f"  {m.question} | {m.outcomes} | {m.url}")
    finally:
        await disc.close()

if __name__ == "__main__":
    asyncio.run(main())
