# main.py
import asyncio
import os
import subprocess
import time
import uuid
from typing import Optional, Tuple

from dotenv import load_dotenv

from feeds.dota_fast import DotaFastFeed
from feeds.polymarket_ws import PolyMarketBook
from feeds.league_feed import league_poll_loop
from core.features import FeatureEngine
from core.signals import SignalEngine, normalize_trigger
from core.risk import RiskEngine
from core.logger import BotLogger
from core.market import combine_binary_books
from execution.order_manager import OrderManager
from execution.polymarket_client import PolymarketLiveClient
from storage.db import BotDatabase
from discovery.polymarket_gamma import (
    PolymarketGammaDiscovery,
    DiscoveredMarket,
    map_market_to_team_tokens,
    market_team_pair_hint,
)
import json
from pathlib import Path
from typing import Dict, Any

class ManualCommandListener:
    def __init__(self, cmd_file: str = "data/manual_commands.json"):
        self.cmd_file = Path(cmd_file)
        self.cmd_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.cmd_file.exists():
            self._write({})
            
    def _write(self, data):
        with open(self.cmd_file, "w") as f:
            json.dump(data, f)
            
    def check_take_profit_exits(self, match_key: str, current_mid: float, fair_price: float, db) -> list[dict]:
        """
        Scans the database for active positions (signals) in the current match
        and determines if we should 'Take Profit' or 'Exit' based on price movement.
        """
        exits = []
        try:
            # Get signals from this match that were fired in the last 60 minutes
            # (Signals don't have an 'active' flag, so we look at all recent ones)
            cur = db.cursor()
            cur.execute("""
                SELECT id, side, execution_price, fair_price, trigger 
                FROM signals 
                WHERE match_key = ? AND ts_ms > ?
            """, (match_key, int((time.time() - 3600) * 1000)))
            
            for row in cur.fetchall():
                sig_id, side, entry_p, sig_fair, trigger = row
                if not entry_p: continue
                
                # Logic A: Aggressive Take Profit (3x Gain)
                # If we bought at 0.05 and it's now 0.15, exit.
                if current_mid >= entry_p * 2.5:
                    exits.append({
                        "action": "EXIT_TAKE_PROFIT",
                        "reason": f"3x Profit reached ({entry_p} -> {current_mid})",
                        "side": side,
                        "original_signal_id": sig_id
                    })
                    continue

                # Logic B: Edge Convergence (The 'Gap' is closed)
                # If we bought because model was > market, and now market >= model, exit.
                # Only exit if we are at least in some profit (mid > entry)
                if current_mid >= fair_price and current_mid > entry_p:
                    exits.append({
                        "action": "EXIT_CONVERGENCE",
                        "reason": f"Market caught up to Model ({current_mid} >= {fair_price})",
                        "side": side,
                        "original_signal_id": sig_id
                    })

        except Exception as e:
            print(f"[ERROR] Exit logic failed: {e}")
        
        return exits
            
    def get_and_clear(self) -> Optional[Dict[str, Any]]:
        if not self.cmd_file.exists(): return None
        try:
            with open(self.cmd_file, "r") as f:
                cmd = json.load(f)
            if cmd:
                self._write({}) # Clear after reading
                return cmd
        except:
            pass
        return None

dotenv_path = os.getenv("DOTENV_PATH", ".env")
load_dotenv(dotenv_path, override=True)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def env_list_int(name: str, default: str = "0,1,2,3"):
    raw = os.getenv(name, default)
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def env_set(name: str, default: str = "") -> set[str]:
    raw = os.getenv(name, default) or ""
    return {normalize_trigger(x) for x in raw.split(",") if x.strip()}


def env_trigger_windows(name: str, default: str = "") -> dict[str, tuple[float, float]]:
    """Parse TRIGGER:min-max pairs, e.g. FIGHT_GAP:8-45,MARKET_CONFIRM:10-45."""
    raw = os.getenv(name, default) or ""
    windows: dict[str, tuple[float, float]] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part or "-" not in part:
            continue
        trigger, rng = part.split(":", 1)
        lo, hi = rng.split("-", 1)
        try:
            windows[normalize_trigger(trigger)] = (float(lo), float(hi))
        except ValueError:
            continue
    return windows


def is_placeholder(value: str) -> bool:
    v = str(value or "").strip().lower()
    return not v or "your_" in v or "polymarket_" in v or v in {"todo", "none", "null", "0"}


def is_valid_token_id(value: str) -> bool:
    v = str(value or "").strip().lower()
    return bool(v) and v not in {"0", "0x", "none", "null", "todo"} and "your_" not in v


def current_git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return os.getenv("GIT_SHA", "unknown")


def build_run_context() -> dict[str, object]:
    started_at_ts_ms = int(time.time() * 1000)
    return {
        "run_id": os.getenv("RUN_ID", f"run-{started_at_ts_ms}-{uuid.uuid4().hex[:8]}"),
        "pid": os.getpid(),
        "git_sha": current_git_sha(),
        "started_at_ts_ms": started_at_ts_ms,
    }


