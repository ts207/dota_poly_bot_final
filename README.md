# Dota Polymarket Bot MVP

Dry-run bot for comparing a fast Dota `radiant_lead`/score feed with Polymarket CLOB prices.

## What this version does

- Scans active Polymarket Dota markets through the Gamma API.
- Extracts `clobTokenIds` and outcomes automatically.
- Aligns Polymarket outcome tokens to actual Dota Radiant/Dire teams when a live Dota game is visible.
- Records Dota ticks, Polymarket book ticks, combined Radiant probability, signals, and dry orders.
- Uses raw `radiant_lead` swing, not fabricated total team net worth.
- Uses both Radiant YES and Dire YES books to build a combined Radiant-probability view.

## Install

```bash
pip install -r dota_poly_bot/requirements.txt
cp dota_poly_bot/.env.example .env
# edit .env, at minimum set STEAM_API_KEY
```

## Run dry collection

```bash
python dota_poly_bot/main.py
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

## Analyze signals

```bash
python dota_poly_bot/research/analyze_signals.py --db ./data/dota_poly_collection.sqlite
```

## Important

- This version is dry-run only. Real order execution is intentionally disabled.
- Automatic discovery can fail if Polymarket market names do not match Dota team names or if the Dota game is not visible through `GetTopLiveGame`.
- Verify token/team mapping from the startup logs before trusting collected data.

## Latest safety/research patches

This build is still dry-run/research only. New safeguards:

- Refuses unconfirmed Polymarket ↔ Dota alignment by default.
- Filters Gamma discovery toward binary match-winner markets and away from props/outrights/map-specific markets.
- Logs Dota server/team metadata into `dota_ticks`.
- Logs `target_token_id` into `signals`.
- Adds `paper_trades` schema for fill-adjusted research.
- Adds `research/analyze_signals.py --fill-window 2 --write-paper` to simulate whether dry orders would have filled.
- Uses persistent Polymarket REST session for snapshots and prints validation resets when local WS book differs from REST snapshot.
- Moves signal weights/risk thresholds into `.env`.

Recommended research flow:

```bash
cp .env.example .env
# edit STEAM_API_KEY and preferably set TARGET_RADIANT_TEAM/TARGET_DIRE_TEAM or TARGET_SERVER_STEAM_ID
python main.py
python research/analyze_signals.py --db ./data/dota_poly_collection.sqlite --fill-window 2 --write-paper
```

Do not use live execution until paper-filled conservative PnL is positive over many matches.
