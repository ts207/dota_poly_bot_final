# Polymarket Dota 2 Series Supervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate following a Best-of-3 Dota series by dynamically switching Polymarket "Game X Winner" markets based on live Dota state.

**Architecture:** 
1. Enhance `DotaFastFeed` to track series wins and derive the current map number.
2. Update `PolymarketGammaDiscovery` to allow and parse "Game X" markets.
3. Refactor `main.py` into a supervisor loop that re-discovers and re-maps markets/tokens whenever the map changes or a market becomes available.

**Tech Stack:** Python, aiohttp, Polymarket Gamma API, Steam Web API.

---

### Task 1: Update Dota Feed for Series Tracking

**Files:**
- Modify: `feeds/dota_fast.py`

- [ ] **Step 1: Add series fields to `DotaFastFeed`**

```python
# feeds/dota_fast.py
# Inside DotaFastFeed.fetch_once, update the 'tick' dictionary creation:
            tick = {
                # ... existing fields ...
                "radiant_series_wins": int(target_game.get("radiant_series_wins", 0) or 0),
                "dire_series_wins": int(target_game.get("dire_series_wins", 0) or 0),
                "series_type": int(target_game.get("series_type", 0) or 0),
                # ... rest of tick ...
            }
```

- [ ] **Step 2: Add helper to calculate current map number**

```python
# feeds/dota_fast.py
# Add to DotaFastFeed class:
    @property
    def current_map_number(self) -> int:
        if not self.latest:
            return 1
        return int(self.latest.get("radiant_series_wins", 0)) + int(self.latest.get("dire_series_wins", 0)) + 1
```

- [ ] **Step 3: Commit**

```bash
git add feeds/dota_fast.py
git commit -m "feat(dota): add series wins and current_map_number tracking"
```

---

### Task 2: Update Polymarket Discovery for Game Parsing

**Files:**
- Modify: `discovery/polymarket_gamma.py`

- [ ] **Step 1: Relax `BAD_MARKET_TERMS`**

```python
# discovery/polymarket_gamma.py:53
BAD_MARKET_TERMS = {
    "tournament", "outright", "champion", "winner of", # Removed "map 1", "map 2"
    "first blood", "total kills", "handicap", "spread",
    "series score", "correct score", "most kills", "roshan", "duration", "over", "under"
}
```

- [ ] **Step 2: Add regex parsing for Game Number**

```python
# discovery/polymarket_gamma.py
import re

def parse_game_number(text: str) -> Optional[int]:
    """Extract game number from market text (e.g. 'Game 2 Winner' -> 2)."""
    match = re.search(r"(?:game|map)\s*(\d+)", text.lower())
    if match:
        return int(match.group(1))
    return None
```

- [ ] **Step 3: Update `choose_market` to prioritize specific game numbers**

```python
# discovery/polymarket_gamma.py
# Add target_game_number parameter to choose_market and use it in scoring
    @staticmethod
    def choose_market(
        markets: Sequence[DiscoveredMarket],
        radiant_team: str = "",
        dire_team: str = "",
        target_match: str = "",
        target_game_number: Optional[int] = None, # New parameter
        min_score: float = 0.35,
    ) -> Optional[Tuple[DiscoveredMarket, Dict[str, str]]]:
        # ... inside loop ...
        m_game = parse_game_number(m.question + " " + m.slug)
        if target_game_number is not None:
            if m_game == target_game_number:
                base += 1.0  # Strong boost for matching game number
            elif m_game is not None:
                continue # Skip markets for the wrong game number
        # ... rest of scoring ...
```

- [ ] **Step 4: Commit**

```bash
git add discovery/polymarket_gamma.py
git commit -m "feat(poly): enable game number parsing and filtering in discovery"
```

---

### Task 3: Refactor Main into Supervisor Loop

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Create a `SeriesSupervisor` class**

```python
# main.py
class SeriesSupervisor:
    def __init__(self, dota_feed, logger, db):
        self.dota_feed = dota_feed
        self.logger = logger
        self.db = db
        self.current_market_id = None
        self.current_map_num = 0

    async def sync_state(self):
        map_num = self.dota_feed.current_map_number
        if map_num != self.current_map_num or not self.current_market_id:
            self.logger.info(f"Map change detected or startup: {self.current_map_num} -> {map_num}")
            # Logic to re-discover market and re-map tokens
            # ...
```

- [ ] **Step 2: Implement dynamic side mapping**

```python
# main.py
# Inside sync_state logic:
tick = self.dota_feed.latest
actual_r = tick["radiant_team"]
actual_d = tick["dire_team"]
mapping = map_market_to_team_tokens(market, actual_r, actual_d)
# This ensures RADIANT_TOKEN_ID always points to whichever team is currently Radiant in Dota.
```

- [ ] **Step 3: Update `main()` to use supervisor**

```python
# main.py
# Replace auto_discover block with supervisor polling
while True:
    await supervisor.sync_state()
    # Run trading logic for one tick
    # ...
    await asyncio.sleep(poll_interval)
```

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: implement SeriesSupervisor for automatic map transitions"
```

---

### Task 4: Verification & Smoke Test

- [ ] **Step 1: Create a mock Steam API script**

```python
# scratch/mock_series_transition.py
# Script that mocks GetTopLiveGame responses transitioning from Game 1 to Game 2.
```

- [ ] **Step 2: Run supervisor against mock**

Run: `PYTHONPATH=. python3 main.py --mock-series` (if implemented) or manually verify with logs.

- [ ] **Step 3: Final Commit**

```bash
git commit -m "test: add mock for series transitions"
```
