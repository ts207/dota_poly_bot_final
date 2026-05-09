# core/signals.py
import os
from typing import Dict, Any, Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


class SignalEngine:
    """
    V1 signal engine using raw radiant_lead swing + score swing against a
    combined Radiant-probability market view. All weights are configurable via
    .env so collection can tune without code edits.
    """

    def __init__(self):
        self.max_spread = _env_float("SIGNAL_MAX_SPREAD", 0.04)
        self.max_mid_disagreement = _env_float("SIGNAL_MAX_MID_DISAGREEMENT", 0.08)
        self.min_depth = _env_float("SIGNAL_MIN_DEPTH", 50.0)
        self.min_edge = _env_float("SIGNAL_MIN_EDGE", 0.05)
        self.min_expected_move = _env_float("SIGNAL_MIN_EXPECTED_MOVE", 0.025)

        # Signal-specific edge floors based on historical EV
        self.type_edge_floors = {
            "STALE_PRICE": 0.05,
            "STRUCTURAL_SWING": 0.075,
            "VISIBLE_FIGHT_UNDERREACTION": 0.10,
            "LEAD_FLIP": 0.10,
            "HIDDEN_ECONOMIC_SWING": 0.10,
            "OVERREACTION_FADE": 0.10
        }

        self.lead_60s_weight = _env_float("SIGNAL_LEAD_60S_WEIGHT", 0.000012)
        self.lead_30s_weight = _env_float("SIGNAL_LEAD_30S_WEIGHT", 0.000006)
        self.lead_10s_weight = _env_float("SIGNAL_LEAD_10S_WEIGHT", 0.000003)
        self.score_60s_weight = _env_float("SIGNAL_SCORE_60S_WEIGHT", 0.010)
        self.score_30s_weight = _env_float("SIGNAL_SCORE_30S_WEIGHT", 0.005)
        self.max_expected_move = _env_float("SIGNAL_MAX_EXPECTED_MOVE", 0.25)

    def expected_price_move(self, f: Dict[str, Any]) -> float:
        """Calculate raw expected move then dampen it based on current price ceiling."""
        move = 0.0
        move += self.lead_60s_weight * float(f.get("nw_change_60s", 0.0))
        move += self.lead_30s_weight * float(f.get("nw_change_30s", 0.0))
        move += self.lead_10s_weight * float(f.get("nw_change_10s", 0.0))
        move += self.score_60s_weight * float(f.get("score_change_60s", 0.0))
        move += self.score_30s_weight * float(f.get("score_change_30s", 0.0))
        
        # Add massive expected move if a building fell (worth a lot of win prob)
        if int(f.get("building_change_60s", 0)) == 1:
            # If the gold swung in Radiant's favor, Radiant took a tower. 
            # If Dire's favor, Dire took it.
            if float(f.get("nw_change_60s", 0.0)) > 0:
                move += 0.12
            else:
                move -= 0.12

        raw_move = max(min(move, self.max_expected_move), -self.max_expected_move)
        
        # Price-aware dampening: 
        # If buying Radiant (move > 0), upside is limited by (1.0 - current_mid).
        # If buying Dire (move < 0), Radiant upside is limited by current_mid.
        mid = float(f.get("mid", 0.5))
        if raw_move > 0:
            dampened = raw_move * (1.0 - mid) * 2.0 # *2 to keep original scale at mid=0.5
        else:
            dampened = raw_move * mid * 2.0
            
        return dampened

    def classify(self, f: Dict[str, Any]) -> str:
        score_60 = abs(float(f.get("score_change_60s", 0.0)))
        lead_60 = abs(float(f.get("nw_change_60s", 0.0)))
        bldg_change = int(f.get("building_change_60s", 0))
        game_min = float(f.get("game_time", 0.0)) / 60.0
        
        # Market Overreaction: Price moved significantly but map is quiet.
        market_move_60 = float(f.get("market_change_60s", 0.0))
        if abs(market_move_60) >= 0.05 and score_60 == 0 and lead_60 < 1000:
            return "OVERREACTION_FADE"

        # Scale threshold: 2500 at 20 mins, increases as game goes on.
        base_thresh = 2000 + (max(0, game_min - 15) * 100)

        old_lead_est = float(f.get("nw_diff", 0.0)) - float(f.get("nw_change_60s", 0.0))
        new_lead = float(f.get("nw_diff", 0.0))
        
        if old_lead_est * new_lead < 0 and lead_60 >= base_thresh:
            return "LEAD_FLIP"
        if bldg_change == 1:
            return "STRUCTURAL_SWING"
        if lead_60 >= base_thresh and score_60 <= 1:
            return "HIDDEN_ECONOMIC_SWING"
        if lead_60 >= base_thresh and score_60 >= 2:
            return "VISIBLE_FIGHT_UNDERREACTION"
        return "STALE_PRICE"

    def generate(self, f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        spread = float(f.get("spread", 1.0))
        if spread > self.max_spread:
            return None
        if float(f.get("combined_mid_disagreement", 0.0)) > self.max_mid_disagreement:
            return None

        # Dynamic Edge Requirement: 
        # Demand more safety margin as the spread widens.
        required_edge = max(self.min_edge, spread * 1.5)

        expected = self.expected_price_move(f)
        mid = float(f.get("mid", 0.5))
        
        signal_type = self.classify(f)
        
        # Signal-specific minimum edge gate
        type_floor = self.type_edge_floors.get(signal_type, self.min_edge)
        
        # Terminal Fight Filter: Block hyper-aggressive fight signals in endgame 
        # because the market often freezes/locks, preventing profitable exits.
        game_time_min = float(f.get("game_time", 0.0)) / 60.0
        if signal_type == "VISIBLE_FIGHT_UNDERREACTION" and abs(expected) > 0.15 and game_time_min > 30:
            return None

        if expected > self.min_expected_move:
            # We expect a move UP for Radiant.
            target_entry = float(f.get("radiant_best_ask", 1.0))
            executable_depth = float(f.get("radiant_ask_depth", 0.0))
            if executable_depth < self.min_depth:
                return None
            
            # edge = (Fair Price) - Actual Entry Price
            edge = (mid + expected) - target_entry
            
            if edge > required_edge and edge >= type_floor:
                return {
                    "side": "BUY_RADIANT_YES",
                    "signal_type": signal_type,
                    "expected_move": expected,
                    "market_lag": expected - (target_entry - mid),
                    "edge": edge,
                }

        if expected < -self.min_expected_move:
            # We expect a move DOWN for Radiant (UP for Dire).
            target_entry = float(f.get("dire_best_ask", 1.0))
            executable_depth = float(f.get("dire_ask_depth", 0.0))
            if executable_depth < self.min_depth:
                return None

            dire_mid = 1.0 - mid
            dire_expected = abs(expected)
            
            edge = (dire_mid + dire_expected) - target_entry
            
            if edge > required_edge and edge >= type_floor:
                return {
                    "side": "BUY_DIRE_YES",
                    "signal_type": signal_type,
                    "expected_move": expected,
                    "market_lag": dire_expected - (target_entry - dire_mid),
                    "edge": edge,
                }

        return None
