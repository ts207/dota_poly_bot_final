# storage/db.py
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, Optional


class BotDatabase:
    def __init__(self, db_path: str = "dota_poly_bot/storage/bot_data.db"):
        self.db_path = db_path
        self._ensure_schema()
        self._ensure_columns()

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
                "fair_price": "REAL",
            },
        }
        with self._get_conn() as conn:
            for table, expected in migrations.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col, decl in expected.items():
                    if col not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

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
                    ts_ms, match_key, market_id, target_token_id, side, signal_type, trigger, fair_price, game_time,
                    nw_change_10s, nw_change_30s, nw_change_60s,
                    score_change_10s, score_change_30s, score_change_60s,
                    market_change_10s, market_change_30s, market_change_60s,
                    expected_move, market_lag, edge, combined_mid_disagreement, action
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), match_key, market_id, target_token_id, signal["side"],
                signal["signal_type"], signal.get("trigger"), signal.get("fair_price"), f.get("game_time", 0),
                f.get("nw_change_10s", 0), f.get("nw_change_30s", 0), f.get("nw_change_60s", 0),
                f.get("score_change_10s", 0), f.get("score_change_30s", 0), f.get("score_change_60s", 0),
                f.get("market_change_10s", 0), f.get("market_change_30s", 0), f.get("market_change_60s", 0),
                signal.get("expected_move", 0), signal.get("market_lag", 0), signal.get("edge", 0),
                f.get("combined_mid_disagreement", 0), "SIGNAL"
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
    ) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO orders (
                    ts_ms, market_id, token_id, side, price, size, status,
                    signal_id, ack_ms, fill_price, filled_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(time.time() * 1000), market_id, token_id, side, price, size, status,
                signal_id, ack_ms, fill_price, filled_size
            ))
            return int(cur.lastrowid)