def token_for_rejection(rejection: Optional[dict], radiant_token_id: str, dire_token_id: str) -> Optional[str]:
    if not rejection:
        return None
    explicit = str(rejection.get("token_id") or "").strip()
    if is_valid_token_id(explicit):
        return explicit
    side = str(rejection.get("side") or "").upper()
    if "RADIANT" in side:
        return radiant_token_id if is_valid_token_id(radiant_token_id) else None
    if "DIRE" in side:
        return dire_token_id if is_valid_token_id(dire_token_id) else None
    return None


def log_startup_config(logger: BotLogger, run_context: dict[str, object], db_path: str, db: Optional[BotDatabase] = None) -> None:
    keys = [
        "ENABLE_LIVE_TRADING", "LIVE_PROBE_ONLY", "AUTO_DISCOVER_POLYMARKET",
        "ALLOW_LIVE_AUTO_DISCOVERY", "ALLOW_LIVE_ANY_DISCOVERED_MATCH",
        "TARGET_SERVER_STEAM_ID", "TARGET_RADIANT_TEAM", "TARGET_DIRE_TEAM",
        "TARGET_MATCH", "ENABLED_TRIGGERS", "BLOCKED_TRIGGERS",
        "TRIGGER_MINUTE_WINDOWS", "DATABASE_PATH",
        "RISK_MAX_DOTA_TICK_AGE_MS", "RISK_MAX_BOOK_AGE_MS",
        "RISK_MAX_SPREAD", "RISK_MAX_COMBINED_DISAGREEMENT",
        "SIGNAL_MIN_EDGE", "SIGNAL_MAX_SPREAD", "SIGNAL_MIN_EXPECTED_MOVE",
    ]
    logger.info(
        "Run context: "
        f"run_id={run_context.get('run_id')} pid={run_context.get('pid')} "
        f"git_sha={run_context.get('git_sha')} started_at_ts_ms={run_context.get('started_at_ts_ms')}"
    )
    logger.info(f"Database path: {db_path}")

    default_enabled_triggers = "FIGHT_GAP,LEAD_FLIP_GAP,MARKET_CONFIRM,STRUCTURE_GAP,KILL_UNSEEN,NW_SURGE,OVERREACTION"
    env_enabled = os.getenv("ENABLED_TRIGGERS", "")
    resolved_enabled = env_set("ENABLED_TRIGGERS", default_enabled_triggers)
    logger.info(
        f"CONFIG RESOLVED_ENABLED_TRIGGERS={','.join(sorted(resolved_enabled)) or 'NONE'} "
        f"(env={'set' if env_enabled else 'default'})"
    )

    for key in keys:
        logger.info(f"CONFIG {key}={os.getenv(key, '')}")

    if db:
        try:
            with db._get_conn() as conn:
                prev_runs = conn.execute(
                    "SELECT COUNT(DISTINCT run_id) FROM dota_ticks WHERE run_id IS NOT NULL AND run_id != ''"
                ).fetchone()[0]
            if prev_runs > 0:
                logger.warning(
                    f"STARTUP: Detected {prev_runs} previous run(s) in database. "
                    f"This may indicate a restart during an active match."
                )
        except Exception:
            pass


def write_discovered_target_env(
    path: str,
    market_id: str,
    radiant_token_id: str,
    dire_token_id: str,
    target_server_steam_id: str,
    radiant_team: str,
    dire_team: str,
    logger: BotLogger,
) -> None:
    """Write the currently discovered safe target mapping for copy/paste or audit.

    This does not modify `.env`; it writes a separate file so live auto-discovery
    remains explicit and reviewable.
    """
    if not env_bool("WRITE_DISCOVERED_TARGET_ENV", True):
        return
    try:
        from pathlib import Path

        out = Path(path or "./data/last_discovered_target.env")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "# Auto-generated by dota_poly_bot_final. Review before using for live probes.\n"
            f"# discovered_at_unix={int(time.time())}\n"
            f"MARKET_ID={market_id}\n"
            f"RADIANT_TOKEN_ID={radiant_token_id}\n"
            f"DIRE_TOKEN_ID={dire_token_id}\n"
            f"TARGET_SERVER_STEAM_ID={target_server_steam_id}\n"
            f"TARGET_RADIANT_TEAM={radiant_team}\n"
            f"TARGET_DIRE_TEAM={dire_team}\n",
            encoding="utf-8",
        )
        logger.info(f"Wrote discovered target mapping to {out}")
    except Exception as e:
        logger.error(f"Failed to write discovered target mapping: {e}")


