import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    discovery = PolymarketGammaDiscovery()
    # Search with very broad terms
    markets = await discovery.search_dota_markets(query_terms=['power rangers', 'modus'], limit_per_query=200)
    for m in markets:
        if 'game 2' in m.question.lower() or 'game 2' in m.slug.lower():
            if 'modus' in m.slug.lower() or 'modus' in m.question.lower():
                print(f"Slug: {m.slug}")
                print(f"Title: {m.question}")
                print(f"Condition ID: {m.condition_id}")
                print(f"Outcomes: {m.outcomes}")
                print(f"Tokens: {m.clob_token_ids}")
    await discovery.close()

if __name__ == '__main__':
    asyncio.run(main())
