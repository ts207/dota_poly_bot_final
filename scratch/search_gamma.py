import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    disc = PolymarketGammaDiscovery()
    try:
        # Search with team names explicitly
        markets = await disc.search_dota_markets(query_terms=['Power Rangers', 'Modus', 'dota'])
        print(f'Found {len(markets)} markets')
        for m in markets:
            print(f'Slug: {m.slug}')
            print(f'Question: {m.question}')
            print(f'Outcomes: {m.outcomes}')
            print('-' * 40)
    finally:
        await disc.close()

if __name__ == '__main__':
    asyncio.run(main())
