# Dota Poly Bot data review

Source: uploaded `dota_poly_collection.zip` containing `dota_poly_collection.sqlite`.

## Table counts

| table               |   rows |
|:--------------------|-------:|
| dota_ticks          |  10158 |
| live_fill_snapshots |      0 |
| live_order_events   |      0 |
| market_ticks        | 188259 |
| orders              |      0 |
| paper_trades        |      0 |
| signal_rejections   |    119 |
| signals             |      0 |

## Time ranges

| table               |   rows | min_utc             | max_utc             |
|:--------------------|-------:|:--------------------|:--------------------|
| dota_ticks          |  10158 | 2026-05-11 06:17:26 | 2026-05-11 08:11:59 |
| live_fill_snapshots |      0 |                     |                     |
| live_order_events   |      0 |                     |                     |
| market_ticks        | 188259 | 2026-05-11 06:17:27 | 2026-05-11 08:11:42 |
| orders              |      0 |                     |                     |
| paper_trades        |      0 |                     |                     |
| signal_rejections   |    119 | 2026-05-11 06:30:18 | 2026-05-11 08:11:29 |
| signals             |      0 |                     |                     |

## Duplicate summary

| dataset           |   raw_rows |   unique_meaningful_rows |   duplicate_rows |
|:------------------|-----------:|-------------------------:|-----------------:|
| dota_ticks        |      10158 |                    10136 |               22 |
| market_ticks      |     188259 |                    42148 |           146111 |
| signal_rejections |        119 |                       86 |               33 |

## Dota matches

|         match_key |   server_steam_id |   partner | radiant_team      | dire_team   |    n |     min_ts_ms |     max_ts_ms | min_utc             | max_utc             |   min_game |   max_game |   min_rs |   max_rs |   min_ds |   max_ds |   min_nw_diff |   max_nw_diff |   avg_delay |   max_delay |
|------------------:|------------------:|----------:|:------------------|:------------|-----:|--------------:|--------------:|:--------------------|:--------------------|-----------:|-----------:|---------:|---------:|---------:|---------:|--------------:|--------------:|------------:|------------:|
| 90285607589477394 | 90285607589477394 |         1 | Carstensz Esports | TEAM GRIND  | 6492 | 1778483661846 | 1778487119580 | 2026-05-11 07:14:21 | 2026-05-11 08:11:59 |        -90 |       3040 |        0 |       30 |        0 |       47 |        -20514 |          3849 |     36.2051 |     221.287 |
| 90285609545068564 | 90285609545068564 |         1 | Carstensz Esports | TEAM GRIND  | 3666 | 1778480246832 | 1778482565139 | 2026-05-11 06:17:26 | 2026-05-11 06:56:05 |        261 |       1801 |        0 |        7 |        0 |       36 |        -30208 |           432 |     54.6579 |     265.139 |

## Dota API delay stats

|         match_key |    n |   avg_delay |   min_delay |   max_delay |   delay_gt_10 |   delay_gt_30 |   delay_gt_60 |   delay_gt_120 |
|------------------:|-----:|------------:|------------:|------------:|--------------:|--------------:|--------------:|---------------:|
| 90285607589477394 | 6492 |     36.2051 |   -104.721  |     221.287 |          4434 |          3598 |          2248 |            347 |
| 90285609545068564 | 3666 |     54.6579 |    -74.6674 |     265.139 |          2672 |          2192 |          1469 |            519 |

## Rejection reasons

| reason                          |   n |   pct |
|:--------------------------------|----:|------:|
| SPREAD_TOO_WIDE                 |  79 |  66.4 |
| EDGE_TOO_LARGE                  |  22 |  18.5 |
| INTRA_MINUTE_MOMENTUM_TOO_SMALL |   6 |   5   |
| RISK_STALE_COMBINED_BOOK        |   4 |   3.4 |
| SNOWBALL_CLIMBING               |   4 |   3.4 |
| EDGE_TOO_SMALL                  |   2 |   1.7 |
| EXPECTED_MOVE_TOO_SMALL         |   2 |   1.7 |

## Rejection triggers

| trigger         |   n |
|:----------------|----:|
| (blank)         |  79 |
| SLOW_BLEED      |  21 |
| STRUCTURE_GAP   |  10 |
| STRUCTURE_EVENT |   4 |
| OVERREACTION    |   3 |
| FIGHT_EVENT     |   2 |

## Rejections by match and market

