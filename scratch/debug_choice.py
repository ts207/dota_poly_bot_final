import asyncio
import os
from discovery.polymarket_gamma import PolymarketGammaDiscovery

async def main():
    discovery = PolymarketGammaDiscovery()
    markets = await discovery.search_dota_markets(active=True, strict_match_winner_only=False)
    print(f"Found {len(markets)} markets.")
    
    target_match = "Power Rangers vs MODUS"
    target_radiant = "_PowerRangers"
    target_dire = "MODUS"
    target_map = 2
    
    chosen = discovery.choose_market(
        markets,
        radiant_team=target_radiant,
        dire_team=target_dire,
        target_match=target_match,
        target_game_number=target_map
    )
    
    if chosen:
        market, mapping = chosen
        print(f"Successfully chose market: {market.slug}")
    else:
        print("Failed to choose market. Debugging scores:")
        for m in markets:
            if 'modus' in m.slug.lower() and 'pr' in m.slug.lower():
                print(f"Market: {m.slug}")
                print(f"  Title: {m.question}")
                import re
                m_game = re.search(r"(?:game|map)\s*(\d+)", (m.question + " " + m.slug).lower())
                print(f"  Parsed Game: {m_game.group(1) if m_game else 'None'}")
                # Check teams
                from discovery.polymarket_gamma import _best_outcome_index
                r_idx = _best_outcome_index(m.outcomes, target_radiant)
                d_idx = _best_outcome_index(m.outcomes, target_dire)
                print(f"  Radiant Index: {r_idx}, Dire Index: {d_idx}")

    await discovery.close()

if __name__ == '__main__':
    asyncio.run(main())
