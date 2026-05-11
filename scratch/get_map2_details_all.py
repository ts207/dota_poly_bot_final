import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    discovery = PolymarketGammaDiscovery()
    markets = await discovery.search_dota_markets(query_terms=['dota'], limit_per_query=500)
    for m in markets:
        if 'pr1-modus' in m.slug.lower():
            print(f"Slug: {m.slug}")
            print(f"Market ID: {m.condition_id}")
            print(f"Outcomes: {m.outcomes}")
            print(f"Tokens: {m.clob_token_ids}")
    await discovery.close()

if __name__ == '__main__':
    asyncio.run(main())
