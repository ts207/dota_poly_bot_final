"""
Signal Engine — V3 (ML Scalper)

Architecture
============
1.  classify()   — label the game-state event type from raw telemetry.
2.  generate()   — gate, ML inference, edge calculation, and signal emission.

Trigger Taxonomy
================
FIGHT            NW swing + kill spike in last 60s.  Best reprice (~29s). ✅ ACTIVE
SLOW_BLEED       Gradual NW build, no kills.          Reliable but slow (~57s). ✅ ACTIVE
KILL_EVENT       Kills only, small NW change.         Inconclusive, kept on. ✅ ACTIVE
ECONOMIC_SWING   NW-only shift (Roshan, buyback).    67% stop-loss rate.    ❌ BLOCKED
LEAD_FLIP        NW lead changed hands.               High priority trade.   ✅ ACTIVE
STRUCTURAL_SWING Building destroyed.                  High priority trade.   ✅ ACTIVE
OVERREACTION     Price moved, map was quiet.          Fade the panic.        ✅ ACTIVE

Edge Window
===========
Only fire when 4% < edge <= 9%.
  - Below 4%: not worth the fill risk.
  - Above 9%: Draft Trap — model sees 99% but market is pinned at 89% for
              tail-risk reasons (scaling draft, disconnect risk). Won't reprice.

Deduplication
=============
One signal per (match_key, game_minute). Prevents hundreds of redundant
orders flooding the book for the same opportunity window.
"""
import os
import csv
import time
from typing import Dict, Any, Optional
import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


# ── trigger taxonomy ──────────────────────────────────────────────────────────

class Trigger:
    FIGHT            = "FIGHT"           # kills + NW swing
    SLOW_BLEED       = "SLOW_BLEED"      # gradual NW build, no kills
    KILL_EVENT       = "KILL_EVENT"      # kills only, small NW
    ECONOMIC_SWING   = "ECONOMIC_SWING"  # NW only (Roshan/buyback) — BLOCKED
    LEAD_FLIP        = "LEAD_FLIP"       # NW lead changed hands
    STRUCTURAL_SWING = "STRUCTURAL_SWING"# building destroyed
    OVERREACTION     = "OVERREACTION"    # price moved on quiet map


# Triggers that empirically fail to reprice Polymarket — skip entirely.
BLOCKED_TRIGGERS = frozenset({
    Trigger.ECONOMIC_SWING,  # 67% stop-loss rate in backtesting
})

# Minimum edge floor per trigger (overrides global min_edge if higher).
TRIGGER_EDGE_FLOORS: Dict[str, float] = {
    Trigger.FIGHT:            0.04,
    Trigger.SLOW_BLEED:       0.04,
    Trigger.KILL_EVENT:       0.04,
    Trigger.LEAD_FLIP:        0.06,
    Trigger.STRUCTURAL_SWING: 0.06,
    Trigger.OVERREACTION:     0.05,
    "ML_PREDICTION":          0.04,
    "M_STRONG_CONFIRM":       0.03,
    "L_STRONG_GAP":           0.03,
    "L_FIGHT_GAP":            0.04,
    "L_ECON_GAP":             0.03,
    "L_STRUCTURAL_GAP":       0.03,
    "L_LEAD_FLIP_GAP":        0.04,
}

# Max edge ceiling per trigger (Draft-Trap guard).
MAX_EDGE = 0.09


# ── engine ────────────────────────────────────────────────────────────────────

