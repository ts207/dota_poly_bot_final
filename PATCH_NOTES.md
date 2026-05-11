# Patch notes — data normalization and cleaning pass

This ZIP applies the data/logging fixes requested for the Dota/Polymarket bot.

## Runtime fixes

- Fixed `strategy_loop` market-tick cache bug by replacing `self._last_logged_m_ts` with a local `last_logged_m_ts` dictionary.
- Added hard token guards so placeholder token IDs such as `0x` do not flow into signals/orders.
- Added `run_id`, `pid`, `git_sha`, and `started_at_ts_ms` runtime context.
- Added startup config logging for safety-critical environment values.
- Added token inference for signal rejections when side is known.
- Stored `execution_price`, `execution_edge`, and `execution_mode` on logged signals.

## Market/data fixes

- `FeatureEngine` now uses Dota game time for the 20-second acceleration baseline.
- `combine_binary_books()` now uses the older of the Radiant/Dire book timestamps, and exposes `radiant_ts_ms`, `dire_ts_ms`, and `leg_ts_skew_ms`.
- `PolyMarketBook.update_assets()` now clears stale books/raw book state when token subscriptions change.
- Shadow signals now log `ts_ms`, `run_id`, `match_key`, `market_id`, `edge_floor`, `max_edge`, and specific edge actions.

## Cleaning pipeline

Added:

```bash
python research/clean_data.py --db ./data/dota_poly_collection.sqlite --write-csv
```

This creates raw-preserving clean tables:

- `clean_dota_states`
- `clean_market_ticks`
- `market_match_segments`
- `clean_signal_rejections`
- `clean_signals`
- `clean_orders`
- `clean_research_dataset`
- `cleaning_rejections`

## Repo hygiene

- Updated `.gitignore` to exclude runtime logs, generated CSV/JSONL files, generated target env files, SQLite sidecars, and Zone.Identifier files.
- Removed committed runtime logs and dirty runtime CSV/env outputs from this deliverable.
- Fixed README commands to use root-level `requirements.txt` and `main.py`.
- Fixed a syntax error in `research/dashboard.py`.

## Validation performed

- `python -m compileall -q .`
- `python test_import.py`
- Ran `research/clean_data.py` against a copy of the uploaded `dota_poly_collection.sqlite`.

Uploaded DB cleaning report from that run:

```text
clean_dota_states: 104
clean_market_ticks: 42148
clean_orders: 0
clean_research_dataset: 0
clean_signal_rejections: 83
clean_signals: 0
duplicate_dota_states_removed: 10054
duplicate_market_ticks_removed: 146111
duplicate_rejections_removed: 36
invalid_market_token_rows: 0
invalid_order_token_rows: 0
invalid_signal_token_rows: 0
market_match_segments: 4
orders_without_signal: 0
raw_dota_ticks: 10158
raw_market_ticks: 188259
raw_orders: 0
raw_signal_rejections: 119
raw_signals: 0
rejections_missing_token: 81
```