class SeriesSupervisor:
    """Manages continuous Polymarket Dota 2 market discovery and state syncing.
    
    Handles map transitions (e.g. Game 1 -> Game 2) and team side swaps.
    """
    def __init__(self, dota_feed: DotaFastFeed, logger: BotLogger, db: BotDatabase):
        self.dota_feed = dota_feed
        self.logger = logger
        self.db = db
        self.disc = PolymarketGammaDiscovery()
        
        self.market_id = ""
        self.radiant_token_id = ""
        self.dire_token_id = ""
        
        self._last_map_number: Optional[int] = None
        self._current_market: Optional[DiscoveredMarket] = None
        
        # Target configuration
        self.target_match = os.getenv("TARGET_MATCH", "").strip()
        self.target_radiant_team = os.getenv("TARGET_RADIANT_TEAM", "").strip()
        self.target_dire_team = os.getenv("TARGET_DIRE_TEAM", "").strip()
        
        # Explicit overrides
        self.env_market_id = os.getenv("MARKET_ID", "").strip()
        if is_placeholder(self.env_market_id):
            self.env_market_id = ""
        self.auto_discover = env_bool("AUTO_DISCOVER_POLYMARKET", True) or not self.env_market_id

    async def sync_state(self) -> Tuple[bool, bool]:
        """Sync market discovery and alignment. Returns (is_active, map_changed)."""
        if not self.auto_discover and self.env_market_id:
            if not self.market_id:
                self.market_id = self.env_market_id
                self.radiant_token_id = os.getenv("RADIANT_TOKEN_ID", "").strip()
                self.dire_token_id = os.getenv("DIRE_TOKEN_ID", "").strip()
                self.logger.info(f"Supervisor: Using explicit market {self.market_id}")
            
            # CRITICAL: Always align sides even with manual IDs to handle lobby swaps
            await self._align_sides()
            return bool(self.market_id and self.radiant_token_id and self.dire_token_id), False

        map_num = int(os.getenv("MAP_NUMBER_OVERRIDE", self.dota_feed.current_map_number))
        map_changed = False
        if map_num != self._last_map_number or not self.market_id:
            await self._discover(map_num)
            map_changed = True
        else:
            await self._align_sides()
            
        return bool(self.market_id and self.radiant_token_id and self.dire_token_id), map_changed

    async def _discover(self, map_num: int):
        self.logger.info(f"Supervisor: Searching for Map {map_num} market...")
        try:
            markets = await self.disc.search_dota_markets()
        except Exception as e:
            self.logger.error(f"Supervisor discovery error: {e}")
            return

        if not markets:
            if int(time.time()) % 60 == 0:
                self.logger.warning("Supervisor: No active Dota markets found via Gamma API.")
            return

        chosen = self.disc.choose_market(
            markets, 
            self.target_radiant_team, 
            self.target_dire_team, 
            self.target_match,
            target_game_number=map_num
        )
        
        # Fallback for series where game number isn't in market title
        if not chosen and map_num > 1:
            chosen = self.disc.choose_market(markets, self.target_radiant_team, self.target_dire_team, self.target_match)

        if chosen:
            self._current_market, mapping = chosen
            self.market_id = mapping["MARKET_ID"]
            self.radiant_token_id = mapping["RADIANT_TOKEN_ID"]
            self.dire_token_id = mapping["DIRE_TOKEN_ID"]
            self._last_map_number = map_num
            self.logger.info(f"Supervisor: Discovered market {self.market_id} for Map {map_num}")
            
            # Align immediately if feed has teams
            await self._align_sides()
            
            # Try to help dota_feed find the server if it's still generic
            if not self.dota_feed.target_server_steam_id:
                team_a, team_b = market_team_pair_hint(self._current_market)
                game = await self.dota_feed.find_live_game_by_team_pair(team_a, team_b)
                if game:
                    self.logger.info(f"Supervisor: Auto-aligned Dota server to {game.get('server_steam_id')}")
                    self.dota_feed.set_target_server(str(game.get("server_steam_id") or ""))

    async def _align_sides(self):
        if not self._current_market or not self.dota_feed.latest:
            return
            
        tick = self.dota_feed.latest
        actual_r = tick["radiant_team"]
        actual_d = tick["dire_team"]
        
        aligned = map_market_to_team_tokens(self._current_market, actual_r, actual_d)
        if aligned:
            if aligned["RADIANT_TOKEN_ID"] != self.radiant_token_id or aligned["DIRE_TOKEN_ID"] != self.dire_token_id:
                self.logger.info(f"Supervisor: Side swap/re-alignment! Radiant={actual_r}, Dire={actual_d}")
                self.radiant_token_id = aligned["RADIANT_TOKEN_ID"]
                self.dire_token_id = aligned["DIRE_TOKEN_ID"]


async def dota_loop(feed: DotaFastFeed, features: FeatureEngine, db: BotDatabase, logger: BotLogger):
    logger.info("Starting Dota loop...")
    first_tick_logged = False
    while True:
        try:
            tick = await feed.fetch_once()
            if tick:
                game_time_s = float(tick.get("game_time", 0) or 0)
                if not first_tick_logged:
                    first_tick_logged = True
                    game_min = game_time_s / 60.0
                    if game_min > 5.0:
                        logger.warning(
                            f"LATE JOIN: First Dota tick at game_time={game_min:.1f}m. "
                            f"Missed first {game_min:.1f} minutes. Feature windows will be incomplete "
                            f"and early-game signals will be unreliable."
                        )
                    else:
                        logger.info(f"First Dota tick at game_time={game_min:.1f}m")
                features.add_dota(tick)
                db.log_dota_tick(tick)
        except Exception as e:
            logger.error(f"Dota feed error: {e}")
            import traceback
            traceback.print_exc()
        await asyncio.sleep(feed.poll_interval)


