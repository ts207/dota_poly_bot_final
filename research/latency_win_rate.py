import sqlite3
import pandas as pd
import os

DB_PATH = "/home/irene/dota_poly_bot_final/data/dota_poly_collection.sqlite"

def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    signals = pd.read_sql_query("""
    SELECT
      s.id,
      s.ts_ms,
      s.trigger,
      s.side,
      s.target_token_id,
      s.game_time,
      s.edge
    FROM signals s
    WHERE s.trigger IN ('DOTA_SPIKE_LATENCY', 'API_LATENCY_GAP')
    ORDER BY s.ts_ms
    """, conn)

    ticks = pd.read_sql_query("""
    SELECT ts_ms, token_id, best_bid, best_ask, mid
    FROM market_ticks
    WHERE token_id != 'COMBINED_RADIANT'
    ORDER BY ts_ms
    """, conn)

    conn.close()

    if signals.empty:
        print("No latency signals found.")
        return

    rows = []

    for _, s in signals.iterrows():
        token_ticks = ticks[ticks.token_id == str(s.target_token_id)]
        before = token_ticks[token_ticks.ts_ms <= s.ts_ms].tail(1)

        if before.empty:
            continue

        base_mid = float(before.iloc[0].mid)

        row = {
            "trigger": s.trigger,
            "side": s.side,
            "base_mid": base_mid,
            "edge": s.edge,
        }

        for h in [5, 10, 15, 30]:
            future = token_ticks[token_ticks.ts_ms >= s.ts_ms + h * 1000].head(1)
            if future.empty:
                row[f"move_{h}s"] = None
                row[f"win_{h}s"] = None
                continue

            future_mid = float(future.iloc[0].mid)
            move = future_mid - base_mid

            row[f"move_{h}s"] = move
            row[f"win_{h}s"] = move > 0

        rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        print("No comparable market ticks found.")
        return

    print("\n=== Latency Directional Win Rate ===")
    for h in [5, 10, 15, 30]:
        col = f"win_{h}s"
        valid = df[df[col].notna()]
        if valid.empty:
            continue
        print(
            f"{h}s: win_rate={valid[col].mean():.2%}, "
            f"avg_move={valid[f'move_{h}s'].mean():.4f}, "
            f"count={len(valid)}"
        )

    print("\nBy trigger:")
    for h in [5, 10, 15, 30]:
        print(f"\n{h}s horizon")
        col = f"win_{h}s"
        if col in df.columns:
            stats = df.groupby("trigger").agg(
                count=(col, "count"),
                win_rate=(col, "mean"),
                avg_move=(f"move_{h}s", "mean"),
            ).round(4)
            print(stats)

if __name__ == "__main__":
    main()
