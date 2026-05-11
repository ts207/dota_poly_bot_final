"""
Normalize and clean Dota/Polymarket bot collection data without mutating raw tables.

Raw tables such as dota_ticks, market_ticks, signals, orders, paper_trades, and
signal_rejections are treated as append-only source data. This script creates a
cleaning layer for research and exports CSVs when requested.

Example:
    python research/clean_data.py --db ./data/dota_poly_collection.sqlite --write-csv
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path
from typing import Iterable


BOOK_DEDUPE_COLS = [
    "market_id", "token_id", "ts_ms", "best_bid", "best_ask", "mid", "spread", "bid_depth", "ask_depth"
]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def qcol(table_cols: set[str], name: str, fallback: str = "NULL") -> str:
    return name if name in table_cols else fallback


def run_cols_select(table_cols: set[str], prefix: str = "") -> str:
    parts = []
    for col in ["run_id", "pid", "git_sha", "started_at_ts_ms"]:
        if col in table_cols:
            parts.append(f"{prefix}{col} AS {col}")
        else:
            parts.append(f"NULL AS {col}")
    return ", ".join(parts)


def valid_token_expr(col: str = "token_id") -> str:
    return f"({col} IS NOT NULL AND TRIM({col}) != '' AND LOWER(TRIM({col})) NOT IN ('0','0x','none','null','todo'))"


def exec_sql(conn: sqlite3.Connection, sql: str) -> None:
    conn.executescript(sql)


def create_cleaning_rejections(conn: sqlite3.Connection) -> None:
    exec_sql(conn, "DROP TABLE IF EXISTS cleaning_rejections;")
    conn.execute(
        """
        CREATE TABLE cleaning_rejections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER,
            reason TEXT NOT NULL,
            detail TEXT
        )
        """
    )


def clean_dota_states(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "dota_ticks"):
        return {"raw_dota_ticks": 0, "clean_dota_states": 0}

    c = columns(conn, "dota_ticks")
    building_col = qcol(c, "building_state", "NULL")
    api_delay_col = qcol(c, "api_delay_s", "NULL")
    run_cols = run_cols_select(c)

    exec_sql(conn, "DROP TABLE IF EXISTS clean_dota_states;")
    conn.execute(
        f"""
        CREATE TABLE clean_dota_states AS
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY match_key, game_time, radiant_score, dire_score, nw_diff, {building_col}
                    ORDER BY ts_ms ASC, id ASC
                ) AS rn
            FROM dota_ticks
        )
        SELECT
            id AS source_dota_tick_id,
            {run_cols},
            ts_ms,
            datetime(ts_ms / 1000, 'unixepoch') || 'Z' AS ts_utc,
            match_key,
            server_steam_id,
            partner,
            radiant_team,
            dire_team,
            game_time AS game_time_s,
            game_time / 60.0 AS game_min,
            radiant_score,
            dire_score,
            radiant_nw,
            dire_nw,
            nw_diff,
            total_nw,
            nw_diff_pct,
            {building_col} AS building_state,
            {api_delay_col} AS api_delay_raw_s,
            CASE
                WHEN {api_delay_col} IS NULL THEN NULL
                WHEN {api_delay_col} < 0 THEN 0
                WHEN {api_delay_col} > 300 THEN 300
                ELSE {api_delay_col}
            END AS api_delay_clipped_s,
            CASE
                WHEN {api_delay_col} IS NULL THEN 'UNKNOWN'
                WHEN {api_delay_col} < 0 THEN 'NEGATIVE'
                WHEN {api_delay_col} <= 15 THEN 'GOOD'
                WHEN {api_delay_col} <= 60 THEN 'LAGGED'
                ELSE 'VERY_LAGGED'
            END AS api_delay_quality_bucket,
            1 AS is_valid,
            NULL AS invalid_reason
        FROM ranked
        WHERE rn = 1
        ORDER BY ts_ms ASC
        """
    )
    raw = conn.execute("SELECT COUNT(*) FROM dota_ticks").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM clean_dota_states").fetchone()[0]
    return {"raw_dota_ticks": raw, "clean_dota_states": clean, "duplicate_dota_states_removed": raw - clean}


def clean_market_ticks(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "market_ticks"):
        return {"raw_market_ticks": 0, "clean_market_ticks": 0}

    c = columns(conn, "market_ticks")
    run_cols = run_cols_select(c)
    partition_cols = ", ".join(BOOK_DEDUPE_COLS)

    exec_sql(conn, "DROP TABLE IF EXISTS clean_market_ticks;")
    conn.execute(
        f"""
        CREATE TABLE clean_market_ticks AS
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY {partition_cols}
                    ORDER BY id ASC
                ) AS rn
            FROM market_ticks
        )
        SELECT
            id AS source_market_tick_id,
            {run_cols},
            ts_ms,
            datetime(ts_ms / 1000, 'unixepoch') || 'Z' AS ts_utc,
            market_id,
            token_id,
            best_bid,
            best_ask,
            mid,
            spread,
            bid_depth,
            ask_depth,
            CASE WHEN {valid_token_expr('token_id')} THEN 1 ELSE 0 END AS is_valid,
            CASE WHEN {valid_token_expr('token_id')} THEN NULL ELSE 'INVALID_TOKEN_ID' END AS invalid_reason
        FROM ranked
        WHERE rn = 1
        ORDER BY ts_ms ASC
        """
    )
    conn.execute(
        """
        INSERT INTO cleaning_rejections(source_table, source_id, reason, detail)
        SELECT 'market_ticks', source_market_tick_id, invalid_reason, token_id
        FROM clean_market_ticks
        WHERE is_valid = 0
        """
    )
    raw = conn.execute("SELECT COUNT(*) FROM market_ticks").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM clean_market_ticks").fetchone()[0]
    invalid = conn.execute("SELECT COUNT(*) FROM clean_market_ticks WHERE is_valid = 0").fetchone()[0]
    return {"raw_market_ticks": raw, "clean_market_ticks": clean, "duplicate_market_ticks_removed": raw - clean, "invalid_market_token_rows": invalid}


def build_market_match_segments(conn: sqlite3.Connection) -> dict[str, int]:
    exec_sql(conn, "DROP TABLE IF EXISTS market_match_segments;")
    conn.execute(
        """
        CREATE TABLE market_match_segments (
            segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            match_key TEXT,
            market_id TEXT,
            radiant_token_id TEXT,
            dire_token_id TEXT,
            segment_start_ts_ms INTEGER,
            segment_end_ts_ms INTEGER,
            segment_start_utc TEXT,
            segment_end_utc TEXT,
            overlap_seconds REAL,
            mapping_confidence TEXT,
            invalid_reason TEXT
        )
        """
    )
    if not table_exists(conn, "clean_dota_states") or not table_exists(conn, "clean_market_ticks"):
        return {"market_match_segments": 0}

    conn.execute(
        """
        INSERT INTO market_match_segments(
            run_id, match_key, market_id, radiant_token_id, dire_token_id,
            segment_start_ts_ms, segment_end_ts_ms, segment_start_utc, segment_end_utc,
            overlap_seconds, mapping_confidence, invalid_reason
        )
        WITH d AS (
            SELECT match_key, MIN(ts_ms) d_start, MAX(ts_ms) d_end, MAX(run_id) run_id
            FROM clean_dota_states
            GROUP BY match_key
        ),
        m AS (
            SELECT market_id, MIN(ts_ms) m_start, MAX(ts_ms) m_end
            FROM clean_market_ticks
            WHERE market_id IS NOT NULL AND market_id != ''
            GROUP BY market_id
        ),
        o AS (
            SELECT
                d.run_id,
                d.match_key,
                m.market_id,
                MAX(d.d_start, m.m_start) AS start_ts,
                MIN(d.d_end, m.m_end) AS end_ts
            FROM d JOIN m ON MAX(d.d_start, m.m_start) <= MIN(d.d_end, m.m_end)
        )
        SELECT
            run_id,
            match_key,
            market_id,
            NULL AS radiant_token_id,
            NULL AS dire_token_id,
            start_ts,
            end_ts,
            datetime(start_ts / 1000, 'unixepoch') || 'Z',
            datetime(end_ts / 1000, 'unixepoch') || 'Z',
            (end_ts - start_ts) / 1000.0,
            'TIME_OVERLAP_ONLY',
            CASE WHEN (end_ts - start_ts) < 60000 THEN 'SHORT_OVERLAP' ELSE NULL END
        FROM o
        ORDER BY start_ts, match_key, market_id
        """
    )
    return {"market_match_segments": conn.execute("SELECT COUNT(*) FROM market_match_segments").fetchone()[0]}


def normalize_reason_sql() -> str:
    return """
    CASE
        WHEN reason = 'REJECT_EDGE' AND edge IS NOT NULL AND edge_floor IS NOT NULL AND edge < edge_floor THEN 'EDGE_TOO_SMALL'
        WHEN reason = 'REJECT_EDGE' AND edge IS NOT NULL AND edge > 0.09 THEN 'EDGE_TOO_LARGE'
        WHEN reason IS NULL OR TRIM(reason) = '' THEN 'UNKNOWN'
        ELSE UPPER(TRIM(reason))
    END
    """


def clean_signal_rejections(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "signal_rejections"):
        return {"raw_signal_rejections": 0, "clean_signal_rejections": 0}
    c = columns(conn, "signal_rejections")
    run_cols = run_cols_select(c)
    normalized = normalize_reason_sql()

    exec_sql(conn, "DROP TABLE IF EXISTS clean_signal_rejections;")
    conn.execute(
        f"""
        CREATE TABLE clean_signal_rejections AS
        WITH ranked AS (
            SELECT
                *,
                {normalized} AS normalized_reason,
                ROW_NUMBER() OVER (
                    PARTITION BY match_key, market_id, token_id, game_time, trigger, trigger_strength, side, {normalized}, edge
                    ORDER BY ts_ms ASC, id ASC
                ) AS rn
            FROM signal_rejections
        )
        SELECT
            id AS source_rejection_id,
            {run_cols},
            printf('%s|%s|%s|%s|%s|%s|%s|%s|%s',
                COALESCE(match_key,''), COALESCE(market_id,''), COALESCE(token_id,''),
                COALESCE(CAST(game_time AS TEXT),''), COALESCE(trigger,''), COALESCE(trigger_strength,''),
                COALESCE(side,''), COALESCE(normalized_reason,''), COALESCE(CAST(edge AS TEXT),'')
            ) AS rejection_key,
            ts_ms,
            datetime(ts_ms / 1000, 'unixepoch') || 'Z' AS ts_utc,
            match_key,
            market_id,
            token_id,
            UPPER(TRIM(COALESCE(side, ''))) AS side,
            UPPER(TRIM(COALESCE(trigger, ''))) AS trigger,
            UPPER(TRIM(COALESCE(trigger_strength, ''))) AS trigger_strength,
            reason,
            normalized_reason,
            game_time AS game_time_s,
            game_time / 60.0 AS game_min,
            mid,
            spread,
            combined_mid_disagreement,
            expected_move,
            fair_price,
            edge,
            edge_floor,
            CASE WHEN token_id IS NULL OR TRIM(token_id) = '' OR LOWER(TRIM(token_id)) IN ('0','0x','none','null','todo') THEN 0 ELSE 1 END AS has_token_id
        FROM ranked
        WHERE rn = 1
        ORDER BY ts_ms ASC
        """
    )
    raw = conn.execute("SELECT COUNT(*) FROM signal_rejections").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM clean_signal_rejections").fetchone()[0]
    missing = conn.execute("SELECT COUNT(*) FROM clean_signal_rejections WHERE has_token_id = 0").fetchone()[0]
    return {"raw_signal_rejections": raw, "clean_signal_rejections": clean, "duplicate_rejections_removed": raw - clean, "rejections_missing_token": missing}


def clean_signals(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "signals"):
        return {"raw_signals": 0, "clean_signals": 0}
    c = columns(conn, "signals")
    run_cols = run_cols_select(c)
    execution_price = qcol(c, "execution_price", "NULL")
    execution_edge = qcol(c, "execution_edge", "NULL")
    execution_mode = qcol(c, "execution_mode", "NULL")

    exec_sql(conn, "DROP TABLE IF EXISTS clean_signals;")
    conn.execute(
        f"""
        CREATE TABLE clean_signals AS
        WITH ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY match_key, market_id, target_token_id, game_time, trigger, trigger_strength, side, edge
                    ORDER BY ts_ms ASC, id ASC
                ) AS rn
            FROM signals
        )
        SELECT
            id AS source_signal_id,
            {run_cols},
            printf('%s|%s|%s|%s|%s|%s|%s|%s', COALESCE(match_key,''), COALESCE(market_id,''), COALESCE(target_token_id,''), COALESCE(CAST(game_time AS TEXT),''), COALESCE(trigger,''), COALESCE(trigger_strength,''), COALESCE(side,''), COALESCE(CAST(edge AS TEXT),'')) AS signal_key,
            ts_ms,
            datetime(ts_ms / 1000, 'unixepoch') || 'Z' AS ts_utc,
            match_key,
            market_id,
            target_token_id AS token_id,
            UPPER(TRIM(COALESCE(side, ''))) AS side,
            signal_type,
            UPPER(TRIM(COALESCE(trigger, ''))) AS trigger,
            UPPER(TRIM(COALESCE(trigger_strength, ''))) AS trigger_strength,
            trigger_window,
            market_state,
            fair_price,
            game_time AS game_time_s,
            game_time / 60.0 AS game_min,
            nw_change_10s, nw_change_30s, nw_change_60s,
            score_change_10s, score_change_30s, score_change_60s,
            market_change_10s, market_change_30s, market_change_60s,
            expected_move,
            market_lag,
            edge AS signal_edge,
            combined_mid_disagreement,
            {execution_price} AS execution_price,
            {execution_edge} AS execution_edge,
            {execution_mode} AS execution_mode,
            CASE WHEN {valid_token_expr('target_token_id')} THEN 1 ELSE 0 END AS is_valid,
            CASE WHEN {valid_token_expr('target_token_id')} THEN NULL ELSE 'INVALID_TARGET_TOKEN_ID' END AS invalid_reason
        FROM ranked
        WHERE rn = 1
        ORDER BY ts_ms ASC
        """
    )
    conn.execute(
        """
        INSERT INTO cleaning_rejections(source_table, source_id, reason, detail)
        SELECT 'signals', source_signal_id, invalid_reason, token_id
        FROM clean_signals
        WHERE is_valid = 0
        """
    )
    raw = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM clean_signals").fetchone()[0]
    invalid = conn.execute("SELECT COUNT(*) FROM clean_signals WHERE is_valid = 0").fetchone()[0]
    return {"raw_signals": raw, "clean_signals": clean, "duplicate_signals_removed": raw - clean, "invalid_signal_token_rows": invalid}


def clean_orders(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "orders"):
        return {"raw_orders": 0, "clean_orders": 0}
    c = columns(conn, "orders")
    run_cols = run_cols_select(c, prefix="o.")
    exchange_order_id = qcol(c, "exchange_order_id", "NULL")
    cancel_ack_ms = qcol(c, "cancel_ack_ms", "NULL")
    raw_response = qcol(c, "raw_response", "NULL")

    exec_sql(conn, "DROP TABLE IF EXISTS clean_orders;")
    conn.execute(
        f"""
        CREATE TABLE clean_orders AS
        SELECT
            o.id AS source_order_id,
            {run_cols},
            o.ts_ms,
            datetime(o.ts_ms / 1000, 'unixepoch') || 'Z' AS ts_utc,
            o.market_id,
            o.token_id,
            UPPER(TRIM(COALESCE(o.side, ''))) AS side,
            o.price,
            o.size,
            o.status,
            o.signal_id AS source_signal_id,
            s.source_signal_id AS clean_signal_source_id,
            o.ack_ms,
            o.fill_price,
            o.filled_size,
            {exchange_order_id} AS exchange_order_id,
            {cancel_ack_ms} AS cancel_ack_ms,
            {raw_response} AS raw_response,
            CASE WHEN {valid_token_expr('o.token_id')} THEN 1 ELSE 0 END AS is_valid,
            CASE WHEN {valid_token_expr('o.token_id')} THEN NULL ELSE 'INVALID_ORDER_TOKEN_ID' END AS invalid_reason
        FROM orders o
        LEFT JOIN clean_signals s ON s.source_signal_id = o.signal_id
        ORDER BY o.ts_ms ASC
        """
    )
    conn.execute(
        """
        INSERT INTO cleaning_rejections(source_table, source_id, reason, detail)
        SELECT 'orders', source_order_id, invalid_reason, token_id
        FROM clean_orders
        WHERE is_valid = 0
        """
    )
    raw = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    clean = conn.execute("SELECT COUNT(*) FROM clean_orders").fetchone()[0]
    invalid = conn.execute("SELECT COUNT(*) FROM clean_orders WHERE is_valid = 0").fetchone()[0]
    no_signal = conn.execute("SELECT COUNT(*) FROM clean_orders WHERE source_signal_id IS NULL").fetchone()[0]
    return {"raw_orders": raw, "clean_orders": clean, "invalid_order_token_rows": invalid, "orders_without_signal": no_signal}


def build_clean_research_dataset(conn: sqlite3.Connection) -> dict[str, int]:
    exec_sql(conn, "DROP TABLE IF EXISTS clean_research_dataset;")
    if not table_exists(conn, "clean_signals"):
        conn.execute("CREATE TABLE clean_research_dataset (note TEXT)")
        return {"clean_research_dataset": 0}
    paper_exists = table_exists(conn, "paper_trades")
    paper_join_cols = """
            p.filled,
            p.fill_price AS paper_fill_price,
            p.fill_ts_ms,
            p.pnl_15s,
            p.pnl_30s,
            p.pnl_60s,
            p.pnl_120s
    """ if paper_exists else """
            NULL AS filled,
            NULL AS paper_fill_price,
            NULL AS fill_ts_ms,
            NULL AS pnl_15s,
            NULL AS pnl_30s,
            NULL AS pnl_60s,
            NULL AS pnl_120s
    """
    paper_join = "LEFT JOIN paper_trades p ON p.signal_id = s.source_signal_id" if paper_exists else ""
    conn.execute(
        f"""
        CREATE TABLE clean_research_dataset AS
        SELECT
            s.source_signal_id,
            s.run_id,
            s.match_key,
            s.market_id,
            s.token_id,
            s.side,
            s.signal_type,
            s.trigger,
            s.trigger_strength,
            s.market_state,
            s.ts_ms AS signal_ts_ms,
            s.ts_utc AS signal_ts_utc,
            s.game_time_s,
            s.game_min,
            s.fair_price,
            s.signal_edge,
            s.execution_price,
            s.execution_edge,
            s.execution_mode,
            s.expected_move,
            s.combined_mid_disagreement,
            o.source_order_id,
            o.price AS order_price,
            o.size AS order_size,
            o.status AS order_status,
            {paper_join_cols}
        FROM clean_signals s
        LEFT JOIN clean_orders o ON o.source_signal_id = s.source_signal_id
        {paper_join}
        WHERE s.is_valid = 1
        ORDER BY s.ts_ms ASC
        """
    )
    return {"clean_research_dataset": conn.execute("SELECT COUNT(*) FROM clean_research_dataset").fetchone()[0]}


def export_csvs(conn: sqlite3.Connection, out_dir: Path, tables: Iterable[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for table in tables:
        if not table_exists(conn, table):
            continue
        out_path = out_dir / f"{table}.csv"
        cur = conn.execute(f"SELECT * FROM {table}")
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([d[0] for d in cur.description])
            writer.writerows(cur.fetchall())


def print_quality_report(metrics: dict[str, int]) -> None:
    print("\nData cleaning quality report")
    print("=" * 34)
    for key in sorted(metrics):
        print(f"{key}: {metrics[key]}")


def clean(db_path: str, write_csv: bool = False, out_dir: str | None = None) -> dict[str, int]:
    db = Path(db_path)
    conn = sqlite3.connect(str(db))
    try:
        create_cleaning_rejections(conn)
        metrics: dict[str, int] = {}
        for step in [
            clean_dota_states,
            clean_market_ticks,
            build_market_match_segments,
            clean_signal_rejections,
            clean_signals,
            clean_orders,
            build_clean_research_dataset,
        ]:
            metrics.update(step(conn))
        conn.commit()

        if write_csv:
            export_csvs(
                conn,
                Path(out_dir) if out_dir else db.with_suffix("").with_name("clean_exports"),
                [
                    "clean_dota_states",
                    "clean_market_ticks",
                    "market_match_segments",
                    "clean_signal_rejections",
                    "clean_signals",
                    "clean_orders",
                    "clean_research_dataset",
                    "cleaning_rejections",
                ],
            )
        print_quality_report(metrics)
        return metrics
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="dota_poly_bot/storage/bot_data.db")
    parser.add_argument("--write-csv", action="store_true")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()
    clean(args.db, write_csv=args.write_csv, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
