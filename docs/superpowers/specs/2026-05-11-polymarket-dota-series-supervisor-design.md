# Design Spec: Polymarket Dota 2 Series Supervisor

## 1. Overview
Automate the discovery and execution of Dota 2 markets on Polymarket by following an entire Best-of-X series. The bot will automatically detect the current map being played, find the corresponding "Game X Winner" market on Polymarket, and align the Radiant/Dire sides correctly even if teams swap positions between games.

## 2. Goals
- **Automatic Map Discovery:** Detect the current game number (1, 2, or 3) from the Dota 2 Live API.
- **Dynamic Market Mapping:** Map "Game X Winner" markets on Polymarket to the live Dota game.
- **Side Alignment:** Correctly map "Team Name" to Radiant/Dire for each specific map to ensure the bot never trades the wrong side after a swap.
- **Hot-Swapping:** Support entering a market that becomes live after the Dota game has already started.

## 3. Architecture

### 3.1. Dota Series State (`DotaFastFeed`)
The feed will be updated to extract series-level metadata from `GetTopLiveGame`:
- `radiant_series_wins` (int)
- `dire_series_wins` (int)
- `series_type` (int)
- **Derived Logic:** `current_map_number = (radiant_series_wins + dire_series_wins) + 1`

### 3.2. Polymarket Game Discovery (`PolymarketGammaDiscovery`)
- **Relax Filters:** Remove "map 1", "map 2", etc., from `BAD_MARKET_TERMS` to allow map-specific markets.
- **Game Index Parsing:** Add a regex-based parser to identify the game number from market questions or slugs (e.g., `re.search(r"game\s*(\d+)", text)`).
- **Match Filtering:** Ensure the market belongs to the correct match by verifying team names and tournament keywords.

### 3.3. Supervisor Loop (`main.py`)
The main loop will be refactored to support continuous monitoring:
1. **Find Series:** Locate the live Dota game for the target teams.
2. **Sync Map:**
   - Detect `current_map_number`.
   - Find Polymarket markets for the match.
   - Select the market where `parsed_game_number == current_map_number`.
3. **Map Tokens:** 
   - Get `team_name_radiant` and `team_name_dire` from the specific live game tick.
   - Map those names to Polymarket outcomes to get `RADIANT_TOKEN_ID` and `DIRE_TOKEN_ID`.
4. **Execution:** Run the trading logic while `current_map_number` remains unchanged.
5. **Transition:** When the map ends, reset the execution context and wait for the next map's data to appear in the feed.

## 4. Error Handling & Edge Cases
- **Missing Market:** If Dota starts Game 2 but Polymarket hasn't listed it, the bot will enter a high-frequency polling state (every 15s) until the market appears.
- **Side Swaps:** The bot re-maps names to sides at the start of *every* map, preventing errors when teams swap Radiant/Dire.
- **Steam API Lag:** Use the `last_update_time` from Steam to ensure the bot doesn't trade on stale data during map transitions.

## 5. Testing Strategy
- **Mock Series:** Create a test script that simulates a BO3 transition (Wins: 0-0 -> 1-0 -> 1-1) and verify the bot picks the correct markets.
- **Side Swap Test:** Mock a game where Team A is Radiant in Map 1 and Dire in Map 2.
- **Gamma Search Test:** Verify the regex correctly parses "Game 1", "Map 1", and "Game 1 Winner".
