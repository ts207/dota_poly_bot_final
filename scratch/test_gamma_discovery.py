
import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    disc = PolymarketGammaDiscovery()
    print("Searching for Dota markets...")
    markets = await disc.search_dota_markets()
    print(f"Found {len(markets)} markets.")
    
    for m in markets:
        print(f"Market: {m.question}")
        print(f"  Slug: {m.slug}")
        print(f"  Outcomes: {m.outcomes}")
        print("-" * 20)
    
    radiant = "Power Rangers"
    dire = "Modus"
    print(f"\nAttempting to choose market for {radiant} vs {dire}...")
    chosen = disc.choose_market(markets, radiant_team=radiant, dire_team=dire)
    
    if chosen:
        market, mapping = chosen
        print(f"CHOSEN: {market.question}")
        print(f"Mapping: {mapping}")
    else:
        print("No market matched.")
    
    await disc.close()

if __name__ == "__main__":
    asyncio.run(main())
