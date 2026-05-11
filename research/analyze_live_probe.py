#!/usr/bin/env python3
"""Analyze tiny live-probe order/fill quality by trigger.

This script is intentionally read-only. It summarizes whether live maker probes
were filled, whether those fills were toxic, and whether no-fill signals were
missed winners.

Usage:
    python research/analyze_live_probe.py --db./data/dota_poly_collection.sqlite
    python research/analyze_live_probe.py --db./data/dota_poly_collection.sqlite --csv ./data/live_probe_summary.csv
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional


SNAPSHOT_OFFSETS = (0.0, 5.0, 15.0, 30.0, 60.0)


@dataclass
class TriggerStats:
    trigger: str
    trigger_strength: str = ""
    signals: int = 0
    orders_sent: int = 0
    fills: int = 0
    filled_size: float = 0.0
    pnl_by_offset: Dict[float, list[float]] = field(default_factory=lambda: {x: [] for x in SNAPSHOT_OFFSETS})
    toxic_15s: int = 0
    no_fill_good_moves: int = 0
    no_fill_bad_moves: int = 0
    submit_ack_ms: list[float] = field(default_factory=list)
    cancel_ack_ms: list[float] = field(default_factory=list)

    def row(self) -> Dict[str, object]:
        def avg(values: Iterable[float]) -> Optional[float]:
            values = list(values)
            return round(sum(values) / len(values), 6) if values else None

        fill_rate = self.fills / self.orders_sent if self.orders_sent else 0.0
        toxic_rate = self.toxic_15s / self.fills if self.fills else 0.0
        no_fill_total = self.no_fill_good_moves + self.no_fill_bad_moves
        no_fill_good_rate = self.no_fill_good_moves / no_fill_total if no_fill_total else 0.0

        out = {
            "trigger": self.trigger,
            "trigger_strength": self.trigger_strength,
            "signals": self.signals,
            "orders_sent": self.orders_sent,
            "fills": self.fills,
            "fill_rate": round(fill_rate, 4),
            "filled_size": round(self.filled_size, 4),
            "toxic_fill_rate_15s": round(toxic_rate, 4),
            "no_fill_good_move_rate_30s": round(no_fill_good_rate, 4),
            "avg_submit_ack_ms": avg(self.submit_ack_ms),
            "avg_cancel_ack_ms": avg(self.cancel_ack_ms),
        }
        for offset in SNAPSHOT_OFFSETS:
            out[f"avg_pnl_{int(offset)}s"] = avg(self.pnl_by_offset[offset])
        return out


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone())


def nearest_market_mid(conn: sqlite3.Connection, token_id: str, ts_ms: int, max_delta_ms: int = 30_000) -> Optional[float]:
    row = conn.execute(
        """
        SELECT mid, ABS(ts_ms - ?) AS dt
        FROM market_ticks
        WHERE token_id = ?
          AND ABS(ts_ms - ?) <= ?
        ORDER BY dt ASC
        LIMIT 1
        """,
        (ts_ms, token_id, ts_ms, max_delta_ms),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def market_mid_at_or_after(conn: sqlite3.Connection, token_id: str, ts_ms: int, offset_s: float) -> Optional[float]:
    target_ts = int(ts_ms + offset_s * 1000)
    row = conn.execute(
        """
        SELECT mid
        FROM market_ticks
        WHERE token_id = ?
          AND ts_ms >= ?
        ORDER BY ts_ms ASC
        LIMIT 1
        """,
        (token_id, target_ts),
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def load_signal_map(conn: sqlite3.Connection) -> Dict[int, dict]:
    rows = conn.execute(
        """
        SELECT id, ts_ms, trigger, COALESCE(trigger_strength, '') AS trigger_strength, side, target_token_id, fair_price, edge
        FROM signals
        """
    ).fetchall()
    return {
        int(r[0]): {
            "ts_ms": int(r[1]),
            "trigger": str(r[2] or "UNKNOWN"),
            "trigger_strength": str(r[3] or ""),
            "side": str(r[4] or ""),
            "token_id": str(r[5] or ""),
            "fair_price": r[6],
            "edge": r[7],
        }
        for r in rows
    }



def rejection_summary(conn: sqlite3.Connection) -> list[Dict[str, object]]:
    if not table_exists(conn, "signal_rejections"):
        return []
    rows = conn.execute(
        """
        SELECT COALESCE(trigger, 'UNKNOWN') AS trigger,
               COALESCE(trigger_strength, '') AS trigger_strength,
               COALESCE(reason, 'UNKNOWN') AS reason,
               COUNT(*) AS n
        FROM signal_rejections
        GROUP BY COALESCE(trigger, 'UNKNOWN'), COALESCE(trigger_strength, ''), COALESCE(reason, 'UNKNOWN')
        ORDER BY n DESC
        """
    ).fetchall()
    return [{"trigger": r["trigger"], "trigger_strength": r["trigger_strength"], "reason": r["reason"], "count": int(r["n"])} for r in rows]

def analyze(db_path: str) -> list[Dict[str, object]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        required = ["signals", "orders", "market_ticks"]
        missing = [t for t in required if not table_exists(conn, t)]
        if missing:
            raise SystemExit(f"Missing required tables: {', '.join(missing)}")

        has_events = table_exists(conn, "live_order_events")
        has_snapshots = table_exists(conn, "live_fill_snapshots")

        signals = load_signal_map(conn)
        stats: Dict[str, TriggerStats] = {}

        for sig in signals.values():
            trigger = sig["trigger"] or "UNKNOWN"
            strength = sig.get("trigger_strength") or ""
            key = f"{trigger}:{strength}" if strength else trigger
            stats.setdefault(key, TriggerStats(trigger=trigger, trigger_strength=strength)).signals += 1

        live_orders = conn.execute(
            """
            SELECT id, ts_ms, signal_id, token_id, price, size, status,
                   exchange_order_id, ack_ms, cancel_ack_ms, fill_price, filled_size
            FROM orders
            WHERE status LIKE 'LIVE_%' OR exchange_order_id IS NOT NULL
            ORDER BY ts_ms
            """
        ).fetchall()

        # Collapse to one submitted order per exchange_order_id where possible.
        seen_orders: set[str] = set()
        order_rows = []
        for o in live_orders:
            key = str(o["exchange_order_id"] or f"db-{o['id']}")
            if key in seen_orders and o["status"] != "LIVE_SENT":
                continue
            if o["status"] == "LIVE_SENT" or key not in seen_orders:
                order_rows.append(o)
                seen_orders.add(key)

        for o in order_rows:
            signal_id = int(o["signal_id"]) if o["signal_id"] is not None else None
            sig = signals.get(signal_id or -1, {})
            trigger = sig.get("trigger") or "UNKNOWN"
            strength = sig.get("trigger_strength") or ""
            key = f"{trigger}:{strength}" if strength else trigger
            st = stats.setdefault(key, TriggerStats(trigger=trigger, trigger_strength=strength))
            st.orders_sent += 1

            if o["ack_ms"] is not None:
                st.submit_ack_ms.append(float(o["ack_ms"]))
            if o["cancel_ack_ms"] is not None:
                st.cancel_ack_ms.append(float(o["cancel_ack_ms"]))

            exchange_order_id = str(o["exchange_order_id"] or "")
            token_id = str(o["token_id"] or sig.get("token_id") or "")
            fill_price = o["fill_price"]
            filled_size = o["filled_size"]

            if has_events and exchange_order_id:
                ev = conn.execute(
                    """
                    SELECT filled_size, avg_fill_price
                    FROM live_order_events
                    WHERE exchange_order_id = ?
                      AND event_type = 'FILL_DETECTED'
                      AND COALESCE(filled_size, 0) > 0
                    ORDER BY ts_ms DESC
                    LIMIT 1
                    """,
                    (exchange_order_id,),
                ).fetchone()
                if ev:
                    filled_size = ev["filled_size"]
                    fill_price = ev["avg_fill_price"] or fill_price

            is_fill = bool(filled_size and float(filled_size) > 0)
            if is_fill:
                st.fills += 1
                st.filled_size += float(filled_size or 0)
                if fill_price is None:
                    # Cannot score PnL without a fill price.
                    continue
                fill_price_f = float(fill_price)
                if has_snapshots and exchange_order_id:
                    snaps = conn.execute(
                        """
                        SELECT seconds_after_fill, best_bid
                        FROM live_fill_snapshots
                        WHERE exchange_order_id = ?
                        """,
                        (exchange_order_id,),
                    ).fetchall()
                    for snap in snaps:
                        off = float(snap["seconds_after_fill"])
                        if off in st.pnl_by_offset and snap["best_bid"] is not None:
                            pnl = float(snap["best_bid"]) - fill_price_f
                            st.pnl_by_offset[off].append(pnl)
                            if off == 15.0 and pnl < 0:
                                st.toxic_15s += 1
            else:
                # Approximate no-fill opportunity cost: did mid move in predicted direction after 30s?
                sig_ts = int(sig.get("ts_ms") or o["ts_ms"])
                side = str(sig.get("side") or "")
                start_mid = nearest_market_mid(conn, token_id, sig_ts)
                later_mid = market_mid_at_or_after(conn, token_id, sig_ts, 30.0)
                if start_mid is not None and later_mid is not None:
                    moved_up = later_mid - start_mid > 0.01
                    moved_down = start_mid - later_mid > 0.01
                    # Since all execution is BUY on the target token, good no-fill move means target token moved up.
                    if moved_up:
                        st.no_fill_good_moves += 1
                    elif moved_down:
                        st.no_fill_bad_moves += 1

        return [stats[k].row() for k in sorted(stats)]
    finally:
        conn.close()


def print_table(rows: list[Dict[str, object]]) -> None:
    if not rows:
        print("No live-probe data found.")
        return
    columns = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))


def write_csv(rows: list[Dict[str, object]], path: str) -> None:
    if not rows:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--csv", help="Optional CSV output path")
    parser.add_argument("--no-rejections", action="store_true", help="Do not print signal rejection summary")
    args = parser.parse_args()

    rows = analyze(args.db)
    print("Live-probe performance by trigger")
    print_table(rows)

    if not args.no_rejections:
        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        try:
            rejection_rows = rejection_summary(conn)
        finally:
            conn.close()
        print("\nSignal rejection summary")
        print_table(rejection_rows)

    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nWrote {args.csv}")


if __name__ == "__main__":
    main()
