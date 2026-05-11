import asyncio
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    disc = PolymarketGammaDiscovery()
    markets = await disc.search_dota_markets()
    for m in markets:
        if "lynx" in m.slug.lower() or "tm6" in m.slug.lower():
            print(f"Title: {m.question}, slug: {m.slug}, IDs: {m.clob_token_ids}")
    await disc.close()

asyncio.run(main())
