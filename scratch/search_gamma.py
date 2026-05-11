import asyncio
import aiohttp
import json

async def search_gamma(query):
    base = "https://gamma-api.polymarket.com/public-search"
    params = {"q": query, "active": "true"}
    async with aiohttp.ClientSession() as session:
        async with session.get(base, params=params) as r:
            if r.status == 200:
                return await r.json()
            return None

async def main():
    for q in ["Grind", "Carstensz", "GB vs", "GB v", "Carstensz Esports"]:
        print(f"Searching for: {q}")
        res = await search_gamma(q)
        if res and res.get("events"):
            for event in res["events"]:
                print(f"Event: {event.get('title')}")
                for market in event.get("markets", []):
                    print(f"  Market: {market.get('question')}")
                    print(f"  Slug:   {market.get('slug')}")
                    print(f"  Outcomes: {market.get('outcomes')}")
                    print(f"  TokenIds: {market.get('clobTokenIds')}")
                    print(f"  ConditionID: {market.get('conditionId')}")
        else:
            print("  No events found.")
        print("-" * 20)

if __name__ == "__main__":
    asyncio.run(main())
