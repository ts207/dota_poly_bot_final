import sqlite3, json

DBS = [
    'data/1win_ptime_g2.sqlite',
    'data/dota_poly_collection.sqlite',
    'data/lynx_tm6_collection.sqlite',
]

for path in DBS:
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"\n=== {path} ===")
    for t in tables:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        n = c.fetchone()[0]
        print(f"  {t}: {n} rows")

    # Match coverage
    if 'dota_ticks' in tables:
        c.execute("""
            SELECT match_key, radiant_team, dire_team,
                   COUNT(*) as n, MIN(game_time) as gt_min, MAX(game_time) as gt_max
            FROM dota_ticks GROUP BY match_key ORDER BY MIN(ts_ms)
        """)
        for r in c.fetchall():
            print(f"  match {r[0]}: {r[1]} vs {r[2]}  ticks={r[3]}  gt={r[4]:.0f}-{r[5]:.0f}s")

    # Signals
    if 'signals' in tables:
        c.execute("SELECT COUNT(*), MIN(game_time), MAX(game_time) FROM signals")
        r = c.fetchone()
        print(f"  signals: {r[0]} (gt {r[1]}-{r[2]})")
        c.execute("SELECT trigger, side, COUNT(*), AVG(edge) FROM signals GROUP BY trigger, side")
        for r in c.fetchall():
            print(f"    {r[0]} {r[1]}: {r[2]} signals  avg_edge={r[3]:.3f}")

    # Paper trades
    if 'paper_trades' in tables:
        c.execute("SELECT COUNT(*), SUM(filled) FROM paper_trades")
        r = c.fetchone()
        print(f"  paper_trades: {r[0]} total, {r[1]} filled")

    # Orders (live)
    if 'orders' in tables:
        c.execute("SELECT COUNT(*), COUNT(fill_price) FROM orders WHERE fill_price IS NOT NULL OR filled_size > 0")
        r = c.fetchone()
        print(f"  orders with fills: {r[0]}")
        c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        for r in c.fetchall():
            print(f"    status={r[0]}: {r[1]}")

    # run_configs
    if 'run_configs' in tables:
        c.execute("SELECT run_id, ts_ms, enabled_triggers, risk_max_book_age_ms FROM run_configs ORDER BY ts_ms DESC LIMIT 3")
        for r in c.fetchall():
            print(f"  run: {r[0][:30]}  book_age={r[3]}  triggers={r[2][:60]}")

    conn.close()
