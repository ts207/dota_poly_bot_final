import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    discovery = PolymarketGammaDiscovery()
    markets = await discovery.search_dota_markets(query_terms=['pr2', 'modus', 'power rangers'])
    print(f"Found {len(markets)} matches for query.")
    for m in markets:
        print(f"Slug: {m.slug}, Title: {m.question}")
    await discovery.close()

if __name__ == '__main__':
    asyncio.run(main())
