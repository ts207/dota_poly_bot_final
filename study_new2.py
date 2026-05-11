import sqlite3

# ── dota_poly_collection deep dive ──────────────────────────────────────────
conn = sqlite3.connect('data/dota_poly_collection.sqlite')
c = conn.cursor()

print("=== MATCH OUTCOMES ===")
c.execute("""
    SELECT match_key, radiant_team, dire_team,
           MIN(ts_ms) as t_start, MAX(ts_ms) as t_end,
           MAX(game_time) as gt_max
    FROM dota_ticks GROUP BY match_key ORDER BY t_start
""")
matches = c.fetchall()
for m in matches:
    mk, rt, dt, t0, t1, gt = m
    # terminal radiant price
    c.execute("""
        SELECT mt.token_id, mt.mid, mt.best_bid, mt.best_ask
        FROM market_ticks mt
        WHERE mt.ts_ms = (SELECT MAX(ts_ms) FROM market_ticks WHERE ts_ms <= ?)
        ORDER BY mt.ts_ms DESC LIMIT 4
    """, (t1 + 30000,))
    ticks = c.fetchall()
    mids = [(str(r[0])[:12], round(r[1],3)) for r in ticks]
    print(f"  {mk[:30]} | {rt:<20} vs {dt:<20} | gt_max={gt:.0f}s | final_mids={mids}")

print()
print("=== SIGNALS BY MATCH ===")
c.execute("""
    SELECT s.match_key, s.trigger, s.side, s.edge, s.game_time, s.expected_move, s.execution_mode, s.action
    FROM signals s ORDER BY s.ts_ms
""")
sigs = c.fetchall()
for s in sigs[:30]:
    mk, trig, side, edge, gt, exp, mode, action = s
    print(f"  {mk[:28]} gt={int(gt):>5}  {trig:<18} {side:<18} edge={edge:.3f}  exp={exp:.3f}  mode={mode}")
if len(sigs) > 30:
    print(f"  ... ({len(sigs)-30} more)")

print()
print("=== PAPER TRADES (fills) ===")
c.execute("""
    SELECT pt.ts_ms, pt.side, pt.intended_price, pt.fill_price, pt.filled,
           pt.exit_bid_15s, pt.exit_bid_30s, pt.exit_bid_60s,
           pt.pnl_15s, pt.pnl_30s, pt.pnl_60s, pt.pnl_120s
    FROM paper_trades pt WHERE pt.filled = 1
""")
for r in c.fetchall():
    ts, side, ip, fp, filled, eb15, eb30, eb60, p15, p30, p60, p120 = r
    print(f"  {side:<18} entry={ip:.3f} fill={fp:.3f}  pnl[15s={p15} 30s={p30} 60s={p60} 120s={p120}]")

print()
print("=== CLEAN SIGNALS (31) ===")
c.execute("PRAGMA table_info(clean_signals)")
cols = [r[1] for r in c.fetchall()]
print(f"  columns: {cols}")
c.execute("SELECT * FROM clean_signals ORDER BY ts_ms LIMIT 10")
rows = c.fetchall()
for r in rows:
    d = dict(zip(cols, r))
    keys = ['match_key','trigger','side','edge','game_time','expected_move','action']
    print("  ", {k: d[k] for k in keys if k in d})

print()
print("=== CLEAN RESEARCH DATASET ===")
c.execute("PRAGMA table_info(clean_research_dataset)")
cols2 = [r[1] for r in c.fetchall()]
print(f"  columns: {cols2}")
c.execute("SELECT * FROM clean_research_dataset ORDER BY ts_ms LIMIT 5")
rows = c.fetchall()
for r in rows:
    d = dict(zip(cols2, r))
    print("  ", {k: round(v,3) if isinstance(v, float) else v for k, v in d.items() if v is not None})

print()
print("=== 1WIN_PTIME_G2 SIGNALS ===")
conn2 = sqlite3.connect('data/1win_ptime_g2.sqlite')
c2 = conn2.cursor()
c2.execute("SELECT trigger, side, edge, game_time, expected_move, execution_mode FROM signals ORDER BY ts_ms")
for r in c2.fetchall():
    print(f"  {r[0]:<18} {r[1]:<18} edge={r[2]:.3f}  gt={int(r[3])}  exp={r[4]:.3f}  mode={r[5]}")
# terminal price
c2.execute("SELECT DISTINCT token_id, AVG(mid) as avg_mid FROM market_ticks GROUP BY token_id")
tids = sorted(c2.fetchall(), key=lambda r: r[1])
print(f"  radiant_token (low_mid): {str(tids[0][0])[:20]}... avg_mid={tids[0][1]:.3f}")
print(f"  dire_token (high_mid):   {str(tids[1][0])[:20]}... avg_mid={tids[1][1]:.3f}")
c2.execute("SELECT token_id, mid FROM market_ticks ORDER BY ts_ms DESC LIMIT 4")
for r in c2.fetchall():
    print(f"  final tick: token={str(r[0])[:16]}... mid={r[1]:.3f}")
conn2.close()
conn.close()
