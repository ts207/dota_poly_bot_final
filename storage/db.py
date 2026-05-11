# storage/db.py
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, Optional


class BotDatabase:
    def __init__(self, db_path: str = "dota_poly_bot/storage/bot_data.db"):
        self.db_path = db_path
        self._ensure_schema()
        self._ensure_columns()
        self._ensure_live_probe_tables()

    def _get_conn(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        schema_path = Path(__file__).with_name("schema.sql")
        if schema_path.exists():
            with self._get_conn() as conn:
                conn.executescript(schema_path.read_text())

    def _ensure_columns(self):
        migrations = {
            "dota_ticks": {
                "server_steam_id": "TEXT",
                "partner": "INTEGER",
                "radiant_team": "TEXT",
                "dire_team": "TEXT",
            },
            "signals": {
                "target_token_id": "TEXT",
                "nw_change_10s": "REAL DEFAULT 0",
                "score_change_10s": "INTEGER DEFAULT 0",
                "score_change_30s": "INTEGER DEFAULT 0",
                "market_change_10s": "REAL DEFAULT 0",
                "market_change_30s": "REAL DEFAULT 0",
                "combined_mid_disagreement": "REAL DEFAULT 0",
                "trigger": "TEXT",
                "trigger_strength": "TEXT",
                "trigger_window": "TEXT",
                "market_state": "TEXT",
                "fair_price": "REAL",
            },
            "orders": {
                "exchange_order_id": "TEXT",
                "cancel_ack_ms": "INTEGER",
                "raw_response": "TEXT",
            },
        }
        with self._get_conn() as conn:
            for table, expected in migrations.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, decl in expected.items():
                    if col not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    def _ensure_live_probe_tables(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_order_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    signal_id INTEGER,
                    market_id TEXT,
                    token_id TEXT,
                    exchange_order_id TEXT,
                    event_type TEXT,
                    intended_price REAL,
                    intended_size REAL,
                    filled_size REAL,
                    avg_fill_price REAL,
                    remaining_size REAL,
                    ack_ms INTEGER,
                    fill_ts_ms INTEGER,
                    raw_response TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_order_events_order ON live_order_events(exchange_order_id, ts_ms)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_order_events_signal ON live_order_events(signal_id, ts_ms)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_fill_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    exchange_order_id TEXT,
                    signal_id INTEGER,
                    market_id TEXT,
                    token_id TEXT,
                    seconds_after_fill REAL,
                    best_bid REAL,
                    best_ask REAL,
                    mid REAL,
                    spread REAL,
                    bid_depth REAL,
                    ask_depth REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_live_fill_snapshots_order ON live_fill_snapshots(exchange_order_id, seconds_after_fill)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_rejections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_ms INTEGER NOT NULL,
                    match_key TEXT,
                    market_id TEXT,
                    token_id TEXT,
                    trigger TEXT,
                    trigger_strength TEXT,
                    side TEXT,
                    reason TEXT,
                    game_time REAL,
                    mid REAL,
                    spread REAL,
                    combined_mid_disagreement REAL,
                    expected_move REAL,
                    fair_price REAL,
                    edge REAL,
                    edge_floor REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_rejections_reason ON signal_rejections(reason, trigger, ts_ms)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signal_rejections_market ON signal_rejections(market_id, ts_ms)")

    @staticmethod
    def _json_dumps(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            return json.dumps(value, default=str, sort_keys=True)
        except Exception:
            return str(value)

    def log_dota_tick(self, tick: Dict[str, Any]):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO dota_ticks (
                    ts_ms, match_key, server_steam_id, partner, radiant_team, dire_team,
                    game_time, radiant_score, dire_score, radiant_nw, dire_nw,
                    nw_diff, total_nw, nw_diff_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tick["ts_ms"], tick.get("match_key"), tick.get("server_steam_id"), tick.get("partner"),
                tick.get("radiant_team"), tick.get("dire_team"), tick.get("game_time"),
                tick.get("radiant_score"), tick.get("dire_score"), tick.get("radiant_nw"), tick.get("dire_nw"),
                tick.get("nw_diff"), tick.get("total_nw"), tick.get("nw_diff_pct")
            ))

    def log_market_tick(self, market_id: str, token_id: str, book: Dict[str, Any]):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO market_ticks (
                    ts_ms, market_id, token_id, best_bid, best_ask, mid, spread, bid_depth, ask_depth
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                book["ts_ms"], market_id, token_id,
                book.get("best_bid"), book.get("best_ask"), book.get("mid"),
                book.get("spread"), book.get("bid_depth"), book.get("ask_depth")
            ))

    def log_signal(
        self,
        signal: Dict[str, Any],
        f: Dict[str, Any],
        match_key: str,
        market_id: str,
        target_token_id: Optional[str] = None,
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO signals (
                    ts_ms, match_key, market_id, target_token_id, side, signal_type, trigger, trigger_strength, trigger_window, market_state, fair_price, game_time,
                    nw_change_10s, nw_change_30s, nw_change_60s,
                    score_change_10s, score_change_30s, score_change_60s,
                    market_change_10s, market_change_30s, market_change_60s,
                    expected_move, market_lag, edge, combined_mid_disagreement, action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), match_key, market_id, target_token_id, signal["side"],
                signal["signal_type"], signal.get("trigger"), signal.get("trigger_strength"), signal.get("trigger_window"), signal.get("market_state"), signal.get("fair_price"), f.get("game_time", 0),
                f.get("nw_change_10s", 0), f.get("nw_change_30s", 0), f.get("nw_change_60s", 0),
                f.get("score_change_10s", 0), f.get("score_change_30s", 0), f.get("score_change_60s", 0),
                f.get("market_change_10s", 0), f.get("market_change_30s", 0), f.get("market_change_60s", 0),
                signal.get("expected_move", 0), signal.get("market_lag", 0), signal.get("edge", 0),
                f.get("combined_mid_disagreement", 0), "SIGNAL"
            ))
            return int(cur.lastrowid)

    def log_signal_rejection(
        self,
        *,
        rejection: Dict[str, Any],
        market_id: str,
        token_id: Optional[str] = None,
    ) -> int:
        """Log a throttled signal/execution rejection for research."""
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO signal_rejections (
                    ts_ms, match_key, market_id, token_id, trigger, trigger_strength, side, reason,
                    game_time, mid, spread, combined_mid_disagreement,
                    expected_move, fair_price, edge, edge_floor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000),
                rejection.get("match_key"),
                market_id,
                token_id,
                rejection.get("trigger"),
                rejection.get("trigger_strength"),
                rejection.get("side"),
                rejection.get("reason"),
                rejection.get("game_time"),
                rejection.get("mid"),
                rejection.get("spread"),
                rejection.get("combined_mid_disagreement"),
                rejection.get("expected_move"),
                rejection.get("fair_price"),
                rejection.get("edge"),
                rejection.get("edge_floor"),
            ))
            return int(cur.lastrowid)

    def log_order(
        self,
        market_id: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        status: str,
        signal_id: Optional[int] = None,
        ack_ms: Optional[int] = None,
        fill_price: Optional[float] = None,
        filled_size: Optional[float] = None,
        exchange_order_id: Optional[str] = None,
        cancel_ack_ms: Optional[int] = None,
        raw_response: Any = None,
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO orders (
                    ts_ms, market_id, token_id, side, price, size, status,
                    signal_id, ack_ms, fill_price, filled_size,
                    exchange_order_id, cancel_ack_ms, raw_response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), market_id, token_id, side, price, size, status,
                signal_id, ack_ms, fill_price, filled_size,
                exchange_order_id, cancel_ack_ms, self._json_dumps(raw_response)
            ))
            return int(cur.lastrowid)

    def log_live_order_event(
        self,
        *,
        event_type: str,
        market_id: str,
        token_id: str,
        exchange_order_id: Optional[str] = None,
        signal_id: Optional[int] = None,
        intended_price: Optional[float] = None,
        intended_size: Optional[float] = None,
        filled_size: Optional[float] = None,
        avg_fill_price: Optional[float] = None,
        remaining_size: Optional[float] = None,
        ack_ms: Optional[int] = None,
        fill_ts_ms: Optional[int] = None,
        raw_response: Any = None,
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO live_order_events (
                    ts_ms, signal_id, market_id, token_id, exchange_order_id, event_type,
                    intended_price, intended_size, filled_size, avg_fill_price,
                    remaining_size, ack_ms, fill_ts_ms, raw_response
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), signal_id, market_id, token_id, exchange_order_id, event_type,
                intended_price, intended_size, filled_size, avg_fill_price,
                remaining_size, ack_ms, fill_ts_ms, self._json_dumps(raw_response)
            ))
            return int(cur.lastrowid)

    def log_live_fill_snapshot(
        self,
        *,
        exchange_order_id: str,
        signal_id: Optional[int],
        market_id: str,
        token_id: str,
        seconds_after_fill: float,
        book: Dict[str, Any],
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO live_fill_snapshots (
                    ts_ms, exchange_order_id, signal_id, market_id, token_id,
                    seconds_after_fill, best_bid, best_ask, mid, spread, bid_depth, ask_depth
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), exchange_order_id, signal_id, market_id, token_id,
                seconds_after_fill, book.get("best_bid"), book.get("best_ask"), book.get("mid"),
                book.get("spread"), book.get("bid_depth"), book.get("ask_depth")
            ))
            return int(cur.lastrowid)
