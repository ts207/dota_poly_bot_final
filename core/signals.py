"""
Signal Engine — simplified trigger taxonomy.

Core execution triggers
=======================
FIGHT_GAP       Fight/kill shock while market is flat. Strength distinguishes STRONG vs NORMAL.
LEAD_FLIP_GAP   Radiant-lead sign flipped while market is flat.
STRUCTURE_GAP   Building-state changed while market is flat.
MARKET_CONFIRM  Strong Dota shock and market has started confirming, but may not be finished.

Research/non-execution labels
=============================
FIGHT_EVENT, LEAD_FLIP_EVENT, STRUCTURE_EVENT, OVERREACTION, SLOW_BLEED.

Design
======
trigger = event family
trigger_strength = NORMAL / STRONG
trigger_window = 10s / 60s
market_state = FLAT / CONFIRMING / MOVED / QUIET
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




# ── trigger normalization ─────────────────────────────────────────────────────

TRIGGER_ALIASES = {
    # Old latency names -> simplified execution taxonomy.
    "L_STRONG_GAP": "FIGHT_GAP",
    "L_FIGHT_GAP": "FIGHT_GAP",
    "L_LEAD_FLIP_GAP": "LEAD_FLIP_GAP",
    "L_STRUCTURAL_GAP": "STRUCTURE_GAP",
    "M_STRONG_CONFIRM": "MARKET_CONFIRM",
    # Old broad names -> research/event labels, not first-test execution triggers.
    "FIGHT": "FIGHT_EVENT",
    "KILL_EVENT": "FIGHT_EVENT",
    "LEAD_FLIP": "LEAD_FLIP_EVENT",
    "STRUCTURAL_SWING": "STRUCTURE_EVENT",
}


def normalize_trigger(trigger: str) -> str:
    t = str(trigger or "").strip().upper()
    return TRIGGER_ALIASES.get(t, t)

# ── helpers ───────────────────────────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_set(name: str, default: str = "") -> set[str]:
    raw = os.getenv(name, default) or ""
    return {normalize_trigger(x) for x in raw.split(",") if x.strip()}


def _env_float_map(name: str, defaults: Dict[str, float]) -> Dict[str, float]:
    """Parse comma-separated TRIGGER:float overrides and merge with defaults.

    Example: TRIGGER_EDGE_FLOORS=FIGHT_GAP:0.05,MARKET_CONFIRM:0.05
    """
    out = {normalize_trigger(k): float(v) for k, v in defaults.items()}
    raw = os.getenv(name, "") or ""
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, val = part.split(":", 1)
        try:
            out[normalize_trigger(key)] = float(val.strip())
        except ValueError:
            continue
    return out


# ── trigger taxonomy ──────────────────────────────────────────────────────────

class Trigger:
    FIGHT_GAP       = "FIGHT_GAP"
    LEAD_FLIP_GAP   = "LEAD_FLIP_GAP"
    STRUCTURE_GAP   = "STRUCTURE_GAP"
    MARKET_CONFIRM  = "MARKET_CONFIRM"
    FIGHT_EVENT     = "FIGHT_EVENT"
    LEAD_FLIP_EVENT = "LEAD_FLIP_EVENT"
    STRUCTURE_EVENT = "STRUCTURE_EVENT"
    OVERREACTION    = "OVERREACTION"
    SLOW_BLEED      = "SLOW_BLEED"
    # ── new gap triggers ────────────────────────────────────────────────────
    KILL_UNSEEN     = "KILL_UNSEEN"   # kill in 30s game window but market never moved
    NW_SURGE        = "NW_SURGE"      # 3-min sustained NW build >5k + confirming kill, flat market


# Minimum edge floor per trigger. Global SIGNAL_MIN_EDGE remains a hard floor.
TRIGGER_EDGE_FLOORS: Dict[str, float] = {
    Trigger.FIGHT_GAP:      0.03,
    Trigger.LEAD_FLIP_GAP:  0.03,
    Trigger.STRUCTURE_GAP:  0.03,
    Trigger.STRUCTURE_EVENT:0.045,
    Trigger.MARKET_CONFIRM: 0.03,
    Trigger.OVERREACTION:   0.06,
    Trigger.SLOW_BLEED:     0.045,
    Trigger.KILL_UNSEEN:    0.03,
    Trigger.NW_SURGE:       0.035,
}

# Max edge ceiling per trigger (Draft-Trap guard).
MAX_EDGE = 0.80

# Triggers disabled before signal emission. Set via BLOCKED_TRIGGERS in .env.
# Parsed inside SignalEngine.__init__ after load_dotenv() has run.

# Event-driven triggers that use fight-lag direction mode (implied_dir from classify).
# For these, expected_move is anchored to the specific fight event, not ML fair value.
_EVENT_LAG_TRIGGERS = frozenset({
    Trigger.FIGHT_GAP, Trigger.KILL_UNSEEN, Trigger.MARKET_CONFIRM,
    Trigger.LEAD_FLIP_GAP, Trigger.NW_SURGE, Trigger.OVERREACTION,
})


# ── engine ────────────────────────────────────────────────────────────────────

class SignalEngine:
    """
    ML-powered scalp signal engine.
    Uses XGBoost ONNX model for win probability; falls back to heuristics.
    """

    def __init__(self, run_context: Optional[Dict[str, Any]] = None):
        self.run_context = run_context or {}
        # Trigger kill switch. Parsed here so .env has already been loaded by main.py.
        self.blocked_triggers = _env_set("BLOCKED_TRIGGERS", "")
        self.trigger_edge_floors = _env_float_map("TRIGGER_EDGE_FLOORS", TRIGGER_EDGE_FLOORS)
        self.last_rejection: Optional[Dict[str, Any]] = None
        self._last_rejection_keys: set[tuple] = set()

        # Market quality gates
        self.max_spread            = _env_float("SIGNAL_MAX_SPREAD", 0.04)
        self.max_mid_disagreement  = _env_float("SIGNAL_MAX_MID_DISAGREEMENT", 0.08)
        self.min_edge              = _env_float("SIGNAL_MIN_EDGE", 0.04)
        self.min_expected_move     = _env_float("SIGNAL_MIN_EXPECTED_MOVE", 0.025)
        # Max allowed adverse 30s market move before rejecting a signal.
        # Prevents adverse-selection entries when market is already pricing the event.
        # OVERREACTION is exempt (fade signals trade against the trend by design).
        # Set to 0 to disable. Default: 2 cents.
        self.max_adverse_trend_30s = _env_float("SIGNAL_MAX_ADVERSE_TREND_30S", 0.02)

        # Heuristic weights (used when ONNX model unavailable)
        self.lead_60s_weight  = _env_float("SIGNAL_LEAD_60S_WEIGHT", 0.000012)
        self.lead_30s_weight  = _env_float("SIGNAL_LEAD_30S_WEIGHT", 0.000006)
        self.lead_10s_weight  = _env_float("SIGNAL_LEAD_10S_WEIGHT", 0.000003)
        self.score_60s_weight = _env_float("SIGNAL_SCORE_60S_WEIGHT", 0.010)
        self.score_30s_weight = _env_float("SIGNAL_SCORE_30S_WEIGHT", 0.005)
        self.max_expected_move = _env_float("SIGNAL_MAX_EXPECTED_MOVE", 0.25)

        # Per-trigger cooldown: trigger → minimum seconds between signals of that type
        self.trigger_cooldowns: Dict[str, float] = {
            Trigger.SLOW_BLEED: 60.0,
            Trigger.OVERREACTION: 45.0,
            Trigger.FIGHT_GAP: 15.0,
            Trigger.LEAD_FLIP_GAP: 15.0,
            Trigger.STRUCTURE_GAP: 30.0,
            Trigger.MARKET_CONFIRM: 15.0,
            Trigger.KILL_UNSEEN: 30.0,
            Trigger.NW_SURGE: 60.0,
        }
        self.default_cooldown = _env_float("SIGNAL_DEFAULT_COOLDOWN_SEC", 30.0)
        # Last emission time per (match_key, trigger): match_key → {trigger → ts_ms}
        self._last_trigger_emit: Dict[str, Dict[str, int]] = {}

        # Late-join feature data warmup: require this many seconds of feature data
        self.feature_warmup_sec = _env_float("SIGNAL_FEATURE_WARMUP_SEC", 60.0)

        # Dedup state: match_key → (game_minute, last_fair_price)
        self._last_signal_state: Dict[str, tuple] = {}
        # Last real-event ts_ms per match_key (any trigger except SLOW_BLEED/catch-alls)
        self._last_event_ts_ms: Dict[str, int] = {}
        self.slow_bleed_max_event_age_s = _env_float("SLOW_BLEED_MAX_EVENT_AGE_S", 180.0)

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
        
        self.shadow_log_path = os.getenv("SHADOW_SIGNAL_LOG_PATH", "data/shadow_signals.csv")
        self._init_shadow_log()

    @staticmethod
    def _valid_token_id(token_id: Any) -> bool:
        v = str(token_id or "").strip().lower()
        return bool(v) and v not in {"0", "0x", "none", "null", "todo"} and "your_" not in v

    _SHADOW_HEADER = [
        "run_id", "pid", "git_sha", "started_at_ts_ms",
        "ts_ms", "match_key", "market_id", "game_time",
        "trigger", "trigger_strength", "side", "token_id",
        "nw_diff", "mid", "fair", "edge", "edge_floor", "max_edge", "action",
    ]

    def _init_shadow_log(self):
        os.makedirs(os.path.dirname(self.shadow_log_path) or ".", exist_ok=True)
        expected_header = ",".join(self._SHADOW_HEADER)
        if os.path.exists(self.shadow_log_path):
            try:
                with open(self.shadow_log_path, "r", newline="") as f:
                    first_line = f.readline().strip()
                if first_line != expected_header:
                    # Format mismatch — archive and start fresh.
                    import shutil
                    archive = self.shadow_log_path + ".old"
                    shutil.move(self.shadow_log_path, archive)
                else:
                    return  # file exists with correct header, append as normal
            except Exception:
                pass  # unreadable — fall through and recreate
        with open(self.shadow_log_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(self._SHADOW_HEADER)

    def _log_shadow(self, f: Dict[str, Any], trigger, trigger_strength, side, token_id, mid, fair, edge, edge_floor, action):
        ts_ms = int(time.time() * 1000)
        with open(self.shadow_log_path, "a", newline="") as f_out:
            writer = csv.writer(f_out)
            writer.writerow([
                self.run_context.get("run_id", os.getenv("RUN_ID", "")),
                self.run_context.get("pid", os.getpid()),
                self.run_context.get("git_sha", os.getenv("GIT_SHA", "")),
                self.run_context.get("started_at_ts_ms", ""),
                ts_ms,
                f.get("match_key", ""),
                f.get("market_id", ""),
                f.get("game_time"),
                trigger,
                trigger_strength,
                side,
                token_id,
                f.get("nw_diff", 0.0),
                mid,
                fair,
                edge,
                edge_floor,
                MAX_EDGE,
                action,
            ])

    def _reject(self, f: Dict[str, Any], reason: str, trigger: str = "", side: str = "",
                trigger_strength: str = "", expected_move: Optional[float] = None,
                fair: Optional[float] = None, edge: Optional[float] = None,
                edge_floor: Optional[float] = None, token_id: Optional[str] = None) -> None:
        """Store a throttled rejection record for DB logging by the strategy loop."""
        match_key = str(f.get("match_key", ""))
        game_minute = int(float(f.get("game_time", 0.0)) // 60)
        key = (match_key, game_minute, str(trigger or "").upper(), reason)
        should_log = key not in self._last_rejection_keys
        if should_log:
            self._last_rejection_keys.add(key)
            if len(self._last_rejection_keys) > 2000:
                self._last_rejection_keys.clear()
        self.last_rejection = {
            "should_log": should_log,
            "reason": reason,
            "trigger": normalize_trigger(trigger),
            "trigger_strength": str(trigger_strength or "").upper(),
            "side": side,
            "token_id": token_id,
            "match_key": match_key,
            "game_time": float(f.get("game_time", 0.0)),
            "mid": float(f.get("mid", 0.0)),
            "spread": float(f.get("spread", 1.0)),
            "combined_mid_disagreement": float(f.get("combined_mid_disagreement", 0.0)),
            "expected_move": expected_move,
            "fair_price": fair,
            "edge": edge,
            "edge_floor": edge_floor,
        }

    def classify(self, f: Dict[str, Any]) -> Dict[str, Any]:
        """Classify this snapshot with a non-overlapping trigger family.

        Returns a dict with trigger, strength, window, and market_state.
        """
        score_60 = abs(float(f.get("score_change_60s", 0.0)))
        nw_60 = abs(float(f.get("nw_change_60s", 0.0)))
        bldg = int(f.get("building_change_60s", 0))
        game_min = float(f.get("game_time", 0.0)) / 60.0
        market_60 = abs(float(f.get("market_change_60s", 0.0)))

        # Dynamic NW threshold: 2,000 at 15 min, +100/min thereafter.
        nw_thresh = 2000 + max(0.0, game_min - 15) * 100

        score_10s_raw = float(f.get("score_change_10s", 0.0))
        nw_10s_raw = float(f.get("nw_change_10s", 0.0))
        market_10s_raw = float(f.get("market_change_10s", 0.0))
        score_10s = abs(score_10s_raw)
        nw_10s = abs(nw_10s_raw)

        # Snapshot deltas: kills/NW that arrived with this API snapshot, independent
        # of game_time-window lookbacks (which are zero when game_time jumps 50+s).
        snap_score = int(f.get("snapshot_score_delta", 0))
        snap_nw    = float(f.get("snapshot_nw_delta", 0.0))
        snap_gt    = float(f.get("snapshot_gt_jump", 0.0))

        # Effective kill count: prefer 10s window; fall back to snapshot delta when
        # game_time jumped past the 10s lookback (snap_gt > 15 means the window is void).
        effective_score = score_10s_raw
        effective_nw    = nw_10s_raw
        if score_10s == 0 and snap_gt > 15 and snap_score != 0:
            effective_score = float(snap_score)
            effective_nw    = snap_nw

        eff_score_abs = abs(effective_score)

        # Directional shock only when score and radiant_lead agree.
        if effective_score > 0 and effective_nw > 0:
            shock_dir = 1
        elif effective_score < 0 and effective_nw < 0:
            shock_dir = -1
        else:
            shock_dir = 0

        strong_shock = shock_dir != 0 and eff_score_abs >= 2 and abs(effective_nw) >= 2000
        market_flat = abs(market_10s_raw) < 0.01
        market_confirmed = (
            (shock_dir == 1 and 0.01 <= market_10s_raw <= 0.05) or
            (shock_dir == -1 and -0.05 <= market_10s_raw <= -0.01)
        )

        market_60s_raw = float(f.get("market_change_60s", 0.0))

        if strong_shock and market_confirmed:
            return {"trigger": Trigger.MARKET_CONFIRM, "strength": "STRONG", "window": "10s", "market_state": "CONFIRMING", "implied_dir": shock_dir}

        nw_diff_now = float(f.get("nw_diff", 0.0))

        if market_flat:
            if strong_shock:
                return {"trigger": Trigger.FIGHT_GAP, "strength": "STRONG", "window": "10s", "market_state": "FLAT", "implied_dir": shock_dir}
            if eff_score_abs >= 1 and shock_dir != 0:
                # Single kill with NW agreement: discrete event with 4s market lag.
                # score>=2 → NORMAL (multi-kill, stronger signal)
                # score==1 → WEAK (single kill, reduced size)
                strength = "NORMAL" if eff_score_abs >= 2 else "WEAK"
                return {"trigger": Trigger.FIGHT_GAP, "strength": strength, "window": "10s", "market_state": "FLAT", "implied_dir": shock_dir}
            if eff_score_abs >= 2:
                # Multi-kill but NW direction conflicts. Score direction is still the best
                # directional signal: the team scoring more kills is usually the aggressor.
                kill_dir = 1 if effective_score > 0 else -1
                return {"trigger": Trigger.FIGHT_GAP, "strength": "WEAK", "window": "10s", "market_state": "FLAT", "implied_dir": kill_dir}

            if eff_score_abs >= 1 and shock_dir == 0 and abs(nw_diff_now) > 2000:
                # Single kill with NW delta conflict (buyback / aegis / bounty redistribution
                # makes the instant NW delta unreliable). Fall back to current NW position:
                # whoever is ahead right now is the more likely kill-taker.
                pos_agrees = (effective_score > 0 and nw_diff_now > 0) or \
                             (effective_score < 0 and nw_diff_now < 0)
                if pos_agrees:
                    kill_dir = 1 if effective_score > 0 else -1
                    return {"trigger": Trigger.FIGHT_GAP, "strength": "WEAK", "window": "10s", "market_state": "FLAT", "implied_dir": kill_dir}

            # LEAD_FLIP_GAP: NW sign crossed zero. Check game-time window AND snapshot delta
            # (the snapshot path catches flips inside game_time jumps where nw_change_10s=0).
            old_lead_10s = nw_diff_now - float(f.get("nw_change_10s", 0.0))
            snap_prev_nw = nw_diff_now - snap_nw
            window_flip   = old_lead_10s * nw_diff_now < 0 and abs(nw_diff_now) > 2000
            snapshot_flip = (snap_gt > 15 and snap_nw != 0
                             and snap_prev_nw * nw_diff_now < 0
                             and abs(nw_diff_now) > 1500)
            if window_flip or snapshot_flip:
                strength = "STRONG" if abs(nw_diff_now) > 3000 else "NORMAL"
                flip_dir = 1 if nw_diff_now > 0 else -1
                return {"trigger": Trigger.LEAD_FLIP_GAP, "strength": strength, "window": "10s", "market_state": "FLAT", "implied_dir": flip_dir}

            if bldg == 1:
                return {"trigger": Trigger.STRUCTURE_GAP, "strength": "NORMAL", "window": "60s", "market_state": "FLAT", "implied_dir": 0}

        # ── KILL_UNSEEN ───────────────────────────────────────────────────────────
        # A kill is visible in the 30s game-time window but the market never moved.
        # This fires when FIGHT_GAP missed it (no snapshot delta, kill arrived between
        # snapshots and is now visible via score_change_30s but market is still flat).
        score_30s_raw = float(f.get("score_change_30s", 0.0))
        nw_30s_raw    = float(f.get("nw_change_30s", 0.0))
        market_30s    = abs(float(f.get("market_change_30s", 0.0)))
        if (abs(score_30s_raw) >= 1
                and market_30s < 0.015          # market flat over the same 30s
                and market_10s_raw < 0.005      # and still flat right now
                and score_30s_raw * nw_30s_raw > 0):   # score and NW agree on direction
            kill_dir = 1 if score_30s_raw > 0 else -1
            return {"trigger": Trigger.KILL_UNSEEN, "strength": "NORMAL", "window": "30s", "market_state": "FLAT", "implied_dir": kill_dir}

        # ── NW_SURGE ──────────────────────────────────────────────────────────────
        # Team has built a sustained NW lead over 3 minutes (not just a single fight)
        # AND just got a confirming kill AND the market hasn't repriced the sustained push.
        nw_180 = float(f.get("nw_change_180s", 0.0))
        if (abs(nw_180) >= 5000
                and score_60 >= 1               # kill confirmed the sustained push
                and market_60 < 0.02            # market hasn't moved for the whole push
                and abs(nw_diff_now) >= 4000):  # current lead still substantial
            surge_strength = "STRONG" if abs(nw_180) >= 8000 else "NORMAL"
            surge_dir = 1 if nw_180 > 0 else -1
            return {"trigger": Trigger.NW_SURGE, "strength": surge_strength, "window": "180s", "market_state": "FLAT", "implied_dir": surge_dir}

        # Research/event labels. These are not enabled in the default live-probe config.
        old_lead_60s = nw_diff_now - float(f.get("nw_change_60s", 0.0))
        new_lead = nw_diff_now

        if market_60 >= 0.05 and score_60 == 0 and nw_60 < 1000 and abs(market_10s_raw) < 0.02:
            # Require market to have cooled (10s move < 2c) before fading the overreaction.
            # Firing while the market is still running creates adverse-selection maker fills.
            # Fade direction: if market moved up for Radiant, buy Dire (implied_dir=-1) and vice versa.
            fade_dir = -1 if market_60s_raw > 0 else 1
            return {"trigger": Trigger.OVERREACTION, "strength": "NORMAL", "window": "60s", "market_state": "MOVED", "implied_dir": fade_dir}
        if old_lead_60s * new_lead < 0 and nw_60 >= nw_thresh:
            return {"trigger": Trigger.LEAD_FLIP_EVENT, "strength": "NORMAL", "window": "60s", "market_state": "MOVED", "implied_dir": 0}
        if bldg == 1:
            return {"trigger": Trigger.STRUCTURE_EVENT, "strength": "NORMAL", "window": "60s", "market_state": "MOVED", "implied_dir": 0}
        if nw_60 >= nw_thresh and score_60 >= 2:
            return {"trigger": Trigger.FIGHT_EVENT, "strength": "STRONG", "window": "60s", "market_state": "MOVED", "implied_dir": 0}
        if score_60 >= 2:
            return {"trigger": Trigger.FIGHT_EVENT, "strength": "NORMAL", "window": "60s", "market_state": "MOVED", "implied_dir": 0}

        return {"trigger": Trigger.SLOW_BLEED, "strength": "NORMAL", "window": "60s", "market_state": "QUIET", "implied_dir": 0}

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

    def _fight_lag_expected(self, f: Dict[str, Any], trigger: str, implied_dir: int) -> float:
        """Compute expected move anchored to the specific fight event, not ML fair value.

        Direction is always implied_dir (from classify). Magnitude reflects kills + NW swing,
        scaled by mid so extreme-priced tokens move proportionally less."""
        mid = float(f.get("mid", 0.5))
        snap_gt = float(f.get("snapshot_gt_jump", 0.0))

        if trigger in {Trigger.FIGHT_GAP, Trigger.MARKET_CONFIRM}:
            if snap_gt > 15:
                nw_shock = abs(float(f.get("snapshot_nw_delta", 0.0)))
                kills    = abs(int(f.get("snapshot_score_delta", 0)))
            else:
                nw_shock = abs(float(f.get("nw_change_10s", 0.0)))
                kills    = abs(float(f.get("score_change_10s", 0.0)))
            raw = kills * 0.03 + nw_shock / 5000.0 * 0.06
        elif trigger == Trigger.KILL_UNSEEN:
            nw_shock = abs(float(f.get("nw_change_30s", 0.0)))
            kills    = abs(float(f.get("score_change_30s", 0.0)))
            raw = kills * 0.03 + nw_shock / 5000.0 * 0.05
        elif trigger == Trigger.LEAD_FLIP_GAP:
            raw = min(abs(float(f.get("nw_diff", 0.0))) / 5000.0 * 0.06, 0.10) + 0.04
        elif trigger == Trigger.NW_SURGE:
            raw = min(abs(float(f.get("nw_change_180s", 0.0))) / 50000.0, 0.08) + 0.02
        elif trigger == Trigger.OVERREACTION:
            raw = abs(float(f.get("market_change_60s", 0.0))) * 0.5
        else:
            raw = 0.0

        raw = max(raw, self.min_expected_move + 0.005)
        raw = min(raw, self.max_expected_move)

        if implied_dir > 0:
            return raw * (1.0 - mid) * 2.0
        else:
            return -raw * mid * 2.0

    def reset_match(self, match_key: str) -> None:
        self._last_signal_state.pop(match_key, None)
        self._last_trigger_emit.pop(match_key, None)
        self._last_event_ts_ms.pop(match_key, None)

    def generate(self, f: Dict[str, Any], has_open_orders: bool = True) -> Optional[Dict[str, Any]]:
        self.last_rejection = None

        # ── 0. Late-join guard ──
        # If the bot joined late, feature windows (nw_change_60s, score_change_60s, etc.)
        # will be 0, making SLOW_BLEED and ML_PREDICTION unreliable.
        game_time = float(f.get("game_time", 0.0))
        feature_elapsed = float(f.get("feature_elapsed_sec", 0.0))
        if feature_elapsed <= 0:
            # Infer from game_time minus a constant join offset if feature_elapsed not provided
            feature_elapsed = game_time
        if feature_elapsed < self.feature_warmup_sec and game_time < self.feature_warmup_sec:
            self._reject(f, "FEATURES_NOT_WARMED_UP", trigger="", side="")
            return None

        # ── 0b. Stale game_time guard ──
        # If Dota feed stopped advancing game_time, nw_change_* features are unreliable
        # (they compare current-vs-same-current producing 0s that mislead the model).
        if f.get("game_time_stale"):
            self._reject(f, "GAME_TIME_STALE", trigger="", side="")
            return None

        # ── 1. Quality ──
        spread = float(f.get("spread", 1.0))
        if spread > self.max_spread:
            self._reject(f, "SPREAD_TOO_WIDE")
            return None
        if float(f.get("combined_mid_disagreement", 0.0)) > self.max_mid_disagreement:
            self._reject(f, "BOOKS_DISAGREE")
            return None

        # ── 2. Dedup ──
        match_key = str(f.get("match_key", ""))
        game_minute = int(float(f.get("game_time", 0.0)) // 60)
        
        last_min, last_fair = self._last_signal_state.get(match_key, (-1, 0.0))
        # Hard lockout removed; replaced with 'Momentum Change' gate below.
        # if last_min == game_minute: return None

        # ── 3. Trigger ──
        classification = self.classify(f)
        trigger = normalize_trigger(classification.get("trigger"))
        trigger_strength = str(classification.get("strength") or "NORMAL").upper()
        trigger_window = str(classification.get("window") or "").lower()
        market_state = str(classification.get("market_state") or "").upper()
        if trigger == Trigger.FIGHT_EVENT and trigger_strength == "CONFLICTED":
            self._reject(f, "CONFLICTED_FIGHT_GAP", trigger=trigger, trigger_strength=trigger_strength)
            return None
        if trigger in self.blocked_triggers:
            self._reject(f, "BLOCKED_TRIGGER", trigger=trigger, trigger_strength=trigger_strength)
            return None

        # ── 3b. SLOW_BLEED game-activity gate ──
        now_ms = int(time.time() * 1000)
        # SLOW_BLEED is the catch-all for "no detected event". Gate it behind:
        # (a) near-zero recent game features, AND
        # (b) a real game event must have been detected within the last N seconds.
        # Fills on pure SLOW_BLEED are adverse-selected — market only hits our bid
        # when it's moving against us.
        if trigger == Trigger.SLOW_BLEED:
            nw_30 = abs(float(f.get("nw_change_30s", 0.0)))
            nw_60 = abs(float(f.get("nw_change_60s", 0.0)))
            sc_30 = abs(float(f.get("score_change_30s", 0.0)))
            sc_60 = abs(float(f.get("score_change_60s", 0.0)))
            snap_score_abs = abs(int(f.get("snapshot_score_delta", 0)))
            has_snapshot_kill = snap_score_abs >= 1 and float(f.get("snapshot_gt_jump", 0.0)) > 15
            if not has_snapshot_kill and nw_30 < 500 and nw_60 < 1500 and sc_30 < 1 and sc_60 < 1:
                self._reject(f, "SLOW_BLEED_NO_GAME_ACTIVITY", trigger=trigger, trigger_strength=trigger_strength)
                return None
            # Event-age gate: only bleed after a real event confirmed the trend
            last_event = self._last_event_ts_ms.get(str(f.get("match_key", "")), 0)
            if last_event and (now_ms - last_event) > self.slow_bleed_max_event_age_s * 1000:
                self._reject(f, "SLOW_BLEED_EVENT_TOO_STALE", trigger=trigger, trigger_strength=trigger_strength)
                return None

        # ── 4. Per-trigger cooldown ──
        match_key = str(f.get("match_key", ""))
        last_emit = self._last_trigger_emit.setdefault(match_key, {})
        cooldown_sec = self.trigger_cooldowns.get(trigger, self.default_cooldown)
        last_ts = last_emit.get(trigger, 0)
        if (now_ms - last_ts) < cooldown_sec * 1000:
            self._reject(f, "TRIGGER_COOLDOWN", trigger=trigger, trigger_strength=trigger_strength)
            return None

        # ── 5. Edge ──
        mid = float(f.get("mid", 0.5))
        
        # Recommendation 1: Time-Weighted Lead Sensitivity
        time_decay = 1.0 / (1.0 + (game_time / 2400.0)) 

        # Calculate Combat Shock Index (High velocity + High acceleration)
        velocity = float(f.get("nw_velocity", 0.0))
        acceleration = float(f.get("nw_acceleration", 0.0))
        combat_shock = 1.0
        if abs(velocity) > 150 and abs(acceleration) > 10:
            combat_shock = 1.25 

        # Recommendation 4: Snowball Filter (Peak Detection)
        # Instead of blocking, we flag it so RiskEngine can scale down the position size.
        is_snowball_climbing = False
        if abs(acceleration) > 20:
            if (velocity > 0 and acceleration > 0) or (velocity < 0 and acceleration < 0):
                is_snowball_climbing = True

        if self.ort_session:
            raw_prob = self.predict_win_prob(f)
            # Time-convergence decay: as game progresses, pull raw model output toward mid
            # Rationale: late-game fair prices converge to 0/1 (game is nearly decided),
            # but the model trained on all game times can overestimate the gap.
            # At game_time=0, no decay (weight=1.0 on model). At game_time=40min,
            # weight=0.7 on model, 0.3 on market mid.
            convergence_alpha = 1.0 / (1.0 + max(0.0, (game_time - 1800.0)) / 1800.0)
            converged_prob = convergence_alpha * raw_prob + (1.0 - convergence_alpha) * mid
            expected = (converged_prob - mid) * combat_shock
            signal_type = "ML_PREDICTION"
        else:
            expected = self._heuristic_expected_move(f) * combat_shock * time_decay
            signal_type = trigger

        # Latency Bump: If it's a DOTA_SPIKE_LATENCY, the ML model (which uses 60s features)
        # is likely underestimating the move. We add a heuristic bump.
        if trigger == "DOTA_SPIKE_LATENCY":
            bump = 0.03 if expected > 0 else -0.03
            expected += bump

        # Snapshot Kill Bump: FIGHT_GAP triggered by snapshot_score_delta means a kill arrived
        # inside a game_time jump. All windowed features (score_change_10s etc.) are zero because
        # there are no intermediate ticks — so both the ML model and heuristic return ~0.
        # Use snapshot_nw_delta to infer direction and add a minimum bump so the signal survives
        # the EXPECTED_MOVE_TOO_SMALL gate.
        snap_score = int(f.get("snapshot_score_delta", 0))
        snap_nw    = float(f.get("snapshot_nw_delta", 0.0))
        snap_gt    = float(f.get("snapshot_gt_jump", 0.0))
        if trigger == Trigger.FIGHT_GAP and snap_score != 0 and snap_gt > 15:
            # Direction from snapshot NW delta; fall back to score delta sign if NW is ambiguous.
            if snap_nw != 0:
                snap_dir = 1.0 if snap_nw > 0 else -1.0
            else:
                snap_dir = 1.0 if snap_score > 0 else -1.0
            # Magnitude: each kill contributes ~3c base move; NW swing scales it.
            nw_mag   = min(abs(snap_nw) / 5000.0, 0.06)   # caps at 6c for 5k NW
            kill_mag = abs(snap_score) * 0.03              # 3c per kill
            bump     = snap_dir * max(kill_mag + nw_mag, self.min_expected_move + 0.005)
            # Only override if windowed features gave us too-small an estimate.
            if abs(expected) < abs(bump):
                expected = bump

        if trigger == Trigger.KILL_UNSEEN:
            score_30 = float(f.get("score_change_30s", 0.0))
            nw_30    = float(f.get("nw_change_30s", 0.0))
            if score_30 != 0 or nw_30 != 0:
                kill_dir = (1.0 if score_30 > 0 else -1.0) if score_30 != 0 else (1.0 if nw_30 > 0 else -1.0)
                bump = kill_dir * max(abs(score_30) * 0.03 + abs(nw_30) / 5000.0 * 0.05,
                                      self.min_expected_move + 0.005)
                if abs(expected) < abs(bump):
                    expected = bump

        if trigger == Trigger.NW_SURGE:
            nw_180 = float(f.get("nw_change_180s", 0.0))
            if nw_180 != 0:
                surge_dir = 1.0 if nw_180 > 0 else -1.0
                bump = surge_dir * max(min(abs(nw_180) / 50000.0, 0.08) + 0.02,
                                       self.min_expected_move + 0.01)
                if abs(expected) < abs(bump):
                    expected = bump

        if abs(expected) < self.min_expected_move:
            self._reject(f, "EXPECTED_MOVE_TOO_SMALL", trigger=trigger, trigger_strength=trigger_strength, expected_move=expected)
            return None

        # Executable edge calculation (Aggressive Maker Mode: Bid + 0.001)
        side = "RADIANT" if expected > 0 else "DIRE"
        token_id = f.get("radiant_token_id" if expected > 0 else "dire_token_id", "")
        if not self._valid_token_id(token_id):
            self._reject(
                f, "MISSING_TARGET_TOKEN_ID", trigger=trigger, side=side,
                trigger_strength=trigger_strength, expected_move=expected, token_id=None,
            )
            return None

        raw_bid = float(f.get("radiant_best_bid" if expected > 0 else "dire_best_bid", 0.0))
        entry = max(raw_bid + 0.001, 0.01)
        fair = min(0.99, max(0.01, mid + expected if expected > 0 else (1.0 - mid) + abs(expected)))
        edge = fair - entry
        
        # ── 5. Log Shadow (Reduced Noise) ──
        # Global min edge is a hard floor; trigger floors can only make it stricter.
        edge_floor = max(self.min_edge, self.trigger_edge_floors.get(trigger, self.min_edge))
        
        # Only log if this is a new minute/trigger/side/token for this match
        shadow_key = (match_key, game_minute, trigger, side, str(token_id))
        if not hasattr(self, "_last_shadow_keys"):
            self._last_shadow_keys = set()
        
        if edge < edge_floor:
            shadow_action = "REJECT_EDGE_TOO_SMALL"
        elif edge > MAX_EDGE:
            shadow_action = "REJECT_EDGE_TOO_LARGE"
        else:
            shadow_action = "FIRE"

        if shadow_key not in self._last_shadow_keys:
            self._log_shadow(f, trigger, trigger_strength, side, token_id, mid, fair, edge, edge_floor, shadow_action)
            self._last_shadow_keys.add(shadow_key)
            # Cleanup old keys to prevent memory leak
            if len(self._last_shadow_keys) > 1000:
                self._last_shadow_keys.clear()

        if edge < edge_floor:
            self._reject(f, "EDGE_TOO_SMALL", trigger=trigger, side=side, trigger_strength=trigger_strength, expected_move=expected, fair=fair, edge=edge, edge_floor=edge_floor, token_id=str(token_id))
            return None
        if edge > MAX_EDGE:
            self._reject(f, "EDGE_TOO_LARGE", trigger=trigger, side=side, trigger_strength=trigger_strength, expected_move=expected, fair=fair, edge=edge, edge_floor=edge_floor, token_id=str(token_id))
            return None

        # Market-trend agreement gate: reject if market trended against signal direction
        # over the past 30s. OVERREACTION is exempt — it fades a move by design.
        if trigger != Trigger.OVERREACTION and self.max_adverse_trend_30s > 0:
            market_30s = float(f.get("market_change_30s", 0.0))
            if (side == "RADIANT" and market_30s < -self.max_adverse_trend_30s) or \
               (side == "DIRE"    and market_30s >  self.max_adverse_trend_30s):
                self._reject(f, "ADVERSE_MARKET_TREND", trigger=trigger, side=side,
                             trigger_strength=trigger_strength, expected_move=expected,
                             fair=fair, edge=edge, edge_floor=edge_floor)
                return None

        # Intra-minute Momentum Check:
        # If we already fired in this minute, only fire again if fair price moved > 3% or we have no open orders (Persistence Mode)
        if last_min == game_minute and has_open_orders:
            if abs(fair - last_fair) < 0.03:
                self._reject(f, "INTRA_MINUTE_MOMENTUM_TOO_SMALL", trigger=trigger, side=side, trigger_strength=trigger_strength, expected_move=expected, fair=fair, edge=edge, edge_floor=edge_floor)
                return None

        # ── 5. Regime Detection (Snowball Guard) ──
        # Lead > 10k, Market Volatility > 3 cents in 60s, Game Time > 20m
        is_snowball = (
            abs(float(f.get("nw_diff", 0.0))) >= 10000 and
            abs(float(f.get("market_change_60s", 0.0))) >= 0.03 and
            float(f.get("game_time", 0.0)) >= 1200
        )

        # ── 6. Emit ──
        self._last_signal_state[match_key] = (game_minute, fair)
        self._last_trigger_emit.setdefault(match_key, {})[trigger] = now_ms
        # Track last real-event timestamp for SLOW_BLEED event-age gate
        _real_event_triggers = {
            Trigger.FIGHT_GAP, Trigger.LEAD_FLIP_GAP, Trigger.STRUCTURE_GAP,
            Trigger.MARKET_CONFIRM, Trigger.KILL_UNSEEN, Trigger.NW_SURGE,
        }
        if trigger in _real_event_triggers:
            self._last_event_ts_ms[match_key] = now_ms
        return {
            "side": "BUY_RADIANT_YES" if expected > 0 else "BUY_DIRE_YES",
            "trigger": trigger,
            "trigger_strength": trigger_strength,
            "market_lag": float(f.get("market_lag", 0.0)),
            "trigger_window": trigger_window,
            "market_state": market_state,
            "signal_type": signal_type,
            "expected_move": expected,
            "fair_price": fair,
            "edge": edge,
            "entry_price_target": entry,
            "is_snowball_regime": is_snowball,
            "is_snowball_climbing": is_snowball_climbing
        }
