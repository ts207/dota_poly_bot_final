# Dota Polymarket Bot MVP

Dry-run bot for comparing a fast Dota `radiant_lead`/score feed with Polymarket CLOB prices.

## What this version does

- Scans active Polymarket Dota markets through the Gamma API.
- Extracts `clobTokenIds` and outcomes automatically.
- Aligns Polymarket outcome tokens to actual Dota Radiant/Dire teams when a live Dota game is visible.
- Records Dota ticks, Polymarket book ticks, combined Radiant probability, signals, dry orders, and rejection diagnostics.
- Uses raw `radiant_lead` swing, not fabricated total team net worth.
- Uses both Radiant YES and Dire YES books to build a combined Radiant-probability view.
- Adds run/session metadata to runtime tables so duplicate processes and map transitions are auditable.
- Adds a cleaning pipeline that creates normalized research tables without overwriting raw data.

## Install

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env, at minimum set STEAM_API_KEY
```

## Run dry collection

```bash
python main.py
```

With `AUTO_DISCOVER_POLYMARKET=true`, you do not need to manually fill `MARKET_ID`, `RADIANT_TOKEN_ID`, or `DIRE_TOKEN_ID` unless automatic discovery cannot confidently map a match.

For the safest matching, set either:

```env
TARGET_SERVER_STEAM_ID=...
```

or:

```env
TARGET_RADIANT_TEAM=Team A
TARGET_DIRE_TEAM=Team B
```

## Analyze and clean data

Recommended research flow:

```bash
python main.py
python research/analyze_signals.py --db ./data/dota_poly_collection.sqlite --fill-window 2 --write-paper
python research/clean_data.py --db ./data/dota_poly_collection.sqlite --write-csv
```

`research/clean_data.py` creates:

- `clean_dota_states`
- `clean_market_ticks`
- `market_match_segments`
- `clean_signal_rejections`
- `clean_signals`
- `clean_orders`
- `clean_research_dataset`
- `cleaning_rejections`

Raw tables remain unchanged.

## Latest safety/research patches

This build is still dry-run/research only. Current safeguards and data-quality fixes:

- Fixes the `strategy_loop` market-tick cache bug caused by using `self` inside a standalone function.
- Uses Dota game time, not wall-clock time, for the 20-second acceleration baseline.
- Makes the combined Radiant book timestamp conservative by using the older leg timestamp and storing leg timestamp skew.
- Clears stale Polymarket book state when subscribed assets change.
- Blocks missing/placeholder token IDs before signal/order logging.
- Splits shadow edge actions into `REJECT_EDGE_TOO_SMALL`, `REJECT_EDGE_TOO_LARGE`, and `FIRE`.
- Logs run context (`run_id`, `pid`, `git_sha`, `started_at_ts_ms`) into runtime tables.
- Stores execution price, edge, and mode on logged signals.
- Ignores runtime logs/CSVs/JSONL and generated target env files.

## Important

- This version is dry-run/research first. Real order execution should stay disabled until clean paper-filled results are positive across many matches.
- Automatic discovery can fail if Polymarket market names do not match Dota team names or if the Dota game is not visible through `GetTopLiveGame`.
- Verify token/team mapping from startup logs and `market_match_segments` before trusting collected data.
- A healthy collection should have no placeholder token IDs, no strategy-loop exceptions, and nonzero clean signals/orders before PnL analysis is meaningful.