class SignalEngine:
    """
    ML-powered scalp signal engine.
    Uses XGBoost ONNX model for win probability; falls back to heuristics.
    """

    def __init__(self):
        # Market quality gates
        self.max_spread            = _env_float("SIGNAL_MAX_SPREAD", 0.04)
        self.max_mid_disagreement  = _env_float("SIGNAL_MAX_MID_DISAGREEMENT", 0.08)
        self.min_edge              = _env_float("SIGNAL_MIN_EDGE", 0.04)
        self.min_expected_move     = _env_float("SIGNAL_MIN_EXPECTED_MOVE", 0.025)

        # Heuristic weights (used when ONNX model unavailable)
        self.lead_60s_weight  = _env_float("SIGNAL_LEAD_60S_WEIGHT", 0.000012)
        self.lead_30s_weight  = _env_float("SIGNAL_LEAD_30S_WEIGHT", 0.000006)
        self.lead_10s_weight  = _env_float("SIGNAL_LEAD_10S_WEIGHT", 0.000003)
        self.score_60s_weight = _env_float("SIGNAL_SCORE_60S_WEIGHT", 0.010)
        self.score_30s_weight = _env_float("SIGNAL_SCORE_30S_WEIGHT", 0.005)
        self.max_expected_move = _env_float("SIGNAL_MAX_EXPECTED_MOVE", 0.25)

        # Dedup state: match_key → (game_minute, last_fair_price)
        self._last_signal_state: Dict[str, tuple] = {}

        # Load ONNX model
        model_path = os.path.join(os.path.dirname(__file__), "../research/dota_xgboost.onnx")
        self.ort_session = None
        if ort and os.path.exists(model_path):
            try:
                self.ort_session = ort.InferenceSession(model_path)
                self._ort_input = self.ort_session.get_inputs()[0].name
                print("[SignalEngine] XGBoost ONNX model loaded.")
            except Exception as e:
                print(f"[SignalEngine] ONNX load failed: {e}")
        
        self.shadow_log_path = "data/shadow_signals.csv"
        self._init_shadow_log()

    def _init_shadow_log(self):
        if not os.path.exists(self.shadow_log_path):
            os.makedirs("data", exist_ok=True)
            with open(self.shadow_log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["ts", "game_time", "trigger", "side", "token_id", "nw_diff", "mid", "fair", "edge", "action"])

    def _log_shadow(self, game_time, trigger, side, token_id, nw_diff, mid, fair, edge, action):
        with open(self.shadow_log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([time.time(), game_time, trigger, side, token_id, nw_diff, mid, fair, edge, action])

    def classify(self, f: Dict[str, Any]) -> str:
        """Label this game-state snapshot with a trigger type."""
        score_60   = abs(float(f.get("score_change_60s", 0.0)))
        nw_60      = abs(float(f.get("nw_change_60s", 0.0)))
        bldg       = int(f.get("building_change_60s", 0))
        game_min   = float(f.get("game_time", 0.0)) / 60.0
        market_60  = abs(float(f.get("market_change_60s", 0.0)))

        # Dynamic NW threshold: 2,000 at 15 min, +100/min thereafter
        nw_thresh = 2000 + max(0.0, game_min - 15) * 100

        # ── 3. Stricter Latency & Momentum Taxonomy ──
        score_10s_raw = float(f.get("score_change_10s", 0.0))
        nw_10s_raw = float(f.get("nw_change_10s", 0.0))
        market_10s_raw = float(f.get("market_change_10s", 0.0))
        
        score_10s = abs(score_10s_raw)
        nw_10s = abs(nw_10s_raw)
        strong_shock = score_10s >= 2 and nw_10s >= 2000
        
        shock_dir = 0
        if score_10s_raw > 0 or nw_10s_raw > 0: shock_dir = 1
        elif score_10s_raw < 0 or nw_10s_raw < 0: shock_dir = -1

        # M_STRONG_CONFIRM: Shock + Market Confirmation (1-5 cents) in same direction
        market_confirmed = (
            (shock_dir == 1 and 0.01 <= market_10s_raw <= 0.05) or
            (shock_dir == -1 and -0.05 <= market_10s_raw <= -0.01)
        )
        if strong_shock and market_confirmed:
            return "M_STRONG_CONFIRM"

        # L_STRONG_GAP: Dead Gap (Market < 1 cent)
        is_market_flat = abs(market_10s_raw) < 0.01
        if is_market_flat:
            if strong_shock:
                return "L_STRONG_GAP"
            # Fallbacks
            if score_10s >= 2: return "L_FIGHT_GAP"
            if nw_10s >= 2000: return "L_ECON_GAP"
            if bldg == 1: return "L_STRUCTURAL_GAP"
            
            # L_LEAD_FLIP_GAP
            old_lead = float(f.get("nw_diff", 0.0)) - float(f.get("nw_change_60s", 0.0))
            new_lead = float(f.get("nw_diff", 0.0))
            if old_lead * new_lead < 0 and abs(new_lead) > 2000:
                return "L_LEAD_FLIP_GAP"

        # ── 4. Traditional Taxonomy (Underreaction) ──
        old_lead = float(f.get("nw_diff", 0.0)) - float(f.get("nw_change_60s", 0.0))
        new_lead = float(f.get("nw_diff", 0.0))
        
        if market_60 >= 0.05 and score_60 == 0 and nw_60 < 1000:
            return Trigger.OVERREACTION
        
        if old_lead * new_lead < 0 and nw_60 >= nw_thresh:
            return Trigger.LEAD_FLIP

        if bldg == 1:
            return Trigger.STRUCTURAL_SWING
        if nw_60 >= nw_thresh and score_60 >= 2:
            return Trigger.FIGHT
        if nw_60 >= nw_thresh and score_60 < 2:
            return Trigger.ECONOMIC_SWING
        if score_60 >= 2:
            return Trigger.KILL_EVENT

        return Trigger.SLOW_BLEED

    def predict_win_prob(self, f: Dict[str, Any]) -> float:
        if not self.ort_session:
            return float(f.get("mid", 0.5))

        features = np.array([[
            float(f.get("game_time", 0.0)),
            float(f.get("nw_diff", 0.0)),
            float(f.get("score_diff", 0.0)),
            float(f.get("nw_change_60s", 0.0)),
            float(f.get("score_change_60s", 0.0)),
        ]], dtype=np.float32)

        pred = self.ort_session.run(None, {self._ort_input: features})
        return float(pred[1][0][1])

    def _heuristic_expected_move(self, f: Dict[str, Any]) -> float:
        move  = self.lead_60s_weight  * float(f.get("nw_change_60s", 0.0))
        move += self.lead_30s_weight  * float(f.get("nw_change_30s", 0.0))
        move += self.lead_10s_weight  * float(f.get("nw_change_10s", 0.0))
        move += self.score_60s_weight * float(f.get("score_change_60s", 0.0))
        move += self.score_30s_weight * float(f.get("score_change_30s", 0.0))

        if int(f.get("building_change_60s", 0)) == 1:
            move += 0.12 if float(f.get("nw_change_60s", 0.0)) > 0 else -0.12

        raw = max(min(move, self.max_expected_move), -self.max_expected_move)
        mid = float(f.get("mid", 0.5))
        return raw * (1.0 - mid) * 2.0 if raw > 0 else raw * mid * 2.0

    def reset_match(self, match_key: str) -> None:
        self._last_signal_state.pop(match_key, None)

    def generate(self, f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # ── 1. Quality ──
        spread = float(f.get("spread", 1.0))
        if spread > self.max_spread: return None
        if float(f.get("combined_mid_disagreement", 0.0)) > self.max_mid_disagreement: return None

        # ── 2. Dedup ──
        match_key = str(f.get("match_key", ""))
        game_minute = int(float(f.get("game_time", 0.0)) // 60)
        
        last_min, last_fair = self._last_signal_state.get(match_key, (-1, 0.0))
        # Hard lockout removed; replaced with 'Momentum Change' gate below.
        # if last_min == game_minute: return None

        # ── 3. Trigger ──
        trigger = self.classify(f)
        if trigger in BLOCKED_TRIGGERS: return None

        # ── 4. Edge ──
        mid = float(f.get("mid", 0.5))
        if self.ort_session:
            expected = self.predict_win_prob(f) - mid
            signal_type = "ML_PREDICTION"
        else:
            expected = self._heuristic_expected_move(f)
            signal_type = trigger

        # Latency Bump: If it's a DOTA_SPIKE_LATENCY, the ML model (which uses 60s features)
        # is likely underestimating the move. We add a heuristic bump.
        if trigger == "DOTA_SPIKE_LATENCY":
            bump = 0.03 if expected > 0 else -0.03
            expected += bump

        if abs(expected) < self.min_expected_move: return None

        # Executable edge calculation (Aggressive Maker Mode: Bid + 0.001)
        side = "RADIANT" if expected > 0 else "DIRE"
        raw_bid = float(f.get("radiant_best_bid" if expected > 0 else "dire_best_bid", 0.0))
        entry = max(raw_bid + 0.001, 0.01)
        fair = min(0.99, max(0.01, mid + expected if expected > 0 else (1.0 - mid) + abs(expected)))
        edge = fair - entry
        
        # ── 5. Log Shadow (Reduced Noise) ──
        edge_floor = TRIGGER_EDGE_FLOORS.get(trigger, self.min_edge)
        
        # Only log if this is a new minute/trigger/side for this match
        shadow_key = (match_key, game_minute, trigger, side)
        if not hasattr(self, "_last_shadow_keys"):
            self._last_shadow_keys = set()
        
        if shadow_key not in self._last_shadow_keys:
            token_id = f.get("radiant_token_id" if expected > 0 else "dire_token_id", "0x")
            self._log_shadow(f.get("game_time"), trigger, side, token_id, f.get("nw_diff", 0.0), 
                             mid, fair, edge, "FIRE" if edge_floor <= edge <= MAX_EDGE else "REJECT_EDGE")
            self._last_shadow_keys.add(shadow_key)
            # Cleanup old keys to prevent memory leak
            if len(self._last_shadow_keys) > 1000:
                self._last_shadow_keys.clear()

        if not (edge_floor <= edge <= MAX_EDGE):
            return None

        # Intra-minute Momentum Check:
        # If we already fired in this minute, only fire again if fair price moved > 3%
        if last_min == game_minute:
            if abs(fair - last_fair) < 0.03:
                return None

        # ── 5. Emit ──
        self._last_signal_state[match_key] = (game_minute, fair)
        return {
            "side": "BUY_RADIANT_YES" if expected > 0 else "BUY_DIRE_YES",
            "trigger": trigger,
            "signal_type": signal_type,
            "expected_move": expected,
            "fair_price": fair,
            "edge": edge,
            "entry_price_target": entry,
        }
