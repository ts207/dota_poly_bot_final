# Dota Poly Bot repo ZIP + data/log review

Reviewed uploads:

- `/mnt/data/dota_poly_bot_final-main(2).zip`
- `/mnt/data/dota_poly_collection.zip` / extracted SQLite DB

## Repo ZIP contents

The repo ZIP contains code, docs, runtime logs, runtime CSVs, model artifacts, scratch scripts, and Windows `:Zone.Identifier` files.

Important runtime artifacts included:

- `bot_final.log` — 306 KB
- `bot_grindback.log` — 69 KB
- `bot_background.log`
- `bot_startup.log`
- `data/shadow_signals.csv`
- `data/api_to_market_latency.csv`
- `data/last_discovered_target.env`
- `research/detailed_trade_report.csv`

## Code review findings

Unfixed high-priority issues found in uploaded ZIP:

1. `main.py` still uses `self._last_logged_m_ts` inside standalone `strategy_loop()`.
2. `core/features.py` still uses real-time `closest_ago(now_ms, 20)` for Dota acceleration while other Dota windows use game time.
3. `core/market.py` still uses `max(r_ts, d_ts)` for combined book timestamp, hiding stale leg risk.
4. `core/signals.py` still writes `data/shadow_signals.csv` with seconds timestamps and without `run_id`, `match_key`, `market_id`, `edge_floor`, or detailed edge reason.
5. `.gitignore` still does not ignore CSV, JSONL, logs, model artifacts, generated env files, or `:Zone.Identifier` files.
6. No `research/clean_data.py` was found.

## Runtime log review

### `bot_final.log`

- Lines: 3,989
- `Strategy loop error`: 0
- `Traceback`: 0
- `PM BOOK VALIDATION RESET`: 11
- `SIGNAL`: 0
- `DRY RUN ORDER`: 0
- Active status lines: 3,904
- Unique active states: 66

This run was active and stable, but it did not emit signals/orders.

### `bot_grindback.log`

- Lines: 901
- `Strategy loop error`: 0
- `Traceback`: 0
- `Risk blocked trade`: 2
- `SIGNAL`: 0
- `DRY RUN ORDER`: 0
- Active status lines: 856
- Unique active states: 25

This run also stayed active but generated no usable orders.

## Uploaded DB review

Table counts:

| Table | Rows |
|---|---:|
| `dota_ticks` | 10,158 |
| `market_ticks` | 188,259 |
| `signal_rejections` | 119 |
| `signals` | 0 |
| `orders` | 0 |
| `paper_trades` | 0 |
| `live_order_events` | 0 |
| `live_fill_snapshots` | 0 |

Main DB issues:

- `market_ticks` has 188,259 raw rows but only 42,148 unique exact book-state rows.
- `dota_ticks` has 10,158 rows but only 104 distinct game-state rows.
- `signal_rejections` has 119 rows; 115 have missing token IDs.
- No order/PnL analysis is possible because `signals`, `orders`, and `paper_trades` are empty.
- Multiple Polymarket markets overlap the second Dota match time range, so cleaning needs market-match segmentation.

Signal rejection distribution:

| Reason | Count |
|---|---:|
| `SPREAD_TOO_WIDE` | 79 |
| `EDGE_TOO_LARGE` | 22 |
| `INTRA_MINUTE_MOMENTUM_TOO_SMALL` | 6 |
| `RISK_STALE_COMBINED_BOOK` | 4 |
| `SNOWBALL_CLIMBING` | 4 |
| `EDGE_TOO_SMALL` | 2 |
| `EXPECTED_MOVE_TOO_SMALL` | 2 |

## Runtime CSV review

### `data/shadow_signals.csv`

- Rows: 32
- `FIRE`: 6
- `REJECT_EDGE`: 26
- Placeholder `token_id=0x`: 2
- Trigger distribution: `SLOW_BLEED` 17, `STRUCTURE_GAP` 6, `FIGHT_EVENT` 4, `OVERREACTION` 3, `STRUCTURE_EVENT` 2
- Mean edge: 0.2433
- Max edge: 0.9359

This file is dirty runtime output and should not be committed.

### `data/api_to_market_latency.csv`

- Rows: 36
- Mean latency: 8.71s
- Median latency: 7.44s
- Max latency: 28.89s
- <=2s latency: 27.8%
- <=5s latency: 41.7%

Latency is too variable to treat as a stable live edge without further segmentation.

### `research/detailed_trade_report.csv`

- Rows: 29
- Mean reported result: +0.55 percentage points
- 15 rows show `TAKE_PROFIT (+2.0%)`
- 6 rows show `STOP_LOSS (-2.0%)`

This appears to be separate historical/backtest output, not tied to the uploaded SQLite run, because the SQLite run has zero signals/orders.

## Final recommendation

Do not tune strategy thresholds yet. First fix collection and cleaning:

1. Fix `strategy_loop` `self` bug.
2. Fix Dota acceleration time base.
3. Make combined book timestamp conservative.
4. Clear old Polymarket book state on asset changes.
5. Add `run_id`, `pid`, `git_sha` to raw tables and logs.
6. Stop committing runtime files.
7. Add `research/clean_data.py` with `clean_dota_states`, `clean_market_ticks`, `market_match_segments`, `clean_signal_rejections`, and `clean_research_dataset`.
8. Run a new dry collection and require nonzero `signals` before any PnL analysis.