async def strategy_loop(
    dota_feed: DotaFastFeed,
    poly_book: PolyMarketBook,
    features: FeatureEngine,
    signal_engine: SignalEngine,
    risk: RiskEngine,
    orders: OrderManager,
    db: BotDatabase,
    logger: BotLogger,
    supervisor: SeriesSupervisor,
):
    logger.info("Starting Strategy loop with SeriesSupervisor...")

    default_enabled_triggers = "FIGHT_GAP,LEAD_FLIP_GAP,MARKET_CONFIRM,STRUCTURE_GAP,KILL_UNSEEN,NW_SURGE,OVERREACTION"
    default_trigger_windows = "FIGHT_GAP:8-45,LEAD_FLIP_GAP:12-40,MARKET_CONFIRM:10-45,STRUCTURE_GAP:10-45,KILL_UNSEEN:8-45,NW_SURGE:15-45,OVERREACTION:5-45"
    enabled_triggers = env_set("ENABLED_TRIGGERS", default_enabled_triggers)
    blocked_triggers = env_set("BLOCKED_TRIGGERS", "")
    trigger_windows = env_trigger_windows("TRIGGER_MINUTE_WINDOWS", default_trigger_windows)

    logger.info(f"Enabled triggers: {','.join(sorted(enabled_triggers)) or 'NONE'}")
    logger.info(f"Blocked triggers: {','.join(sorted(blocked_triggers)) or 'NONE'}")
    if trigger_windows:
        window_desc = ", ".join(f"{k}:{v[0]:g}-{v[1]:g}m" for k, v in sorted(trigger_windows.items()))
        logger.info(f"Trigger minute windows: {window_desc}")

    all_known_triggers = {
        "FIGHT_GAP", "LEAD_FLIP_GAP", "STRUCTURE_GAP", "MARKET_CONFIRM",
        "FIGHT_EVENT", "LEAD_FLIP_EVENT", "STRUCTURE_EVENT", "OVERREACTION", "SLOW_BLEED",
        "KILL_UNSEEN", "NW_SURGE",
    }
    unknown = enabled_triggers - all_known_triggers
    if unknown:
        logger.warning(f"ENABLED_TRIGGERS contains unknown triggers: {unknown}")
    missing_enabled = all_known_triggers - enabled_triggers - blocked_triggers
    if missing_enabled:
        logger.info(f"Triggers neither enabled nor blocked (won't fire): {missing_enabled}")

    db.log_run_config({
        "enabled_triggers": ",".join(sorted(enabled_triggers)),
        "blocked_triggers": ",".join(sorted(blocked_triggers)),
        "trigger_windows": str(trigger_windows),
        "signal_min_edge": float(os.getenv("SIGNAL_MIN_EDGE", "0.04")),
        "risk_max_book_age_ms": int(float(os.getenv("RISK_MAX_BOOK_AGE_MS", "800"))),
        "risk_max_dota_tick_age_ms": int(float(os.getenv("RISK_MAX_DOTA_TICK_AGE_MS", "1500"))),
        "enable_live_trading": os.getenv("ENABLE_LIVE_TRADING", "false"),
        "auto_discover": os.getenv("AUTO_DISCOVER_POLYMARKET", "true"),
        "target_server_steam_id": os.getenv("TARGET_SERVER_STEAM_ID", ""),
        "target_radiant_team": os.getenv("TARGET_RADIANT_TEAM", ""),
        "target_dire_team": os.getenv("TARGET_DIRE_TEAM", ""),
        "map_number_override": os.getenv("MAP_NUMBER_OVERRIDE", ""),
    })

    cmd_listener = ManualCommandListener()
    last_logged_m_ts: dict[tuple[str, str], int] = {}
    _first_dota_tick_ts: Optional[int] = None
    _data_gap_logged = False

    while True:
        try:
            # Sync supervisor state
            is_active, map_changed = await supervisor.sync_state()
            if not is_active:
                if int(time.time()) % 15 == 0:
                    has_dota = dota_feed.latest is not None
                    print(
                        f"Strategy: Waiting for active market discovery... "
                        f"(Dota connected={has_dota}, market_id={supervisor.market_id or 'none'})"
                    )
                await asyncio.sleep(2.0)
                continue
            
            if map_changed:
                logger.info("Supervisor: Map changed detected. Resetting feature and signal engines.")
                features.reset()
                if hasattr(dota_feed.latest, "get"):
                    signal_engine.reset_match(dota_feed.latest.get("match_key", ""))
            
            market_id = supervisor.market_id
            radiant_token_id = supervisor.radiant_token_id
            dire_token_id = supervisor.dire_token_id

            if not (is_valid_token_id(radiant_token_id) and is_valid_token_id(dire_token_id)):
                logger.info(
                    "Strategy: Waiting for valid token mapping "
                    f"radiant_token_id={radiant_token_id!r} dire_token_id={dire_token_id!r}"
                )
                await asyncio.sleep(2.0)
                continue
            
            # Ensure PolyMarketBook is tracking current tokens
            await poly_book.update_assets([radiant_token_id, dire_token_id])
            
            # Ensure OrderManager knows current market
            if orders.market_id != market_id:
                orders.market_id = market_id

            dota_tick = dota_feed.latest
            radiant_book = poly_book.get_book(radiant_token_id)
            dire_book = poly_book.get_book(dire_token_id)

            if dota_tick and _first_dota_tick_ts is None:
                _first_dota_tick_ts = int(dota_tick.get("ts_ms", 0) or 0)
            if dota_tick and not _data_gap_logged and radiant_book and dire_book:
                book_ts = int(radiant_book.get("ts_ms", 0) or 0)
                if _first_dota_tick_ts and book_ts:
                    gap_s = (book_ts - _first_dota_tick_ts) / 1000.0
                    if gap_s > 60:
                        logger.warning(
                            f"DATA GAP: {gap_s:.0f}s ({gap_s/60:.1f}m) between first Dota tick "
                            f"and first market book. No signals could fire during this window."
                        )
                _data_gap_logged = True

            if not dota_tick or not radiant_book or not dire_book:
                if int(time.time()) % 10 == 0:
                    missing = []
                    if not dota_tick:
                        missing.append("Dota")
                    if not radiant_book:
                        missing.append("RadiantBook")
                    if not dire_book:
                        missing.append("DireBook")
                    print(
                        "Strategy: Waiting for data... "
                        + " ".join(f"{m}={False}" for m in missing)
                    )
                await asyncio.sleep(1.0)
                continue

            _game_time_now = float(dota_tick.get("game_time", 0) or 0)
            if not hasattr(strategy_loop, "_late_join_logged") and _game_time_now > 600:
                logger.warning(
                    f"LATE JOIN: Strategy active at game_time={_game_time_now/60:.1f}m. "
                    f"Market may already reflect current game state; signal edge may be reduced."
                )
                strategy_loop._late_join_logged = True

            combined_book = combine_binary_books(radiant_book, dire_book)

            # Only log market ticks when the timestamp advances for this market/token.
            for tid, book in [(radiant_token_id, radiant_book), (dire_token_id, dire_book), ("COMBINED_RADIANT", combined_book)]:
                key = (market_id, str(tid))
                last_ts = last_logged_m_ts.get(key, 0)
                curr_ts = int(book.get("ts_ms", 0) or 0)
                if curr_ts > last_ts:
                    db.log_market_tick(market_id, tid, book)
                    last_logged_m_ts[key] = curr_ts

            features.add_market(combined_book)
            f = features.compute(dota_tick, combined_book)
            if not f:
                if int(time.time()) % 10 == 0:
                    print("Strategy: Processing... (Feature window filling)")
                await asyncio.sleep(1.0)
                continue

            # Inject mapping context for auditing/cleaning
            f["market_id"] = market_id
            f["radiant_token_id"] = radiant_token_id
            f["dire_token_id"] = dire_token_id

            if int(time.time()) % 5 == 0:
                print(
                    f"Strategy: Active | Time={int(dota_tick['game_time']//60)}m "
                    f"| CombinedMid={f['mid']:.3f} | Lead={f['nw_diff']:.0f} "
                    f"| Disagree={f['combined_mid_disagreement']:.3f}"
                )

            # ── 4. Manual Commands & Auto Exits ──
            manual_cmd = cmd_listener.get_and_clear()
            if manual_cmd:
                action = manual_cmd.get("action")
                logger.info(f"MANUAL COMMAND RECEIVED: {action}")
                if action == "FORCE_EXIT":
                    await orders.cancel_all()
                    logger.warning("MANUAL: Position exit command processed.")
                    continue
                elif action in ("FORCE_BUY_RADIANT", "FORCE_BUY_DIRE"):
                    side = "BUY_RADIANT_YES" if action == "FORCE_BUY_RADIANT" else "BUY_DIRE_YES"
                    signal = {
                        "side": side,
                        "trigger": "MANUAL_OVERRIDE",
                        "trigger_strength": "STRONG",
                        "expected_move": 0.50,
                        "fair_price": 0.95 if side == "BUY_RADIANT_YES" else 0.05,
                        "edge": 0.20,
                        "signal_type": "MANUAL",
                        "is_manual": True
                    }
                    logger.warning(f"MANUAL: Injecting {side} signal!")

            # Check for Automated Exits (Take Profit)
            if not signal:
                # Calculate current probability for exit checking
                fair_prob = signal_engine.predict_win_prob(f) if signal_engine.ort_session else f["mid"]
                auto_exits = cmd_listener.check_take_profit_exits(
                    f.get("match_key", ""), 
                    f["mid"], 
                    fair_prob,
                    db
                )
                if auto_exits:
                    exit_sig = auto_exits[0]
                    logger.info(f"[STRATEGY] Auto-Exit Triggered: {exit_sig['reason']}")
                    # Fire a 'SELL' or 'REVERSE' signal for the strategy to process
                    signal = {
                        "side": "EXIT",
                        "trigger": exit_sig["action"],
                        "reason": exit_sig["reason"],
                        "target_signal_id": exit_sig["original_signal_id"]
                    }

            if not signal:
                signal = signal_engine.generate(f, has_open_orders=bool(orders.open_orders))

            if not signal:
                rejection = getattr(signal_engine, "last_rejection", None)
                if rejection and rejection.get("should_log") and env_bool("LOG_SIGNAL_REJECTIONS", True):
                    db.log_signal_rejection(
                        rejection=rejection,
                        market_id=market_id,
                        token_id=token_for_rejection(rejection, radiant_token_id, dire_token_id),
                    )

            if signal:
                if signal["side"] == "EXIT":
                    logger.warning(f"EXECUTION: Closing position due to {signal['reason']}")
                    # In this dry-run / simplified setup, we log it and cancel orders.
                    # A live implementation would place a SELL order here.
                    await orders.cancel_all()
                    continue

                target_token_id = radiant_token_id if signal["side"] == "BUY_RADIANT_YES" else dire_token_id
                target_book = radiant_book if target_token_id == radiant_token_id else dire_book

                if not is_valid_token_id(target_token_id):
                    logger.info("Execution blocked: MISSING_TARGET_TOKEN_ID")
                    if env_bool("LOG_SIGNAL_REJECTIONS", True):
                        db.log_signal_rejection(
                            rejection={
                                "match_key": f.get("match_key"),
                                "trigger": signal.get("trigger"),
                                "trigger_strength": signal.get("trigger_strength"),
                                "side": signal.get("side"),
                                "reason": "MISSING_TARGET_TOKEN_ID",
                                "game_time": f.get("game_time"),
                                "mid": f.get("mid"),
                                "spread": target_book.get("spread") if target_book else None,
                                "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                "expected_move": signal.get("expected_move"),
                                "fair_price": signal.get("fair_price"),
                                "edge": signal.get("edge"),
                                "edge_floor": None,
                            },
                            market_id=market_id,
                            token_id=None,
                        )
                    continue

                current_exposure = orders.get_open_exposure()
                allowed, reason = risk.allow_trade(dota_tick, combined_book, target_book, current_exposure)
                if not allowed:
                    logger.info(f"Risk blocked trade: {reason}")
                    if env_bool("LOG_SIGNAL_REJECTIONS", True):
                        db.log_signal_rejection(
                            rejection={
                                "match_key": f.get("match_key"),
                                "trigger": signal.get("trigger"),
                                "trigger_strength": signal.get("trigger_strength"),
                                "side": signal.get("side"),
                                "reason": f"RISK_{reason}",
                                "game_time": f.get("game_time"),
                                "mid": f.get("mid"),
                                "spread": target_book.get("spread"),
                                "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                "expected_move": signal.get("expected_move"),
                                "fair_price": signal.get("fair_price"),
                                "edge": signal.get("edge"),
                                "edge_floor": None,
                            },
                            market_id=market_id,
                            token_id=target_token_id,
                        )
                else:
                    remaining_capacity = max(0.0, risk.max_position_per_match - current_exposure)
                    size = risk.order_size(signal, target_book, remaining_capacity=remaining_capacity)
                    if size <= 0:
                        logger.info("Risk blocked trade: ZERO_SIZE_OR_HEALTH_GATE")
                        if env_bool("LOG_SIGNAL_REJECTIONS", True):
                            db.log_signal_rejection(
                                rejection={
                                    "match_key": f.get("match_key"),
                                    "trigger": signal.get("trigger"),
                                    "trigger_strength": signal.get("trigger_strength"),
                                    "side": signal.get("side"),
                                    "reason": "ZERO_SIZE_OR_HEALTH_GATE",
                                    "game_time": f.get("game_time"),
                                    "mid": f.get("mid"),
                                    "spread": target_book.get("spread"),
                                    "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                    "expected_move": signal.get("expected_move"),
                                    "fair_price": signal.get("fair_price"),
                                    "edge": signal.get("edge"),
                                    "edge_floor": None,
                                },
                                market_id=market_id,
                                token_id=target_token_id,
                            )
                    else:
                        # Hybrid Pricing: Taker for Momentum, Maker for Gaps
                        trigger = signal.get("trigger", "SLOW_BLEED")
                        fair = float(signal.get("fair_price", 0.5))
                        bid = float(target_book["best_bid"])
                        ask = float(target_book["best_ask"])

                        trigger = normalize_trigger(signal.get("trigger"))
                        game_minute = float(f.get("game_time", 0.0)) / 60.0

                        if trigger in blocked_triggers:
                            logger.info(f"Execution blocked: BLOCKED_TRIGGER ({trigger})")
                            if env_bool("LOG_SIGNAL_REJECTIONS", True):
                                db.log_signal_rejection(
                                    rejection={
                                        "match_key": f.get("match_key"), "trigger": trigger, "trigger_strength": signal.get("trigger_strength"), "side": signal.get("side"),
                                        "reason": "EXEC_BLOCKED_TRIGGER", "game_time": f.get("game_time"),
                                        "mid": f.get("mid"), "spread": target_book.get("spread"),
                                        "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                        "expected_move": signal.get("expected_move"), "fair_price": fair,
                                        "edge": signal.get("edge"), "edge_floor": None,
                                    },
                                    market_id=market_id, token_id=target_token_id,
                                )
                            continue

                        if trigger not in enabled_triggers:
                            logger.info(f"Execution blocked: DISABLED_OR_UNKNOWN_TRIGGER ({trigger})")
                            if env_bool("LOG_SIGNAL_REJECTIONS", True):
                                db.log_signal_rejection(
                                    rejection={
                                        "match_key": f.get("match_key"), "trigger": trigger, "trigger_strength": signal.get("trigger_strength"), "side": signal.get("side"),
                                        "reason": "DISABLED_OR_UNKNOWN_TRIGGER", "game_time": f.get("game_time"),
                                        "mid": f.get("mid"), "spread": target_book.get("spread"),
                                        "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                        "expected_move": signal.get("expected_move"), "fair_price": fair,
                                        "edge": signal.get("edge"), "edge_floor": None,
                                    },
                                    market_id=market_id, token_id=target_token_id,
                                )
                            continue

                        if trigger in trigger_windows:
                            min_minute, max_minute = trigger_windows[trigger]
                            if not (min_minute <= game_minute <= max_minute):
                                logger.info(
                                    f"Execution blocked: TRIGGER_OUTSIDE_MINUTE_WINDOW "
                                    f"({trigger} game_min={game_minute:.1f} allowed={min_minute:g}-{max_minute:g})"
                                )
                                if env_bool("LOG_SIGNAL_REJECTIONS", True):
                                    db.log_signal_rejection(
                                        rejection={
                                            "match_key": f.get("match_key"), "trigger": trigger, "trigger_strength": signal.get("trigger_strength"), "side": signal.get("side"),
                                            "reason": "TRIGGER_OUTSIDE_MINUTE_WINDOW", "game_time": f.get("game_time"),
                                            "mid": f.get("mid"), "spread": target_book.get("spread"),
                                            "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                            "expected_move": signal.get("expected_move"), "fair_price": fair,
                                            "edge": signal.get("edge"), "edge_floor": None,
                                        },
                                        market_id=market_id, token_id=target_token_id,
                                    )
                                continue

                        # Taker for event triggers (fill in the 4s latency window),
                        # maker for drift/trend triggers (wait for price to come to us).
                        TAKER_TRIGGERS = {"FIGHT_GAP", "LEAD_FLIP_GAP", "STRUCTURE_GAP", "MARKET_CONFIRM", "KILL_UNSEEN", "OVERREACTION"}
                        if trigger in TAKER_TRIGGERS:
                            # Cross the spread: place at ask + 1 tick to take immediately.
                            # Orders are cancelled in 1s if unfilled, so we only fill against
                            # stale quotes — not against a market that's already repriced.
                            price = min(ask + 0.001, 0.97)
                            mode = f"TAKER_{trigger}"
                        else:
                            # Maker: join the bid and wait for a taker to come to us.
                            price = min(bid + 0.001, ask - 0.001)
                            mode = f"MAKER_{trigger}"

                        exec_edge = fair - price
                        # Taker pays spread so allow slightly tighter floor (2c vs 3c).
                        edge_floor = 0.02 if trigger in TAKER_TRIGGERS else 0.03
                        if exec_edge < edge_floor:
                            label = "TAKER_EDGE_TOO_SMALL" if trigger in TAKER_TRIGGERS else "MAKER_EDGE_TOO_SMALL"
                            logger.info(f"Execution blocked: {label} (Edge={exec_edge:.4f}, Fair={fair:.4f}, Price={price:.4f})")
                            if env_bool("LOG_SIGNAL_REJECTIONS", True):
                                db.log_signal_rejection(
                                    rejection={
                                        "match_key": f.get("match_key"), "trigger": trigger, "trigger_strength": signal.get("trigger_strength"), "side": signal.get("side"),
                                        "reason": label, "game_time": f.get("game_time"),
                                        "mid": f.get("mid"), "spread": target_book.get("spread"),
                                        "combined_mid_disagreement": f.get("combined_mid_disagreement"),
                                        "expected_move": signal.get("expected_move"), "fair_price": fair,
                                        "edge": exec_edge, "edge_floor": edge_floor,
                                    },
                                    market_id=market_id, token_id=target_token_id,
                                )
                            continue

                        logger.signal(
                            f"{signal['side']} | {mode} | Strength={signal.get('trigger_strength')} | Edge={exec_edge:.4f} "
                            f"| Fair={fair:.4f} | Price={price:.4f} "
                            f"| Snowball={signal.get('is_snowball_regime')}"
                        )
                        if env_bool("ENABLE_LIVE_TRADING", False):
                            size = min(size, float(os.getenv("LIVE_MAX_ORDER_SIZE", "1.00")))

                        signal["execution_price"] = price
                        signal["execution_edge"] = exec_edge
                        signal["execution_mode"] = mode
                        signal_id = db.log_signal(signal, f, dota_tick["match_key"], market_id, target_token_id=target_token_id)
                        result = await orders.buy_limit(target_token_id, price, size, signal, signal_id=signal_id)
                        # Event-based triggers: cancel quickly so fills only happen against
                        # stale quotes in the 4s window before market reprices.
                        # Model/drift triggers: give more time for the maker to fill.
                        is_event_trigger = trigger in {"FIGHT_GAP", "LEAD_FLIP_GAP", "STRUCTURE_GAP", "MARKET_CONFIRM"}
                        default_cancel = "1.0" if is_event_trigger else "2.0"
                        live_default  = "0.8" if is_event_trigger else "1.5"
                        cancel_after_s = float(os.getenv(
                            "LIVE_CANCEL_AFTER_S" if env_bool("ENABLE_LIVE_TRADING", False) else "ORDER_CANCEL_AFTER_S",
                            live_default if env_bool("ENABLE_LIVE_TRADING", False) else default_cancel,
                        ))
                        asyncio.create_task(orders.cancel_after(result["id"], seconds=cancel_after_s))

            await asyncio.sleep(0.1)
        except Exception as e:
            import traceback
            logger.error(f"Strategy loop error: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(2.0)


async def main():
    steam_key = os.getenv("STEAM_API_KEY")
    if not steam_key or is_placeholder(steam_key):
        print("Error: STEAM_API_KEY not found in .env")
        return

    logger = BotLogger()
    run_context = build_run_context()
    os.environ.setdefault("RUN_ID", str(run_context["run_id"]))
    db_path = os.getenv("DATABASE_PATH", "dota_poly_bot/storage/bot_data.db")
    db = BotDatabase(db_path, run_context=run_context)
    log_startup_config(logger, run_context, db_path, db=db)

    target_match = os.getenv("TARGET_MATCH", "").strip()
    target_radiant_team = os.getenv("TARGET_RADIANT_TEAM", "").strip()
    target_dire_team = os.getenv("TARGET_DIRE_TEAM", "").strip()
    target_server_steam_id = os.getenv("TARGET_SERVER_STEAM_ID", "").strip()

    dota_feed = DotaFastFeed(
        steam_key,
        target_match_name=target_match,
        target_radiant_team=target_radiant_team,
        target_dire_team=target_dire_team,
        target_server_steam_id=target_server_steam_id,
        poll_interval=float(os.getenv("DOTA_POLL_INTERVAL", "1.0")),
        partners=env_list_int("DOTA_PARTNERS", "0,1,2,3"),
    )

    supervisor = SeriesSupervisor(dota_feed, logger, db)
    
    # Initial sync attempt to populate IDs for initialization
    _, _ = await supervisor.sync_state()

    market_id = supervisor.market_id
    radiant_token_id = supervisor.radiant_token_id
    dire_token_id = supervisor.dire_token_id

    # If we have discovered something, write it for audit
    if market_id and radiant_token_id and dire_token_id:
        target_server_steam_id = str(getattr(dota_feed, "target_server_steam_id", "") or target_server_steam_id).strip()
        write_discovered_target_env(
            os.getenv("DISCOVERED_TARGET_ENV_PATH", "./data/last_discovered_target.env"),
            market_id,
            radiant_token_id,
            dire_token_id,
            target_server_steam_id,
            supervisor.target_radiant_team,
            supervisor.target_dire_team,
            logger,
        )

    poly_book = PolyMarketBook(
        [radiant_token_id, dire_token_id] if radiant_token_id and dire_token_id else [],
        snapshot_interval_s=float(os.getenv("PM_SNAPSHOT_INTERVAL_S", "120")),
        validation_tolerance=float(os.getenv("PM_BOOK_VALIDATION_TOLERANCE", "0.01")),
    )
    features = FeatureEngine()
    signals = SignalEngine(run_context=run_context)
    risk = RiskEngine()

    enable_live = env_bool("ENABLE_LIVE_TRADING", False)
    live_probe_only = env_bool("LIVE_PROBE_ONLY", True)
    
    if enable_live:
        if not live_probe_only:
            raise RuntimeError("Refusing full live mode. Set LIVE_PROBE_ONLY=true for tiny-capital testing.")
        if env_bool("ALLOW_UNCONFIRMED_POLYMARKET_MAPPING", False):
            raise RuntimeError("Refusing live probe with ALLOW_UNCONFIRMED_POLYMARKET_MAPPING=true.")

        allow_live_auto_discovery = env_bool("ALLOW_LIVE_AUTO_DISCOVERY", False)
        if supervisor.auto_discover:
            if not allow_live_auto_discovery:
                raise RuntimeError(
                    "Refusing live probe with auto-discovered IDs unless ALLOW_LIVE_AUTO_DISCOVERY=true. "
                    "Run dry discovery first or enable the explicit live auto-discovery flag."
                )
            explicit_target_requested = bool(
                target_server_steam_id or target_match or (target_radiant_team and target_dire_team)
            )
            if not explicit_target_requested and not env_bool("ALLOW_LIVE_ANY_DISCOVERED_MATCH", False):
                raise RuntimeError(
                    "Refusing live auto-discovery without a target. Set TARGET_RADIANT_TEAM+TARGET_DIRE_TEAM, "
                    "TARGET_MATCH, TARGET_SERVER_STEAM_ID, or explicitly set ALLOW_LIVE_ANY_DISCOVERED_MATCH=true."
                )
            logger.info("LIVE AUTO-DISCOVERY ENABLED via SeriesSupervisor.")

        poly_client = PolymarketLiveClient()
        orders = OrderManager(
            poly_client=poly_client,
            dry_run=False,
            db=db,
            market_id=market_id,
            book_provider=lambda token_id: poly_book.get_book(token_id),
        )
        logger.info("LIVE PROBE MODE ENABLED: tiny real orders may be submitted.")
    else:
        orders = OrderManager(poly_client=None, dry_run=True, db=db, market_id=market_id)
        logger.info("DRY RUN MODE ENABLED.")

    league_interval = float(os.getenv("LEAGUE_POLL_INTERVAL", "10"))
    league_delay = float(os.getenv("LEAGUE_POLL_DELAY_START", "3"))

    try:
        await asyncio.gather(
            dota_loop(dota_feed, features, db, logger),
            poly_book.run(),
            league_poll_loop(interval=league_interval, delay_start=league_delay),
            strategy_loop(
                dota_feed,
                poly_book,
                features,
                signals,
                risk,
                orders,
                db,
                logger,
                supervisor,
            ),
        )
    finally:
        await dota_feed.close()
        await poly_book.close()
        await supervisor.disc.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
