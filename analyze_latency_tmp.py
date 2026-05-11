import sqlite3, pandas as pd, numpy as np, os
os.chdir('/home/irene/dota_poly_bot_final')
conn = sqlite3.connect('data/dota_poly_collection.sqlite')

# ── 1. API-to-market latency CSV ────────────────────────────────────────────
lat = pd.read_csv('data/api_to_market_latency.csv')
print('=== API-TO-MARKET LATENCY (n=%d events) ===' % len(lat))
print(lat.to_string())

# ── 2. Latency distribution detail ──────────────────────────────────────────
print()
print('=== LATENCY DISTRIBUTION ===')
print(lat['latency_s'].describe().round(3))
print()
pcts = [10,25,50,75,90,95,99]
print('Percentiles:')
for p in pcts:
    print(f'  p{p}: {np.percentile(lat["latency_s"], p):.2f}s')

print()
print('=== LATENCY BY EVENT TYPE ===')
print(lat.groupby('event_type')['latency_s'].describe().round(3).to_string())

print()
print('=== MARKET MOVE SIZE BY LATENCY BUCKET ===')
bins  = [0, 1, 3, 5, 10, 15, 30]
labels = ['<1s','1-3s','3-5s','5-10s','10-15s','15-30s']
lat['bucket'] = pd.cut(lat['latency_s'], bins=bins, labels=labels)
agg = lat.groupby('bucket').agg(
    count=('market_move','count'),
    avg_abs_move=('market_move', lambda x: x.abs().mean()),
    avg_move=('market_move','mean'),
    pct_nonzero=('market_move', lambda x: (x.abs() > 0.005).mean()),
).round(4)
print(agg.to_string())

# ── 3. How much edge is capturable per latency bucket? ───────────────────────
# At each latency band, what fraction of the market move had already happened
# by the time our order would have reached the exchange?
# Assumption: taker order reaches exchange in ~0.3s after signal fires.
# The market move up to 0.3s post-event is "already captured by others".
# The remaining move from 0.3s to latency_s is what we could capture.
print()
print('=== EDGE CAPTURE WINDOW ===')
# We have latency_s (first market move) and market_move (total).
# Approximate: the market moves ~linearly during the latency window.
# "Capturable fraction" = what's left after 0.3s execution lag
bot_exec_lag = 0.3  # rough estimate: API poll + compute + order submission
lat['frac_remaining'] = (lat['latency_s'] - bot_exec_lag).clip(lower=0) / lat['latency_s'].clip(lower=0.01)
lat['capturable_move'] = lat['market_move'].abs() * lat['frac_remaining']
print(lat[['event_type','latency_s','market_move','frac_remaining','capturable_move']].to_string())
print()
print('Avg capturable move:', lat['capturable_move'].mean().round(4))
print('Avg market move:    ', lat['market_move'].abs().mean().round(4))

# ── 4. Dota tick poll interval vs. market reaction speed ─────────────────────
print()
print('=== KILL DETECTION TIMING (main match) ===')
ticks = pd.read_sql(
    "SELECT game_time, radiant_score, dire_score, nw_diff, ts_ms "
    "FROM dota_ticks WHERE match_key = '90285599503423511_m1' "
    "AND run_id = 'run-1778500128141-fabf67b3' ORDER BY ts_ms",
    conn)
ticks['total_kills'] = ticks['radiant_score'] + ticks['dire_score']
ticks['kill_delta'] = ticks['total_kills'].diff().fillna(0)
ticks['gt_jump'] = ticks['game_time'].diff().fillna(0)
ticks['wall_gap_s'] = ticks['ts_ms'].diff().fillna(0) / 1000.0

# Real-time gap between when kill happened and when bot detected it
# If game_time jumped by gt_jump, the kill happened ~gt_jump/2 seconds before the new tick arrived
# (uniformly distributed within the Steam update window)
kill_rows = ticks[ticks['kill_delta'] > 0].copy()
kill_rows['detection_lag_s'] = kill_rows['gt_jump'] / 2.0  # expected mid-window lag

print('Kill detection lag distribution (gt_jump/2):')
print(kill_rows['detection_lag_s'].describe().round(2))
print()
print('Expected detection lag (p50):', kill_rows['detection_lag_s'].median(), 's')
print('Expected detection lag (p75):', kill_rows['detection_lag_s'].quantile(0.75), 's')

# ── 5. End-to-end latency budget ─────────────────────────────────────────────
print()
print('=== END-TO-END LATENCY BUDGET ===')
# Total lag = kill_detection_lag + compute_lag + order_submission_lag
# Market reaction latency (from our measurement) = 7.4s median
# Our total lag = detection_lag + ~0.1s compute + ~0.3s order submission
detection_med = kill_rows['detection_lag_s'].median()
compute_lag   = 0.1
order_lag     = 0.3
our_total     = detection_med + compute_lag + order_lag
market_react  = lat['latency_s'].median()
edge_window   = market_react - our_total

print(f'  Kill detection lag (median gt_jump/2): {detection_med:.1f}s')
print(f'  Compute + features:                   {compute_lag:.1f}s')
print(f'  Order submission:                     {order_lag:.1f}s')
print(f'  Our total lag (median):               {our_total:.1f}s')
print(f'  Market reaction latency (median):     {market_react:.1f}s')
print(f'  Edge window (market - us):            {edge_window:.1f}s')
print()
print('  If edge_window > 0: we fire BEFORE market reacts (opportunity exists)')
print('  If edge_window < 0: market has already moved when we fire')

# ── 6. Fast events (where we actually have edge) ─────────────────────────────
print()
print('=== FAST-REACT EVENTS (latency_s < 3s) ===')
fast = lat[lat['latency_s'] < 3.0]
print(f'Count: {len(fast)}/{len(lat)} ({100*len(fast)/len(lat):.0f}%)')
print(fast[['event_time_s','event_type','latency_s','market_move','nw_change','score_change']].to_string())
print()
print('Fast event avg market move:', fast['market_move'].abs().mean().round(4))
print('Fast event nw_change:', fast['nw_change'].abs().mean().round(0))

# ── 7. Required edge vs. available edge ──────────────────────────────────────
print()
print('=== EDGE SUFFICIENCY CHECK ===')
# Market spread on main market (0xe791): avg 6.8c
# Taker cost = crossing spread = ~3.4c per side = 6.8c roundtrip
# Min profitable move = spread/2 + fees ~ 3.5c
spread_cost = 0.034  # one-way cost to cross
min_move_needed = spread_cost

fast_moves = fast['market_move'].abs()
slow_moves = lat[lat['latency_s'] >= 3]['market_move'].abs()
print(f'Taker spread cost (one-way, ~half spread): {spread_cost:.3f}')
print(f'Min market move needed to cover cost:      {min_move_needed:.3f}')
print()
print(f'Fast events (<3s): {(fast_moves > min_move_needed).sum()}/{len(fast_moves)} moves > {min_move_needed:.3f}')
print(f'Slow events (>=3s): {(slow_moves > min_move_needed).sum()}/{len(slow_moves)} moves > {min_move_needed:.3f}')
print()
print(f'Fast event moves: {fast_moves.tolist()}')

conn.close()