|         match_key | market_id         |   n |   missing_token |   min_game |   max_game |     min_ts_ms | min_utc             | max_utc             |
|------------------:|:------------------|----:|----------------:|-----------:|-----------:|--------------:|:--------------------|:--------------------|
| 90285609545068564 | 0x5d4403c3…8220ed |  34 |              34 |    8.93333 |    30.0167 | 1778481018837 | 2026-05-11 06:30:18 | 2026-05-11 06:52:08 |
| 90285607589477394 | 0x1a4c70d8…9df822 |   1 |               1 |    7       |     7      | 1778483694166 | 2026-05-11 07:14:54 | 2026-05-11 07:14:54 |
| 90285607589477394 | 0x6f1e0c0f…313b28 |  82 |              78 |   -1.5     |    50.6667 | 1778483803456 | 2026-05-11 07:16:43 | 2026-05-11 08:11:29 |
| 90285607589477394 | 0x5d4403c3…8220ed |   2 |               2 |   37.4333  |    37.4333 | 1778486327845 | 2026-05-11 07:58:47 | 2026-05-11 07:58:56 |

## Inferred market token mapping

| market_id         | token_id          |                n |   avg_abs_diff |
|:------------------|:------------------|-----------------:|---------------:|
| 0x1a4c70d8…9df822 | 3863118123…573478 | 193328           |    4.33681e-19 |
| 0x1a4c70d8…9df822 | 1021059579…072438 | 193328           |    2.994       |
| 0x5d4403c3…8220ed | 4011673209…956039 |      1.07756e+06 |    7.05527e-06 |
| 0x5d4403c3…8220ed | 9581179841…265880 |      1.07861e+06 |    2.02796     |
| 0x6f1e0c0f…313b28 | 9026823144…855144 |      5.99445e+06 |    2.23123e-07 |
| 0x6f1e0c0f…313b28 | 6398730071…386804 |      5.99889e+06 |    2.45636     |

## Top duplicated market ticks

| market_id         | token_id          |         ts_ms | utc                 |   best_bid |   best_ask |   mid |   spread |   cnt |
|:------------------|:------------------|--------------:|:--------------------|-----------:|-----------:|------:|---------:|------:|
| 0x6f1e0c0f…313b28 | 6398730071…386804 | 1778487013617 | 2026-05-11 08:10:13 |       0.92 |       0.99 | 0.955 |     0.07 |  1268 |
| 0x6f1e0c0f…313b28 | 9026823144…855144 | 1778487013617 | 2026-05-11 08:10:13 |       0.01 |       0.08 | 0.045 |     0.07 |  1268 |
| 0x6f1e0c0f…313b28 | COMBINED_RADIANT  | 1778487013617 | 2026-05-11 08:10:13 |       0.01 |       0.08 | 0.045 |     0.07 |  1268 |
| 0x6f1e0c0f…313b28 | 6398730071…386804 | 1778486686738 | 2026-05-11 08:04:46 |       0.9  |       0.99 | 0.945 |     0.09 |   839 |
| 0x6f1e0c0f…313b28 | 9026823144…855144 | 1778486686738 | 2026-05-11 08:04:46 |       0.01 |       0.1  | 0.055 |     0.09 |   839 |
| 0x6f1e0c0f…313b28 | COMBINED_RADIANT  | 1778486686738 | 2026-05-11 08:04:46 |       0.01 |       0.1  | 0.055 |     0.09 |   839 |
| 0x6f1e0c0f…313b28 | 6398730071…386804 | 1778486686744 | 2026-05-11 08:04:46 |       0.9  |       0.99 | 0.945 |     0.09 |   836 |
| 0x6f1e0c0f…313b28 | 9026823144…855144 | 1778486686744 | 2026-05-11 08:04:46 |       0.01 |       0.1  | 0.055 |     0.09 |   836 |
| 0x6f1e0c0f…313b28 | COMBINED_RADIANT  | 1778486686744 | 2026-05-11 08:04:46 |       0.01 |       0.1  | 0.055 |     0.09 |   836 |
| 0x6f1e0c0f…313b28 | 6398730071…386804 | 1778486643263 | 2026-05-11 08:04:03 |       0.9  |       0.99 | 0.945 |     0.09 |   746 |

## Key conclusions


- The run contains raw feed data and rejection diagnostics, but no logged valid signals, no orders, and no paper trades.
- `market_ticks` has heavy exact duplication: 188,259 raw rows collapse to 42,148 meaningful rows.
- `signal_rejections` has many missing token IDs: 115 of 119 rows. This blocks token-level rejection analysis unless token mapping is inferred.
- Most rejections are `SPREAD_TOO_WIDE` (79/119) and `EDGE_TOO_LARGE` (22/119).
- Dota feed rows are highly repeated by game state: 10,158 Dota ticks collapse to 104 unique match/game-state rows across the two matches.
- API delay is noisy and sometimes negative, so it needs normalization before use as a modeling feature.
