
import asyncio
import os
import time
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, AsyncMock

# Mocking dependencies before imports if necessary, or just mock the instances
from core.logger import BotLogger
from storage.db import BotDatabase
from main import SeriesSupervisor
from discovery.polymarket_gamma import DiscoveredMarket

class MockDotaFeed:
    def __init__(self):
        self.latest = {
            "radiant_team": "Team Liquid",
            "dire_team": "Gaimin Gladiators",
            "radiant_series_wins": 0,
            "dire_series_wins": 0,
            "game_time": 100.0,
            "ts_ms": int(time.time() * 1000)
        }
        self.target_server_steam_id = None
        self.poll_interval = 1.0

    @property
    def current_map_number(self) -> int:
        return int(self.latest.get("radiant_series_wins", 0)) + int(self.latest.get("dire_series_wins", 0)) + 1

    async def fetch_once(self):
        return self.latest
    
    async def find_live_game_by_team_pair(self, a, b):
        return {"server_steam_id": "123456789"}
    
    def set_target_server(self, sid):
        self.target_server_steam_id = sid

async def run_test():
    logger = BotLogger()
    # Use temporary file DB
    db_path = "scratch/test_supervisor.db"
    if os.path.exists(db_path): os.remove(db_path)
    db = BotDatabase(db_path)
    
    feed = MockDotaFeed()
    
    # Setup supervisor
    os.environ["TARGET_RADIANT_TEAM"] = "Team Liquid"
    os.environ["TARGET_DIRE_TEAM"] = "Gaimin Gladiators"
    os.environ["AUTO_DISCOVER_POLYMARKET"] = "true"
    
    supervisor = SeriesSupervisor(feed, logger, db)
    
    # Mock the discovery object inside supervisor
    mock_discovery = MagicMock()
    supervisor.disc = mock_discovery
    
    # Prepare mock markets
    market_g1 = DiscoveredMarket(
        gamma_id="g1",
        condition_id="c1",
        question="Will Team Liquid win Game 1 against Gaimin Gladiators?",
        slug="liquid-vs-gaimin-game-1",
        outcomes=["Team Liquid", "Gaimin Gladiators"],
        clob_token_ids=["t1_r", "t1_d"]
    )
    
    market_g2 = DiscoveredMarket(
        gamma_id="g2",
        condition_id="c2",
        question="Will Team Liquid win Game 2 against Gaimin Gladiators?",
        slug="liquid-vs-gaimin-game-2",
        outcomes=["Team Liquid", "Gaimin Gladiators"],
        clob_token_ids=["t2_r", "t2_d"]
    )
    
    # Mock search_dota_markets
    mock_discovery.search_dota_markets = AsyncMock(return_value=[market_g1, market_g2])
    
    # Mock choose_market to simulate finding the right game
    def side_effect_choose(markets, r, d, match, target_game_number=None):
        if target_game_number == 1:
            return market_g1, {
                "MARKET_ID": "c1",
                "RADIANT_TOKEN_ID": "t1_r",
                "DIRE_TOKEN_ID": "t1_d"
            }
        if target_game_number == 2:
            return market_g2, {
                "MARKET_ID": "c2",
                "RADIANT_TOKEN_ID": "t2_r",
                "DIRE_TOKEN_ID": "t2_d"
            }
        return None
    
    mock_discovery.choose_market.side_effect = side_effect_choose

    print("\n--- Test 1: Game 1 Discovery ---")
    feed.latest["radiant_series_wins"] = 0
    feed.latest["dire_series_wins"] = 0
    
    active = await supervisor.sync_state()
    print(f"Active: {active}")
    print(f"Market ID: {supervisor.market_id}")
    print(f"Radiant Token: {supervisor.radiant_token_id}")
    print(f"Dire Token: {supervisor.dire_token_id}")
    
    assert supervisor.market_id == "c1"
    assert supervisor.radiant_token_id == "t1_r"

    print("\n--- Test 2: Stay on Game 1 ---")
    # Same state
    active = await supervisor.sync_state()
    print(f"Market ID: {supervisor.market_id} (Expected c1)")
    assert supervisor.market_id == "c1"

    print("\n--- Test 3: Transition to Game 2 ---")
    print("Simulating Game 1 ends, Liquid wins. Series score: 1-0")
    feed.latest["radiant_series_wins"] = 1
    feed.latest["dire_series_wins"] = 0
    
    print(f"Current Map Number from feed: {feed.current_map_number}")
    
    active = await supervisor.sync_state()
    print(f"Active: {active}")
    print(f"Market ID: {supervisor.market_id} (Expected c2)")
    print(f"Radiant Token: {supervisor.radiant_token_id}")
    print(f"Dire Token: {supervisor.dire_token_id}")
    
    assert supervisor.market_id == "c2"
    assert supervisor.radiant_token_id == "t2_r"
    
    print("\n--- Test 4: Side Swap Alignment in Game 2 ---")
    print("Simulating Liquid is now Dire in Game 2")
    feed.latest["radiant_team"] = "Gaimin Gladiators"
    feed.latest["dire_team"] = "Team Liquid"
    
    # We need to mock map_market_to_team_tokens which is imported in main.py
    # or just let it run if it's imported correctly.
    # In main.py: from discovery.polymarket_gamma import ..., map_market_to_team_tokens, ...
    
    active = await supervisor.sync_state()
    print(f"Radiant Team in Feed: {feed.latest['radiant_team']}")
    print(f"Radiant Token: {supervisor.radiant_token_id} (Expected t2_d because Liquid is Dire)")
    print(f"Dire Token: {supervisor.dire_token_id} (Expected t2_r because Gaimin is Radiant)")
    
    # Wait, if Liquid is Dire, then dire_token should be Liquid's token for Game 2?
    # Actually market_g2 outcomes are ["Team Liquid", "Gaimin Gladiators"]
    # t2_r is for "Team Liquid", t2_d is for "Gaimin Gladiators"
    # If Liquid is Dire, dire_token_id should be t2_r.
    # If Gaimin is Radiant, radiant_token_id should be t2_d.
    
    assert supervisor.radiant_token_id == "t2_d"
    assert supervisor.dire_token_id == "t2_r"

    print("\nSUCCESS: All series transition tests passed!")

if __name__ == "__main__":
    asyncio.run(run_test())
