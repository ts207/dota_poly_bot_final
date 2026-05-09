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

    def order_size(self, edge: float, remaining_capacity: float = None) -> float:
        """
        Determines order size based on conviction (edge).
        - Edge >= 10%: 1.0x baseline
        - Edge < 10%: No trade (for STALE_PRICE/STRUCTURAL we keep 0.5x logic)
        - Removed 1.5x multiplier to avoid terminal fight traps.
        """
        if edge >= 0.10:
            multiplier = 1.0
        elif edge >= 0.05:
            multiplier = 0.5
        else:
            multiplier = 0.0

        size = self.max_order_size * multiplier

        if remaining_capacity is not None:
            size = min(size, max(0.0, remaining_capacity))
        return round(size, 2)
