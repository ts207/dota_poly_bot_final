# Tiny Live-Probe Mode

This patch adds an opt-in live-probe path for **tiny real orders** so you can measure actual Polymarket order acknowledgements, cancels, partial fills, and adverse selection.

It is not full production trading. Dry run remains the default.

## What changed

- Added `execution/polymarket_client.py` as a small `py-clob-client` adapter.
- Replaced the real-execution placeholder in `execution/order_manager.py` with guarded live-probe order placement and cancellation.
- Updated `main.py` so live mode only starts when all safety flags are explicit.
- Added `BLOCKED_TRIGGERS = set()` in `core/signals.py` to fix the undefined-symbol crash.
- Added live-probe settings to `.env.example`.

## Required safe configuration

For live probe mode, use manual mapping only:

```env
ENABLE_LIVE_TRADING=true
LIVE_PROBE_ONLY=true

AUTO_DISCOVER_POLYMARKET=false
ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=false

MARKET_ID=...
RADIANT_TOKEN_ID=...
DIRE_TOKEN_ID=...
TARGET_SERVER_STEAM_ID=...

LIVE_MAX_ORDER_SIZE=1.00
LIVE_MAX_POSITION_PER_MATCH=5.00
LIVE_MAX_ORDERS_PER_MATCH=5
LIVE_CANCEL_AFTER_S=1.5

POLY_HOST=https://clob.polymarket.com
POLY_CHAIN_ID=137
POLY_PRIVATE_KEY=...
POLY_FUNDER=...
```

The bot refuses live probe mode when:

- `LIVE_PROBE_ONLY=false`
- `AUTO_DISCOVER_POLYMARKET=true`
- `ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=true`
- `TARGET_SERVER_STEAM_ID` is missing
- `POLY_PRIVATE_KEY` is missing
- order size exceeds `LIVE_MAX_ORDER_SIZE`
- match exposure exceeds `LIVE_MAX_POSITION_PER_MATCH`
- order count exceeds `LIVE_MAX_ORDERS_PER_MATCH`

## Recommended first run

1. Run dry first with the exact same manual token configuration:

```env
ENABLE_LIVE_TRADING=false
AUTO_DISCOVER_POLYMARKET=false
```

```bash
python main.py
```

2. Confirm startup logs show the correct match and token mapping.

3. Enable live probe with $1 max order size:

```env
ENABLE_LIVE_TRADING=true
LIVE_MAX_ORDER_SIZE=1.00
LIVE_MAX_POSITION_PER_MATCH=5.00
LIVE_MAX_ORDERS_PER_MATCH=3
LIVE_CANCEL_AFTER_S=1.0
```

4. Run one match only:

```bash
python main.py
```

5. Inspect the `orders` table:

```sql
SELECT ts_ms, token_id, price, size, status, ack_ms, fill_price, filled_size
FROM orders
ORDER BY id DESC
LIMIT 50;
```

## Notes

- The Polymarket CLOB Python client API can vary by version. If live submission fails with a method/signature error, the only file you should need to adapt is `execution/polymarket_client.py`.
- Do not leave live probe unattended.
- Start with $1 orders. The purpose is measurement, not profit.

## Live fill-quality logging added

The upgraded live probe writes two extra tables:

- `live_order_events`: submit acknowledgements, pre-cancel status, cancel acknowledgement, post-cancel status, detected fills, failures, exchange order id, raw exchange JSON, fill size/price, remaining size, and ack timings.
- `live_fill_snapshots`: target-token order-book snapshots after a detected fill at offsets from `LIVE_FILL_SNAPSHOT_OFFSETS_S`.

Useful inspection queries:

```sql
SELECT
  ts_ms, event_type, exchange_order_id, token_id,
  intended_price, intended_size, filled_size, avg_fill_price,
  remaining_size, ack_ms
FROM live_order_events
ORDER BY id DESC
LIMIT 100;
```

```sql
SELECT
  exchange_order_id, seconds_after_fill,
  best_bid, best_ask, mid, spread, bid_depth, ask_depth
FROM live_fill_snapshots
ORDER BY id DESC
LIMIT 100;
```

To compare live orders against ordinary order records:

```sql
SELECT
  ts_ms, status, exchange_order_id, token_id, price, size,
  ack_ms, cancel_ack_ms, fill_price, filled_size
FROM orders
WHERE status LIKE 'LIVE_%'
ORDER BY id DESC;
```

## Logging fixes in this build

- The `0s` fill snapshot is written synchronously when a fill is detected, so it is not lost if the process stops shortly after the fill.
- `CANCEL_ACK` stores only cancel acknowledgment metadata and the raw cancel response; it does not infer fill size, average fill price, or remaining size from a cancel response.
- Generic `price` fields are no longer treated as average fill price. Only explicit average/fill-price fields are used for fill-price logging.

## Strategy controls added

Use these to test one trigger family at a time without editing code:

```env
ENABLED_TRIGGERS=FIGHT_GAP,LEAD_FLIP_GAP,MARKET_CONFIRM
BLOCKED_TRIGGERS=SLOW_BLEED,OVERREACTION,FIGHT_EVENT,LEAD_FLIP_EVENT,STRUCTURE_EVENT,STRUCTURE_GAP
TRIGGER_MINUTE_WINDOWS=FIGHT_GAP:8-45,LEAD_FLIP_GAP:12-40,MARKET_CONFIRM:10-45,STRUCTURE_GAP:10-45,SLOW_BLEED:15-35
```

Analyze trigger quality after a run:

```bash
python research/analyze_live_probe.py --db ./data/dota_poly_collection.sqlite
```

The key metrics are filled post-fill bid PnL at 15s/30s and toxic fill rate, not raw signal count.


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


## Auto-discovering MARKET_ID / token IDs / Dota server ID

The bot can now populate the target IDs automatically during discovery.

Dry discovery flow:

```env
ENABLE_LIVE_TRADING=false
AUTO_DISCOVER_POLYMARKET=true
ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=false
WRITE_DISCOVERED_TARGET_ENV=true
DISCOVERED_TARGET_ENV_PATH=./data/last_discovered_target.env

# Strongly recommended so discovery picks the intended match:
TARGET_RADIANT_TEAM=...
TARGET_DIRE_TEAM=...
# or:
TARGET_MATCH=...
```

Run:

```bash
python main.py
```

When discovery succeeds, the bot writes:

```text
./data/last_discovered_target.env
```

with:

```env
MARKET_ID=...
RADIANT_TOKEN_ID=...
DIRE_TOKEN_ID=...
TARGET_SERVER_STEAM_ID=...
TARGET_RADIANT_TEAM=...
TARGET_DIRE_TEAM=...
```

Review that file before live probing.

Live auto-discovery is still blocked unless you explicitly opt in:

```env
ENABLE_LIVE_TRADING=true
LIVE_PROBE_ONLY=true
AUTO_DISCOVER_POLYMARKET=true
ALLOW_LIVE_AUTO_DISCOVERY=true
ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=false
```

For live auto-discovery, set at least one target selector:

```env
TARGET_RADIANT_TEAM=...
TARGET_DIRE_TEAM=...
```

or:

```env
TARGET_MATCH=...
```

The bot refuses live auto-discovery unless it has confirmed a visible Dota game and obtained `TARGET_SERVER_STEAM_ID`. It will not use unconfirmed Polymarket mapping in live mode.

Do **not** set `ALLOW_LIVE_ANY_DISCOVERED_MATCH=true` unless you intentionally want the bot to choose any discovered Dota/Polymarket match.
