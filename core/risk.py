# core/risk.py
import os
import time
from typing import Dict, Any, Tuple, Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


class RiskEngine:
    def __init__(self):
        self.max_position_per_match = _env_float("RISK_MAX_POSITION_PER_MATCH", 100.0)
        self.max_order_size = _env_float("RISK_MAX_ORDER_SIZE", 20.0)
        self.max_dota_tick_age_ms = int(_env_float("RISK_MAX_DOTA_TICK_AGE_MS", 1500))
        self.max_book_age_ms = int(_env_float("RISK_MAX_BOOK_AGE_MS", 800))
        self.max_spread = _env_float("RISK_MAX_SPREAD", 0.04)
        self.max_combined_disagreement = _env_float("RISK_MAX_COMBINED_DISAGREEMENT", 0.08)
        self.min_exit_depth = _env_float("RISK_MIN_EXIT_DEPTH", 25.0)

    def allow_trade(
        self,
        dota_tick: Dict[str, Any],
        combined_book: Dict[str, Any],
        execution_book: Dict[str, Any],
        current_exposure: float,
        now_ms: Optional[int] = None,
    ) -> Tuple[bool, str]:
        now = now_ms if now_ms is not None else int(time.time() * 1000)

        if now - int(dota_tick["ts_ms"]) > self.max_dota_tick_age_ms:
            return False, "STALE_DOTA"

        if now - int(combined_book["ts_ms"]) > self.max_book_age_ms:
            return False, "STALE_COMBINED_BOOK"

        if now - int(execution_book["ts_ms"]) > self.max_book_age_ms:
            return False, "STALE_EXECUTION_BOOK"

        if abs(current_exposure) >= self.max_position_per_match:
            return False, "EXPOSURE_LIMIT"

        if float(execution_book.get("spread", 1.0)) > self.max_spread:
            return False, "EXECUTION_SPREAD_TOO_WIDE"
            
        # Exit Liquidity Filter: Ensure there is a bid to sell into later.
        if float(execution_book.get("bid_depth", 0.0)) < self.min_exit_depth:
            return False, "INSUFFICIENT_EXIT_LIQUIDITY"

        if float(combined_book.get("combined_mid_disagreement", 0.0)) > self.max_combined_disagreement:
            return False, "TOKEN_BOOKS_DISAGREE"

        if float(execution_book.get("best_ask", 1.0)) >= 0.99:
            return False, "NO_EXECUTABLE_ASK"

        return True, "OK"

    def order_size(self, signal: Dict[str, Any], target_book: Dict[str, Any], remaining_capacity: float = None) -> float:
        """
        Determines order size based on Signal Type, Edge, and Market Health.
        
        Rules:
        - STALE_PRICE: 5-15% Small, 15%+ Small (if book healthy)
        - STRUCTURAL: 7.5-15% Normal, 15%+ Normal (if liquidity excellent)
        - FIGHT: 10-15% Normal, 15%+ Block if late or book stale
        """
        edge = float(signal.get("edge", 0.0))
        sig_type = signal.get("signal_type", "STALE_PRICE")
        
        # Calculate Market Health Score (0.0 to 1.0)
        # Based on: Freshness, Bid Presence, and Depth relative to standard order size.
        bid_depth = float(target_book.get("bid_depth", 0.0))
        health = 1.0
        if bid_depth < 50: health *= 0.5
        if float(target_book.get("spread", 1.0)) > 0.02: health *= 0.8
        
        # V3 Trigger Taxonomy sizing
        trigger = signal.get("trigger", signal.get("signal_type", "SLOW_BLEED"))
        
        if trigger == "M_STRONG_CONFIRM":
            multiplier = 1.0 * health
        elif trigger in {"LEAD_FLIP", "STRUCTURAL_SWING", "L_FIGHT_GAP", "L_LEAD_FLIP_GAP", "FIGHT"}:
            multiplier = 0.5 * health
        elif trigger in {"L_STRONG_GAP", "SLOW_BLEED", "KILL_EVENT"}:
            multiplier = 0.2 * health # Tiny size for carry/bleed
        elif trigger == "OVERREACTION":
            multiplier = 0.5 * health
        else:
            multiplier = 0.1 * health # Default safety
        elif trigger == "ML_PREDICTION":
            multiplier = 0.5 * health
        else:
            multiplier = 0.25 * health

        size = self.max_order_size * multiplier

        if remaining_capacity is not None:
            size = min(size, max(0.0, remaining_capacity))
        return round(size, 2)
