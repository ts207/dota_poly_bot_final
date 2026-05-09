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
    # ML_PREDICTION used when model overrides trigger label
    "ML_PREDICTION":          0.04,
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

        # Dedup state: match_key → last fired game_minute
        self._last_signal_minute: Dict[str, int] = {}

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

    # ── classification ────────────────────────────────────────────────────────

    def classify(self, f: Dict[str, Any]) -> str:
        """Label this game-state snapshot with a trigger type."""
        score_60   = abs(float(f.get("score_change_60s", 0.0)))
        nw_60      = abs(float(f.get("nw_change_60s", 0.0)))
        bldg       = int(f.get("building_change_60s", 0))
        game_min   = float(f.get("game_time", 0.0)) / 60.0
        market_60  = abs(float(f.get("market_change_60s", 0.0)))

        # Dynamic NW threshold: 2,000 at 15 min, +100/min thereafter
        nw_thresh = 2000 + max(0.0, game_min - 15) * 100

        # Overreaction: price moved but map is quiet
        if market_60 >= 0.05 and score_60 == 0 and nw_60 < 1000:
            return Trigger.OVERREACTION

        # NW lead changed sign — biggest structural shift possible
        old_lead = float(f.get("nw_diff", 0.0)) - float(f.get("nw_change_60s", 0.0))
        new_lead = float(f.get("nw_diff", 0.0))
        if old_lead * new_lead < 0 and nw_60 >= nw_thresh:
            return Trigger.LEAD_FLIP

        # Tower / barracks destroyed
        if bldg == 1:
            return Trigger.STRUCTURAL_SWING

        # Fight: kills AND large NW swing together
        if nw_60 >= nw_thresh and score_60 >= 2:
            return Trigger.FIGHT

        # Economic swing: large NW shift, no kills (Roshan, buyback, etc.)
        if nw_60 >= nw_thresh and score_60 < 2:
            return Trigger.ECONOMIC_SWING

        # Kill event: kills but small NW change
        if score_60 >= 2:
            return Trigger.KILL_EVENT

        return Trigger.SLOW_BLEED

    # ── ML inference ─────────────────────────────────────────────────────────

    def predict_win_prob(self, f: Dict[str, Any]) -> float:
        """Run XGBoost ONNX model. Returns Radiant win probability [0, 1]."""
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
        return float(pred[1][0][1])  # class-1 (Radiant win) probability

    # ── heuristic fallback ───────────────────────────────────────────────────

    def _heuristic_expected_move(self, f: Dict[str, Any]) -> float:
        """V1 heuristic expected move, price-dampened."""
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

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def reset_match(self, match_key: str) -> None:
        """Clear dedup state when a match ends."""
        self._last_signal_minute.pop(match_key, None)

    # ── main entry point ──────────────────────────────────────────────────────

    def generate(self, f: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluate a feature snapshot and return a trade signal or None.

        Pipeline:
          1. Market quality gates  — spread, mid disagreement
          2. Deduplication gate    — one signal per game-minute per match
          3. Trigger classification — what kind of event is this?
          4. Blocked trigger gate  — skip known-bad trigger types
          5. ML / heuristic edge   — calculate expected move
          6. Edge range gate       — 4% < edge <= 9%
          7. Emit signal
        """
        # ── 1. Market quality ─────────────────────────────────────────────────
        spread = float(f.get("spread", 1.0))
        if spread > self.max_spread:
            return None
        if float(f.get("combined_mid_disagreement", 0.0)) > self.max_mid_disagreement:
            return None

        # ── 2. Deduplication ──────────────────────────────────────────────────
        match_key   = str(f.get("match_key", ""))
        game_minute = int(float(f.get("game_time", 0.0)) // 60)
        if self._last_signal_minute.get(match_key) == game_minute:
            return None

        # ── 3. Trigger classification ─────────────────────────────────────────
        trigger = self.classify(f)

        # ── 4. Blocked trigger gate ───────────────────────────────────────────
        if trigger in BLOCKED_TRIGGERS:
            return None

        # ── 5. Expected move (ML or heuristic) ───────────────────────────────
        mid = float(f.get("mid", 0.5))
        if self.ort_session:
            expected    = self.predict_win_prob(f) - mid
            signal_type = "ML_PREDICTION"
        else:
            expected    = self._heuristic_expected_move(f)
            signal_type = trigger

        edge_floor    = max(self.min_edge, TRIGGER_EDGE_FLOORS.get(signal_type, self.min_edge))
        required_edge = max(edge_floor, spread * 1.5)

        # ── 6. Build and gate signal ──────────────────────────────────────────
        def _emit(side: str, entry: float, move: float) -> Optional[Dict[str, Any]]:
            edge = abs(move)  # entry == mid, so edge == |expected|
            if edge <= required_edge or edge > MAX_EDGE:
                return None
            self._last_signal_minute[match_key] = game_minute
            return {
                "side":          side,
                "trigger":       trigger,
                "signal_type":   signal_type,
                "expected_move": move,
                "edge":          round(edge, 4),
                "target_price":  round(entry, 4),
                "game_minute":   game_minute,
            }

        if expected > self.min_expected_move:
            return _emit("BUY_RADIANT_YES", mid, expected)

        if expected < -self.min_expected_move:
            return _emit("BUY_DIRE_YES", 1.0 - mid, expected)

        return None
