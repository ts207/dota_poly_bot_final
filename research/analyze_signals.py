"""
Analyze dry-run signals and simulate whether orders were realistically fillable.

Examples:
    python research/analyze_signals.py --db ./data/dota_poly_collection.sqlite
    python research/analyze_signals.py --db ./data/match.sqlite --fill-window 2 --write-paper

Paper-fill model:
  - Uses the dry order's intended limit price and size.
  - Looks at market_ticks for the ordered token for the next N seconds.
  - If best_ask <= intended_price and ask_depth >= intended_size, fill at best_ask.
  - Exits conservatively against future best_bid at 15/30/60/120 seconds.
"""
import argparse
import sqlite3
from pathlib import Path
from typing import Optional
import pandas as pd

HORIZONS = (15, 30, 60, 120)


def future_tick(conn, market_id: str, token_id: str, ts_ms: int, horizon_s: int):
    target = ts_ms + horizon_s * 1000
    return pd.read_sql_query(
        """
        SELECT * FROM market_ticks
        WHERE market_id = ? AND token_id = ? AND ts_ms >= ?
        ORDER BY ts_ms ASC
        LIMIT 1
        """,
        conn,
        params=(market_id, token_id, target),
    )


def find_fill(conn, market_id: str, token_id: str, order_ts_ms: int, intended_price: float, intended_size: float, fill_window_s: float):
    end_ts = order_ts_ms + int(fill_window_s * 1000)
    ticks = pd.read_sql_query(
        """
        SELECT * FROM market_ticks
        WHERE market_id = ? AND token_id = ? AND ts_ms >= ? AND ts_ms <= ?
        ORDER BY ts_ms ASC
        """,
        conn,
        params=(market_id, token_id, order_ts_ms, end_ts),
    )
    if ticks.empty:
        return None
    for _, t in ticks.iterrows():
        ask = float(t.best_ask)
        depth = float(t.ask_depth or 0)
        if ask <= intended_price and depth >= intended_size:
            return {
                "fill_ts_ms": int(t.ts_ms),
                "fill_price": ask,
                "fill_tick": t,
            }
    return None


def write_paper_row(conn, row):
    cols = [
        "signal_id", "order_id", "ts_ms", "market_id", "token_id", "side", "intended_price", "intended_size",
        "filled", "fill_price", "fill_ts_ms", "exit_bid_15s", "exit_bid_30s", "exit_bid_60s", "exit_bid_120s",
        "pnl_15s", "pnl_30s", "pnl_60s", "pnl_120s",
    ]
    conn.execute(
        f"INSERT INTO paper_trades ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
        [row.get(c) for c in cols],
    )


