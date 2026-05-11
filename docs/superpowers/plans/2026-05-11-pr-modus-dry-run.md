# Power Rangers vs MODUS Dry Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a dry run of the Dota-Polymarket bot for the Power Rangers vs MODUS series to verify auto-discovery and alignment.

**Architecture:** 
1. Configure `.env` with match-specific metadata.
2. Launch `main.py` in dry-run mode.
3. Monitor logs to confirm the `SeriesSupervisor` correctly identifies the market and aligns tokens.
4. Verify data collection in the SQLite database.

**Tech Stack:** Python, asyncio, SQLite.

---

### Task 1: Environment Configuration

**Files:**
- Modify: `.env`

- [ ] **Step 1: Backup current `.env`**

Run: `cp .env .env.bak`

- [ ] **Step 2: Update `.env` with target metadata**

Modify `.env` to include:
```env
AUTO_DISCOVER_POLYMARKET=true
TARGET_SERVER_STEAM_ID=90285610368047130
TARGET_RADIANT_TEAM=_PowerRangers
TARGET_DIRE_TEAM=MODUS
TARGET_MATCH=Power Rangers vs MODUS
ENABLE_LIVE_TRADING=false
ALLOW_LIVE_AUTO_DISCOVERY=false
WRITE_DISCOVERED_TARGET_ENV=true
```

- [ ] **Step 3: Verify `.env` variables are loaded**

Run: `python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('TARGET_SERVER_STEAM_ID'))"`
Expected: `90285610368047130`

---

### Task 2: Launch Dry Run

**Files:**
- Launch: `main.py`

- [ ] **Step 1: Start the bot in the background or a multiplexer**

Run: `PYTHONPATH=. python3 main.py`

- [ ] **Step 2: Monitor startup logs for discovery**

Look for:
- `Supervisor: Searching for Map 1 market...`
- `Supervisor: Discovered market 0x... for Map 1`
- `Supervisor: Side swap/re-alignment! Radiant=_PowerRangers, Dire=MODUS`

- [ ] **Step 3: Confirm active strategy loop**

Look for:
- `Strategy: Active | Time=Xm | CombinedMid=...`

---

### Task 3: Verify Data Collection

**Files:**
- Check: `data/dota_poly_collection.sqlite`

- [ ] **Step 1: Verify dota_ticks are being logged**

Run: `sqlite3 data/dota_poly_collection.sqlite "SELECT COUNT(*) FROM dota_ticks;"`
Expected: A non-zero count that increases over time.

- [ ] **Step 2: Verify market_ticks are being logged**

Run: `sqlite3 data/dota_poly_collection.sqlite "SELECT COUNT(*) FROM market_ticks;"`
Expected: A non-zero count.

- [ ] **Step 3: Check for any virtual signals or rejections**

Run: `sqlite3 data/dota_poly_collection.sqlite "SELECT COUNT(*) FROM signals;"`
(Optional: If the game state triggers any logic)

---

### Task 4: Cleanup (Optional)

- [ ] **Step 1: Stop the bot**

(Press Ctrl+C or kill the process)

- [ ] **Step 2: Restore `.env` if needed**

Run: `cp .env.bak .env` (if you want to revert)
