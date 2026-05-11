import asyncio
import json
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    disc = PolymarketGammaDiscovery()
    try:
        query_terms = ["power rangers", "modus"]
        print(f"Searching for markets with terms: {query_terms}")
        markets = await disc.search_dota_markets(query_terms=query_terms, strict_match_winner_only=False)
        
        print(f"\nDiscovered {len(markets)} markets:")
        for m in markets:
            print(f"- [{m.gamma_id}] {m.question} ({m.slug})")
            print(f"  Outcomes: {m.outcomes}")
            print(f"  Liquidity: {m.liquidity}, Volume24h: {m.volume24hr}")
            print(f"  CLOB Token IDs: {m.clob_token_ids}")
        
        # Look for Game 1/Map 1
        print("\n--- Testing choose_market for Map 1 ---")
        chosen1 = disc.choose_market(
            markets, 
            radiant_team="Power Rangers", 
            dire_team="Modus", 
            target_game_number=1
        )
        if chosen1:
            m, mapping = chosen1
            print(f"Chosen for Map 1: {m.question}")
            print(f"Mapping: {json.dumps(mapping, indent=2)}")
        else:
            print("No market chosen for Map 1.")

        # Look for Game 2/Map 2
        print("\n--- Testing choose_market for Map 2 ---")
        chosen2 = disc.choose_market(
            markets, 
            radiant_team="Power Rangers", 
            dire_team="Modus", 
            target_game_number=2
        )
        if chosen2:
            m, mapping = chosen2
            print(f"Chosen for Map 2: {m.question}")
            print(f"Mapping: {json.dumps(mapping, indent=2)}")
        else:
            print("No market chosen for Map 2.")

    finally:
        await disc.close()

if __name__ == "__main__":
    asyncio.run(main())
