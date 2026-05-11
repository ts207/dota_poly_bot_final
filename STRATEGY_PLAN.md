# Strategy Improvement Plan

## Current thesis

The bot is a Dota → Polymarket underreaction scalper. It watches live Dota telemetry, estimates whether Polymarket has lagged a recent event, places a short-lived maker bid on the target YES token, and measures whether real fills are profitable or toxic.

## First live-probe trigger set

Start with only the strongest latency/underreaction triggers:

```env
ENABLED_TRIGGERS=FIGHT_GAP,LEAD_FLIP_GAP,MARKET_CONFIRM
BLOCKED_TRIGGERS=SLOW_BLEED,OVERREACTION,FIGHT_EVENT,LEAD_FLIP_EVENT,STRUCTURE_EVENT,STRUCTURE_GAP
TRIGGER_MINUTE_WINDOWS=FIGHT_GAP:8-45,LEAD_FLIP_GAP:12-40,MARKET_CONFIRM:10-45,STRUCTURE_GAP:10-45,SLOW_BLEED:15-35
```

## Tiny live-probe config

```env
ENABLE_LIVE_TRADING=true
LIVE_PROBE_ONLY=true
AUTO_DISCOVER_POLYMARKET=false
ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=false
LIVE_MAX_ORDER_SIZE=1.00
LIVE_MAX_POSITION_PER_MATCH=3.00
LIVE_MAX_ORDERS_PER_MATCH=3
LIVE_CANCEL_AFTER_S=1.0
LIVE_FILL_SNAPSHOT_OFFSETS_S=0,5,15,30,60
SIGNAL_MAX_SPREAD=0.03
SIGNAL_MAX_MID_DISAGREEMENT=0.04
SIGNAL_MIN_EXPECTED_MOVE=0.035
SIGNAL_MIN_EDGE=0.04
RISK_MAX_SPREAD=0.03
RISK_MAX_COMBINED_DISAGREEMENT=0.04
RISK_MIN_EXIT_DEPTH=50
```

## Manual checklist before live probe

- Confirm Polymarket market question.
- Confirm `MARKET_ID`.
- Confirm `RADIANT_TOKEN_ID` belongs to actual Radiant team.
- Confirm `DIRE_TOKEN_ID` belongs to actual Dire team.
- Confirm `TARGET_SERVER_STEAM_ID` matches the same Dota match.
- Fund the wallet only with the small amount intended for probing.

## Review after every run

```bash
python research/analyze_live_probe.py --db ./data/dota_poly_collection.sqlite
```

Keep a trigger only if real fills show positive post-fill bid PnL at 15s and 30s, with acceptable toxic-fill rate.

Do not scale based on paper PnL alone.


## Trigger/edge hardening update

The latest strategy build adds these protections:

- Strong 10s shock triggers now require score change and `radiant_lead` change to agree in direction.
- `LEAD_FLIP_GAP` uses a 10-second lead flip, not a 60-second lead flip, so it is more latency-focused.
- `SIGNAL_MIN_EDGE` is a true global floor. Per-trigger floors from `TRIGGER_EDGE_FLOORS` can only make the edge requirement stricter.
- Throttled signal and execution rejections are logged to `signal_rejections` when `LOG_SIGNAL_REJECTIONS=true`.

Useful query:

```sql
SELECT reason, trigger, COUNT(*) AS n
FROM signal_rejections
GROUP BY reason, trigger
ORDER BY n DESC;
```

## Latest trigger safety patch

`FIGHT_GAP / NORMAL` now requires kill direction and `radiant_lead` movement to agree. If kills and lead movement disagree or lead movement is flat/unknown, the bot labels the state as `FIGHT_EVENT / CONFLICTED` and rejects it with `CONFLICTED_FIGHT_GAP`. `research/analyze_live_probe.py` now prints a signal rejection summary by default.


## Auto-ID discovery update

Auto-discovery now writes the selected target mapping to `DISCOVERED_TARGET_ENV_PATH` when `WRITE_DISCOVERED_TARGET_ENV=true`.

For safest live use:

1. Run dry discovery first.
2. Inspect `./data/last_discovered_target.env`.
3. Copy the IDs into `.env` or set `ALLOW_LIVE_AUTO_DISCOVERY=true` only after confirming the teams and market.

Live auto-discovery is refused unless Polymarket mapping is confirmed against a visible Dota game and a server ID is available.