def analyze(db_path: str, fill_window_s: float, write_paper: bool):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    orders = pd.read_sql_query(
        """
        SELECT o.*, s.side AS signal_side, s.signal_type, s.edge, s.market_lag, s.game_time
        FROM orders o
        LEFT JOIN signals s ON s.id = o.signal_id
        ORDER BY o.ts_ms ASC
        """,
        conn,
    )
    if orders.empty:
        print("No orders found. Run the bot in dry-run mode until it logs signals/orders.")
        return

    if write_paper:
        conn.execute("DELETE FROM paper_trades")

    rows = []
    for _, o in orders.iterrows():
        token_id = str(o.token_id)
        market_id = str(o.market_id)
        intended_price = float(o.price)
        intended_size = float(o.size)
        order_ts = int(o.ts_ms)

        fill = find_fill(conn, market_id, token_id, order_ts, intended_price, intended_size, fill_window_s)
        filled = fill is not None
        fill_price = float(fill["fill_price"]) if filled else None
        fill_ts = int(fill["fill_ts_ms"]) if filled else None

        row = {
            "order_id": int(o.id),
            "signal_id": int(o.signal_id) if pd.notna(o.signal_id) else None,
            "ts_ms": order_ts,
            "market_id": market_id,
            "token_id": token_id,
            "side": str(o.side),
            "signal_side": o.signal_side,
            "signal_type": o.signal_type,
            "edge": float(o.edge) if pd.notna(o.edge) else None,
            "market_lag": float(o.market_lag) if pd.notna(o.market_lag) else None,
            "game_time": float(o.game_time) if pd.notna(o.game_time) else None,
            "intended_price": intended_price,
            "intended_size": intended_size,
            "filled": int(filled),
            "fill_price": fill_price,
            "fill_ts_ms": fill_ts,
        }

        for h in HORIZONS:
            ft = future_tick(conn, market_id, token_id, fill_ts or order_ts, h)
            exit_bid = None if ft.empty else float(ft.iloc[0]["best_bid"])
            row[f"exit_bid_{h}s"] = exit_bid
            row[f"pnl_{h}s"] = None if (not filled or exit_bid is None or fill_price is None) else exit_bid - fill_price

        if write_paper:
            write_paper_row(conn, row)
        rows.append(row)

    if write_paper:
        conn.commit()

    out = pd.DataFrame(rows)
    if out.empty:
        print("No analyzable dry orders.")
        return

    print("Dry orders:", len(out))
    print(f"Paper-fill window: {fill_window_s:.2f}s")
    print(f"Fill rate: {out['filled'].mean():.2%}")

    if "signal_type" in out:
        print("\nBy signal_type:")
        print(out.groupby("signal_type", dropna=False).agg(
            orders=("order_id", "count"),
            fill_rate=("filled", "mean"),
        ).sort_values("orders", ascending=False))

    for h in HORIZONS:
        col = f"pnl_{h}s"
        valid = out[out["filled"] == 1][col].dropna()
        if valid.empty:
            continue
        print(f"\n{h}s paper-filled conservative PnL:")
        print(f"  mean: {valid.mean():.4f}")
        print(f"  median: {valid.median():.4f}")
        print(f"  win_rate_gt_0: {(valid > 0).mean():.2%}")

    # Useful diagnostic buckets.
    if "edge" in out:
        out["edge_bucket"] = pd.cut(out["edge"], bins=[0, 0.05, 0.075, 0.10, 0.15, 1.0], labels=["0-5%", "5-7.5%", "7.5-10%", "10-15%", "15%+"])
        print("\nBy edge bucket:")
        print(out.groupby("edge_bucket", observed=False).agg(
            orders=("order_id", "count"), 
            fill_rate=("filled", "mean"),
            win_rate_120s=("pnl_120s", lambda x: (x > 0).mean()),
            mean_pnl_120s=("pnl_120s", "mean"),
            median_pnl_120s=("pnl_120s", "median")
        ))

    # Detailed Breakdown: Signal Type x Edge Bucket
    if "edge" in out and "signal_type" in out:
        print("\n--- Cross-Analysis: Signal Type x Edge Bucket (120s Horizon) ---")
        cross = out.groupby(["signal_type", "edge_bucket"], observed=False).agg(
            orders=("order_id", "count"),
            win_rate=("pnl_120s", lambda x: (x > 0).mean()),
            mean_pnl=("pnl_120s", "mean"),
            median_pnl=("pnl_120s", "median")
        ).round(4)
        print(cross[cross["orders"] > 0])

    if "game_time" in out and out["game_time"].notna().any():
        out["minute_bucket"] = pd.cut(out["game_time"] / 60, bins=[0, 10, 20, 30, 45, 999], labels=["0-10", "10-20", "20-30", "30-45", "45+"])
        print("\nBy game-time bucket:")
        print(out.groupby("minute_bucket", observed=False).agg(orders=("order_id", "count"), fill_rate=("filled", "mean")))

    out_path = Path(db_path).with_name("paper_signal_analysis.csv")
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")
    if write_paper:
        print("Updated paper_trades table.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="dota_poly_bot/storage/bot_data.db")
    parser.add_argument("--fill-window", type=float, default=2.0)
    parser.add_argument("--write-paper", action="store_true")
    args = parser.parse_args()
    analyze(args.db, args.fill_window, args.write_paper)
