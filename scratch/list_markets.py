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
            if "Nigma" in m.question or "PlayTime" in m.question or "NGX" in m.question or "ptime" in m.question.lower():
                print(f"{m.question}")
                print(f"  Outcomes: {m.outcomes}")
                print(f"  Tokens:   {m.clob_token_ids}")
                print(f"  CID:      {m.condition_id}")
                print(f"  Slug:     {m.slug}")
                print("-" * 40)
    finally:
        await disc.close()

if __name__ == "__main__":
    asyncio.run(main())
