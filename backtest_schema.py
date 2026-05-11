import sqlite3

for game, path in [('G1', 'data/1win_pari_g1.sqlite'), ('G2', 'data/1win_pari_g2.sqlite'), ('G3', 'data/1win_pari_g3.sqlite')]:
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"\n=== {game} tables: {tables} ===")
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        cols = [(r[1], r[2]) for r in c.fetchall()]
        c.execute(f"SELECT COUNT(*) FROM {t}")
        n = c.fetchone()[0]
        print(f"  {t} ({n} rows): {[col for col,_ in cols]}")
    conn.close()
